"""EQAL runtime API v0.4. Routes under /v1; header X-API-Key: <tenant key>.
Every write is an INSERT of a new record version. Reports read the latest version per case."""
import os, json, hashlib, hmac, statistics as st, datetime as dt
from pathlib import Path
from fastapi import FastAPI, Depends, HTTPException, Header, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from sqlalchemy import select, func, text
from .db import Session, Tenant, Record, init_db, engine
from .runtime import Runtime, Case, load_policy, seal, AUT
from .providers import get_provider

if os.getenv("SENTRY_DSN"):
    import sentry_sdk; sentry_sdk.init(dsn=os.environ["SENTRY_DSN"], send_default_pii=False)

app = FastAPI(title="EQAL runtime", version="0.4")
PACK_NAME = os.getenv("EQAL_POLICY_PACK", "ap")
POLICY = load_policy(PACK_NAME)
RUNTIME = Runtime(POLICY, get_provider(os.getenv("EQAL_PROVIDER", "simulated")))
MATURITY_DAYS = int(os.getenv("EQAL_MATURITY_DAYS", "30"))
PACK_TITLES = {"AP": "Accounts payable", "SCM": "Supply chain execution"}
UNITS = {"AP": "invoice", "SCM": "exception"}

@app.on_event("startup")
def _startup():
    init_db()
    tid, key = os.getenv("EQAL_BOOTSTRAP_TENANT"), os.getenv("EQAL_BOOTSTRAP_API_KEY")
    if tid and key:
        with Session() as s:
            if not s.get(Tenant, tid): s.add(Tenant(tenant_id=tid, name=tid, api_key_hash=_hash(key))); s.commit()

def _hash(k): return hashlib.sha256(k.encode()).hexdigest()
def tenant(x_api_key: str = Header(...)) -> str:
    h = _hash(x_api_key)
    with Session() as s:
        for t in s.execute(select(Tenant)).scalars():
            if hmac.compare_digest(t.api_key_hash, h): return t.tenant_id
    raise HTTPException(401, "invalid API key")

# ---------------------------------------------------------------- models
class DecideIn(BaseModel):
    case_id: str
    input_refs: dict = Field(default_factory=dict)      # evidence fields only
    signals: dict = Field(default_factory=dict)         # risk and classification signals
    flags: dict = Field(default_factory=dict)           # autonomy_rule predicates -> bool
    consequence: float | None = None
    harm_class: str = "financial"
    reversible: bool = True
    evidence_hashes: dict = Field(default_factory=dict)
    observe_only: bool = False

class OutcomeIn(BaseModel):
    kind: str = Field("observed", pattern="^(observed|estimated|counterfactual|realized)$")
    value: str
    correct: bool | None = None
    truth: bool | None = None                            # which verdict was right; enables shadow attribution
    realised_effect: float | None = None
    human: dict | None = None                            # {"touches":2,"decision":"approve","override":false,"approver_ids":[...]}
    detail: dict | None = None

# ---------------------------------------------------------------- persistence helpers
def _insert(rec: dict, tid: str):
    with Session() as s:
        s.add(Record(tenant_id=tid, case_id=rec["case_id"], version=rec["version"], pack=rec["pack"], exception_class=rec["exception_class"],
                     autonomy_effective=rec["autonomy_effective"], action=rec["action"], cost=rec["cost"], latency_ms=rec["latency_ms"],
                     human_touches=(rec.get("outcome") or {}).get("human_touches", 0), maturity=rec["maturity"], payload=json.dumps(rec, default=str)))
        s.commit()

def _latest(tid: str, case_id: str | None = None):
    with Session() as s:
        sub = select(Record.case_id, func.max(Record.version).label("v")).where(Record.tenant_id == tid)
        if case_id: sub = sub.where(Record.case_id == case_id)
        sub = sub.group_by(Record.case_id).subquery()
        rows = s.execute(select(Record).join(sub, (Record.case_id == sub.c.case_id) & (Record.version == sub.c.v)).where(Record.tenant_id == tid).order_by(Record.created_at)).scalars().all()
        return [json.loads(r.payload) for r in rows]

# ---------------------------------------------------------------- routes
@app.get("/health")
def health(): return {"ok": True}

@app.get("/health/full")
def health_full():
    with engine.connect() as c: c.execute(text("select 1"))
    return {"ok": True, "db": True, "policy": f"{POLICY['pack']} v{POLICY['version']} ({POLICY['lifecycle']})", "provider": type(RUNTIME.prov).__name__}

@app.get("/v1/policy")
def policy(tid: str = Depends(tenant)): return POLICY

@app.post("/v1/decide")
def decide(body: DecideIn, tid: str = Depends(tenant)):
    if _latest(tid, body.case_id): raise HTTPException(409, "case already decided; append an outcome instead")
    case = Case(body.case_id, body.input_refs, body.signals, body.flags, body.consequence, body.harm_class, body.reversible, body.evidence_hashes)
    rec = seal(RUNTIME.decide(case, tid, observe_only=body.observe_only))
    rec["input_refs"] = {k: v for k, v in rec["input_refs"].items() if not k.startswith("_")}
    _insert(rec, tid)
    return rec

@app.post("/v1/outcomes/{case_id}")
def outcome(case_id: str, body: OutcomeIn, tid: str = Depends(tenant)):
    prior = _latest(tid, case_id)
    if not prior: raise HTTPException(404, "unknown case")
    prev = prior[0]
    rec = dict(prev); rec["version"] = prev["version"] + 1; rec["prior_hash"] = prev.get("record_hash")
    touches = (body.human or {}).get("touches", (prev.get("human") or {}).get("approvers", 0) if prev.get("human") else 0)
    shadow_ok = None
    if prev.get("shadow") and body.truth is not None and prev["shadow"].get("verdict") is not None:
        shadow_ok = prev["shadow"]["verdict"] == body.truth
    rec["outcome"] = dict(kind=body.kind, value=body.value, correct=body.correct, truth=body.truth, realised_effect=body.realised_effect or 0.0,
                          human_touches=touches, human_cost=touches * POLICY["human_touch_cost"], override=(body.human or {}).get("override", False),
                          approver_ids=(body.human or {}).get("approver_ids", []), shadow_correct=shadow_ok, detail=body.detail or {},
                          observed_at=dt.datetime.utcnow().isoformat())
    rec["maturity"] = "OBSERVED"
    seal(rec); _insert(rec, tid)
    return rec

@app.post("/v1/mature")
def mature(tid: str = Depends(tenant), days: int = MATURITY_DAYS):
    """Promote OBSERVED records older than `days` to MATURE by writing a new version. Idempotent."""
    n = 0; cutoff = dt.datetime.utcnow() - dt.timedelta(days=days)
    for prev in _latest(tid):
        if prev["maturity"] != "OBSERVED": continue
        if dt.datetime.fromisoformat(prev["outcome"]["observed_at"]) > cutoff: continue
        rec = dict(prev); rec["version"] = prev["version"] + 1; rec["prior_hash"] = prev.get("record_hash"); rec["maturity"] = "MATURE"
        seal(rec); _insert(rec, tid); n += 1
    return {"matured": n}

@app.get("/v1/ledger")
def ledger(tid: str = Depends(tenant), limit: int = Query(50, le=500), human_only: bool = False, case_id: str | None = None):
    recs = _latest(tid, case_id)
    if human_only: recs = [r for r in recs if r.get("human")]
    return recs[-limit:]

@app.get("/v1/ledger/{case_id}/versions")
def versions(case_id: str, tid: str = Depends(tenant)):
    with Session() as s:
        rows = s.execute(select(Record).where(Record.tenant_id == tid, Record.case_id == case_id).order_by(Record.version)).scalars().all()
    return [json.loads(r.payload) for r in rows]

# ---------------------------------------------------------------- P&L ([0044]-[0049]) and governance
def _pnl(tid: str) -> dict:
    recs = _latest(tid); n = len(recs); H = POLICY["human_touch_cost"]; ec = POLICY["exception_classes"]
    if n == 0: return dict(n=0)
    obs = [r for r in recs if r.get("outcome")]
    ai = sum(r["cost"] for r in recs); hu = sum(r["outcome"]["human_cost"] for r in obs) + sum((r["human"] or {}).get("approvers", 0) * H for r in recs if not r.get("outcome") and r.get("human"))
    touchless = sum(1 for r in recs if not r.get("human")) / n
    judged = [r for r in obs if r["outcome"]["correct"] is not None]
    correct = (sum(1 for r in judged if r["outcome"]["correct"]) / len(judged)) if judged else None
    by_mat = {m: sum(r["cost"] for r in recs if r["maturity"] == m) for m in ("PENDING", "OBSERVED", "MATURE")}
    attribution = {}
    for k, pol in ec.items():
        if not pol.get("shadow_reference"): continue
        sel = [r for r in obs if r["exception_class"] == k and r.get("shadow") and r["outcome"]["shadow_correct"] is not None]
        mature = [r for r in sel if r["maturity"] == "MATURE"]
        basis = mature if mature else sel                    # matured outcomes when available; otherwise reported as unproven
        if not basis: continue
        a = sum(1 for r in basis if r["outcome"]["shadow_correct"]) / len(basis); theta = pol["budget"]["evidence"]
        above = sum(sum(s["cost"] for s in r["path"][1:]) for r in basis)
        attribution[k] = dict(n=len(basis), shadow_accuracy=a, threshold=theta, basis=("MATURE" if mature else "OBSERVED"),
                              avoidable=(above if (a >= theta and mature) else 0.0), unproven=(above if (a >= theta and not mature) else 0.0), justified=a < theta)
    held = [r for r in obs if r["outcome"]["value"] in ("impersonation_blocked", "noncompliant_source_held")]
    by_class = {}
    for k, pol in ec.items():
        rs = [r for r in recs if r["exception_class"] == k]; b = pol["budget"]
        by_class[k] = dict(name=k.replace("_", " "), n=len(rs), avg_cost=st.mean(r["cost"] for r in rs) if rs else 0.0,
                           touchless=(sum(1 for r in rs if not r.get("human")) / len(rs)) if rs else 0.0,
                           max_cost=(None if b["max_cost"] is None else (b["max_cost"] if not isinstance(b["max_cost"], dict) else f"≤{b['max_cost']['cap']} by consequence")),
                           min_confidence=b["evidence"], evidence=", ".join(pol["evidence_required"]),
                           autonomy=(b["autonomy"] if "autonomy_rule" not in pol else f"{b['autonomy']} if rule, else {pol['autonomy_rule']['otherwise']}"),
                           human=f"{pol['human_rule']['role']} ×{pol['human_rule']['approvers']} ({pol['human_rule']['when']})")
    cons = [r for r in recs if r["conservatively_routed"]]
    return dict(n=n, ai_cost=ai, human_cost=hu, total=ai + hu, per_case=(ai + hu) / n, touchless=touchless, correct=correct, judged=len(judged),
                realised=sum(r["outcome"]["realised_effect"] for r in obs), held=len(held), capacity_est=n * H - hu, manual_per_case=H,
                overrides=sum(1 for r in obs if r["outcome"]["override"]), none_autonomy=sum(1 for r in recs if r["autonomy_effective"] == "NONE"),
                unauthorised=sum(1 for r in recs if r["autonomy_effective"] == "NONE" and r["action"].startswith("act")),
                lens_demoted=sum(1 for r in recs if r["autonomy_effective"] != r["autonomy_policy"] and not r.get("observe_only")),
                conservative=len(cons), conservative_cost=sum(r["cost"] for r in cons),
                conservative_caught=sum(1 for r in cons if r.get("outcome") and r["outcome"]["value"] == "impersonation_blocked"),
                spend_by_maturity=by_mat, attribution=attribution, by_class=by_class,
                observe_only=sum(1 for r in recs if r.get("observe_only")),
                compute_ms=sum(r["latency_ms"] for r in recs), sample=[r for r in recs if r.get("human")][:6],
                range=_range(tid))

def _range(tid):
    with Session() as s:
        lo, hi = s.execute(select(func.min(Record.created_at), func.max(Record.created_at)).where(Record.tenant_id == tid)).one()
    return f"{lo:%d %b %Y} to {hi:%d %b %Y}" if lo and hi else ""

@app.get("/v1/pnl")
def pnl(tid: str = Depends(tenant)): return _pnl(tid)

@app.get("/v1/governance")
def governance(tid: str = Depends(tenant)):
    """Assertions computed from the ledger, not scores. [0067] autonomy evidence coverage per class."""
    recs = _latest(tid); n = len(recs); ec = POLICY["exception_classes"]
    if n == 0: return dict(n=0)
    obs = [r for r in recs if r.get("outcome")]
    cov = {}
    for k, pol in ec.items():
        rs = [r for r in obs if r["exception_class"] == k]; acted = [r for r in rs if r["action"].startswith("act")]
        cov[k] = dict(decisions=len(rs), acted=len(acted), acted_correct=sum(1 for r in acted if r["outcome"]["correct"]),
                      mature=sum(1 for r in rs if r["maturity"] == "MATURE"), autonomy_ceiling=pol["budget"]["autonomy"])
    return dict(n=n, pack=f"{POLICY['pack']}/{POLICY['version']}", lifecycle=POLICY["lifecycle"],
                actions_on_none_autonomy=sum(1 for r in recs if r["autonomy_effective"] == "NONE" and r["action"].startswith("act")),
                inside_active_pack=sum(1 for r in recs if r["pack"] == f"{POLICY['pack']}/{POLICY['version']}") / n,
                approver_count_met=sum(1 for r in obs if r.get("human") and r["outcome"]["human_touches"] >= r["human"]["approvers"]),
                approver_count_required=sum(1 for r in obs if r.get("human")),
                overrides=[dict(case_id=r["case_id"], cls=r["exception_class"], outcome=r["outcome"]["value"]) for r in obs if r["outcome"]["override"]][:50],
                invocation_failures=sum(1 for r in recs for s in r["path"] if s["outcome_code"] != "OK"),
                declined_paths=sum(len(r["declined"]) for r in recs), conservatively_routed=sum(1 for r in recs if r["conservatively_routed"]),
                lens_demotions=sum(1 for r in recs if r["autonomy_effective"] != r["autonomy_policy"] and not r.get("observe_only")),
                observe_only_records=sum(1 for r in recs if r.get("observe_only")),
                autonomy_evidence_coverage=cov, spend_by_maturity={m: sum(r["cost"] for r in recs if r["maturity"] == m) for m in ("PENDING", "OBSERVED", "MATURE")},
                unproven_spend=sum(a.get("unproven", 0) for a in _pnl(tid)["attribution"].values()))

@app.get("/v1/pnl/report", response_class=HTMLResponse)
def report(tid: str = Depends(tenant)): return render(_pnl(tid))

# ---------------------------------------------------------------- report
def eur(x): return f"€{x:,.2f}"
def render(s):
    tpl = (Path(__file__).parent / "report_template.html").read_text()
    if s.get("n", 0) == 0: return tpl.replace("{{N}}", "0").replace("{{FINDING}}", "<p class=note>No decisions yet.</p>")
    att = next(iter(s["attribution"].values()), None)
    rows = "".join(f"<tr><td>{c['name']}</td><td class=num>{c['max_cost'] if isinstance(c['max_cost'], str) else ('€%.3f'%c['max_cost'] if c['max_cost'] is not None else 'no limit')}</td>"
                   f"<td class=num>{'%.0f%%'%(c['min_confidence']*100)}</td><td>{c['evidence']}</td><td>{c['autonomy']}</td><td>{c['human']}</td>"
                   f"<td class=num>{c['n']} · €{c['avg_cost']:.3f} avg · {c['touchless']:.0%} touchless</td></tr>" for c in s["by_class"].values())
    lrows = "".join(f"<tr{' class=flag' if r.get('outcome') and r['outcome']['value']=='impersonation_blocked' else ''}><td>{r['case_id']}</td><td>{r['exception_class'].replace('_',' ')}{' <span class=leak>(conservative)</span>' if r['conservatively_routed'] else ''}</td>"
                    f"<td>{' → '.join(p['cls'] for p in r['path']) or '—'}</td><td class=num>€{r['cost']:.3f}</td><td class=num>{('%.1f%%'%(r['confidence']*100)) if r['confidence'] else '—'}</td>"
                    f"<td>{r['action']} ({r['autonomy_effective']})</td><td>{r['human']['role']} ×{r['human']['approvers']}{' (override)' if r.get('outcome') and r['outcome']['override'] else ''}</td>"
                    f"<td>{(r['outcome']['value'].replace('_',' ') + ' · ' + r['maturity'].lower()) if r.get('outcome') else 'awaiting outcome'}</td></tr>" for r in s["sample"])
    if att and att["avoidable"] > 0:
        finding = f'<div class="finding"><h2>{eur(att["avoidable"])} you didn\'t need to spend <span class="tag">counterfactual, evidence-conditioned, matured</span></h2><p>{att["n"]} escalated cases; the lower class\'s stored shadow answers were {att["shadow_accuracy"]:.1%} correct on matured outcomes, above the {att["threshold"]:.0%} threshold.</p></div>'
    elif att and att["unproven"] > 0:
        finding = f'<div class="finding" style="border-left-color:#C77700"><h2>{eur(att["unproven"])} unproven <span class="tag">counterfactual, not yet matured</span></h2><p>{att["n"]} escalated cases; shadow accuracy {att["shadow_accuracy"]:.1%} is above the {att["threshold"]:.0%} threshold on observed outcomes, but none has matured. Neither waste nor justified until it does.</p></div>'
    else:
        finding = f'<div class="finding" style="border-left-color:var(--gain)"><h2>No avoidable intelligence spend found <span class="tag">counterfactual, evidence-conditioned</span></h2><p>{att["n"] if att else 0} escalated cases; shadow accuracy {att["shadow_accuracy"] if att else 0:.1%} against a {att["threshold"] if att else 0:.0%} threshold ({att["basis"].lower() if att else "no"} outcomes), so the escalations were justified.</p></div>'
    correct = f"{s['correct']:.2%} ({s['judged']} judged)" if s["correct"] is not None else "awaiting outcomes"
    rep = {"{{N}}": f"{s['n']:,}", "{{TOUCHLESS}}": f"{s['touchless']:.1%}", "{{ESCALATED}}": f"{1-s['touchless']:.1%}", "{{AI}}": eur(s["ai_cost"]), "{{HUMAN}}": eur(s["human_cost"]),
           "{{TOTAL}}": eur(s["total"]), "{{PER}}": f"€{s['per_case']:.3f}", "{{MANUAL_PER}}": f"€{s['manual_per_case']:.2f}", "{{EXPOSURE}}": eur(s["realised"]), "{{BLOCKED}}": str(s["held"]),
           "{{CAPACITY}}": eur(s["capacity_est"]), "{{CORRECT}}": correct, "{{OVERRIDES}}": str(s["overrides"]), "{{REFUSED}}": str(s["none_autonomy"]),
           "{{BASELINE_BOX}}": "", "{{FINDING}}": finding, "{{PACK_TITLE}}": PACK_TITLES.get(POLICY["pack"], POLICY["pack"]),
           "{{PROVIDER_LABEL}}": ("simulated provider" if type(RUNTIME.prov).__name__ == "SimulatedProvider" else "live run"),
           "{{UNIT}}": UNITS.get(POLICY["pack"], "case"), "{{UNIT_CAP}}": UNITS.get(POLICY["pack"], "case").capitalize(), "{{RANGE}}": s.get("range", ""), "{{GRID_ROWS}}": rows, "{{LEDGER_ROWS}}": lrows,
           "{{POLICY_VERSION}}": str(POLICY["version"]),
           "{{CONSERVATIVE}}": f"{s['conservative']} conservatively routed (€{s['conservative_cost']:.2f}, {s['conservative_caught']} impersonation attempts among them); {s['lens_demoted']} demoted by the risk lens; spend by maturity: pending €{s['spend_by_maturity']['PENDING']:.2f}, observed €{s['spend_by_maturity']['OBSERVED']:.2f}, mature €{s['spend_by_maturity']['MATURE']:.2f}."}
    for k, v in rep.items(): tpl = tpl.replace(k, v)
    return tpl
