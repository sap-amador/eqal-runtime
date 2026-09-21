"""EQAL runtime core v0.4 — a port of the frozen v0.3 reference implementation
(02-reference/simulate.py) with three deliberate differences:

1. autonomy_rule predicates are evaluated by the adapter and arrive as booleans in
   case.flags (the reference evaluated one AP-specific predicate inline);
2. consequence and consequence-relative budgets are resolved per case ([0028]);
3. the record carries the fields the filed specification describes: eligibility
   determinations with reason codes, invocation outcome codes, declined paths,
   adapter id, pack lifecycle state, harm class, evidence hashes, tokens, region.

Vocabulary: autonomy NONE < RECOMMEND < ACT_NOTIFY < ACT; level ceiling in {0,1,2,3,H};
classes D/S/L/F/M. No ERP, no vendor, no simulation in this file.
"""
from __future__ import annotations
import copy, hashlib, json, os, yaml
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

POLICY_DIR = Path(__file__).parent / "policy"
AUT = ["NONE", "RECOMMEND", "ACT_NOTIFY", "ACT"]

def load_policy(pack: str) -> dict:
    p = yaml.safe_load((POLICY_DIR / f"{pack}.yaml").read_text())
    p.setdefault("lifecycle", "ACTIVE")
    return p

@dataclass
class Invocation:
    verdict: bool | None
    confidence: float
    outcome_code: str = "OK"          # OK | TIMEOUT | ERROR | REFUSED | MALFORMED
    tokens_in: int = 0
    tokens_out: int = 0
    adapter_id: str | None = None
    provider_region: str | None = None
    elapsed_ms: int = 0
    reason: str = ""

class Provider(Protocol):
    def invoke(self, icls: str, exception_class: str, case: "Case") -> Invocation: ...
    def classify(self, icls: str, case: "Case") -> tuple[list[str], float]: ...

@dataclass
class Case:
    case_id: str
    input_refs: dict                      # evidence fields only (adapter has redacted)
    signals: dict = field(default_factory=dict)     # risk-lens and classification signals
    flags: dict = field(default_factory=dict)       # autonomy_rule predicate results, e.g. {"variance_lte": True}
    consequence: float | None = None                # adapter-supplied (e.g. line_cost); pack default otherwise
    harm_class: str = "financial"
    reversible: bool = True
    evidence_hashes: dict = field(default_factory=dict)

class Runtime:
    def __init__(self, pack: dict, provider: Provider):
        self.p, self.prov = pack, provider
        self.C = pack["classes"]

    # ---- helpers ------------------------------------------------------------
    def restrictiveness(self, k):                                            # [0031]
        pol = self.p["exception_classes"][k]
        return (AUT.index(pol["budget"]["autonomy"]), 0 if pol["level_ceiling"] == "H" else 1, -(pol["budget"]["evidence"] or 1))

    def resolve_budget(self, pol: dict, case: Case) -> tuple[dict, float]:   # [0028]
        b = copy.deepcopy(pol["budget"]); c = pol["consequence"]
        cons = case.consequence if case.consequence is not None else (float(c["default"]) if isinstance(c, dict) else float(c))
        if isinstance(b.get("max_cost"), dict):
            b["max_cost"] = round(min(b["max_cost"]["cap"], b["max_cost"]["fraction_of_consequence"] * cons), 4)
        return b, cons

    def classify(self, case: Case):                                          # [0030]
        cfg, log = self.p["classification"], []
        for icls in cfg["ladder"]:
            if cfg["validation"].get(icls) == "not_permitted":
                log.append(dict(classifier=icls, eligible=False, reason="NOT_PERMITTED")); continue
            cands, conf = self.prov.classify(icls, case)
            log.append(dict(classifier=icls, eligible=True, candidates=cands, confidence=round(conf, 4)))
            if conf >= cfg["threshold"] and len(cands) == 1: return cands[0], log, False
            if icls == "D" and len(cands) > 1: return min(cands, key=self.restrictiveness), log, True
        seen = {c for e in log for c in e.get("candidates", [])}
        return min(seen, key=self.restrictiveness), log, True

    def risk(self, case: Case):                                              # [0042]
        rl = self.p["risk_lens"]; s = case.signals
        score = min(1.0, sum(rl["weights"][k] for k in rl["signals"] if s.get(k)))
        return round(score, 3), (rl["demote_to"] if score >= rl["threshold"] else "ACT")

    def policy_autonomy(self, pol: dict, case: Case) -> str:
        aut = pol["budget"]["autonomy"]
        if "autonomy_rule" in pol:
            ar = pol["autonomy_rule"]; key = next(x for x in ar if x.endswith("_if"))
            preds = ar[key]                                  # dict of predicate names -> policy values
            if all(case.flags.get(name) is True for name in preds): aut = key[:-3]
            else: aut = ar["otherwise"]
        return aut

    # ---- the decision ---------------------------------------------------------
    def decide(self, case: Case, tenant_id: str, *, observe_only: bool = False) -> dict:
        k, clog, conservative = self.classify(case)                          # 310
        pol = self.p["exception_classes"][k]; b, cons = self.resolve_budget(pol, case)   # 320
        score, lens = self.risk(case)                                        # 330
        aut = self.policy_autonomy(pol, case)
        eff = AUT[min(AUT.index(aut), AUT.index(lens))]                      # min(policy, lens)
        if observe_only: eff = "NONE"                                        # [0076]
        eligibility, path, shadow, declined, envelope, shadows = [], [], None, [], [], []
        for x in (case.input_refs.get("extraction") and [case.input_refs["extraction"]] or []):   # adapter-side extraction step (e.g. Document AI / vision model)
            envelope.append(dict(component="extraction", cls="S", provider=str(x.get("model", "")).split("-")[0] or "extraction", service=x.get("model"), native_meter="tokens" if "tokens_in" in x else "documents",
                                 native_quantity=dict(tokens_in=x.get("tokens_in", 0), tokens_out=x.get("tokens_out", 0)) if "tokens_in" in x else dict(documents=1),
                                 contract_rate=None, direct_cost=x.get("cost_usd"), allocated_cost=None, currency="USD", quantity_source=x.get("quantity_source", "RESPONSE"), cost_evidence="ESTIMATED"))
        cost, lat, level, reason, conf, verdict = 0.0, 0, 0, None, None, None
        tokens = dict(tokens_in=0, tokens_out=0); adapters, regions = set(), set()
        ceiling = pol["level_ceiling"]
        for icls in pol["path"]:                                             # 340
            val = pol.get("validation", {}).get(icls, "permitted")
            if val == "not_permitted":
                eligibility.append(dict(cls=icls, eligible=False, reason="NOT_PERMITTED")); declined.append(icls); continue
            spec = self.C[icls]
            if val == "shadow_only":
                r = self.prov.invoke(icls, k, case)
                shadow = dict(cls=icls, verdict=r.verdict, confidence=r.confidence, outcome_code=r.outcome_code)
                shadows.append(dict(role="shadow", position="validation", cls=icls, verdict=r.verdict, confidence=round(r.confidence, 4), outcome_code=r.outcome_code, cost=spec["cost"]))
                eligibility.append(dict(cls=icls, eligible=True, reason="SHADOW_ONLY")); continue
            if b["max_cost"] is not None and cost + spec["cost"] > b["max_cost"] + 1e-9:                 # 350
                eligibility.append(dict(cls=icls, eligible=False, reason="BUDGET_COST")); declined.append(icls); reason = "budget"; break
            if b.get("max_latency_ms") and lat + spec["latency_ms"] > b["max_latency_ms"]:               # [0037]
                eligibility.append(dict(cls=icls, eligible=False, reason="BUDGET_LATENCY")); declined.append(icls); reason = "latency"; break
            eligibility.append(dict(cls=icls, eligible=True, reason="OK"))
            r = self.prov.invoke(icls, k, case)                              # 360
            cost += spec["cost"]; lat += spec["latency_ms"]
            tokens["tokens_in"] += r.tokens_in; tokens["tokens_out"] += r.tokens_out
            if r.adapter_id: adapters.add(r.adapter_id)
            if r.provider_region: regions.add(r.provider_region)
            step = dict(level=level + 1, cls=icls, outcome_code=r.outcome_code, verdict=r.verdict, confidence=round(r.confidence, 4), cost=spec["cost"],
                        tokens_in=r.tokens_in, tokens_out=r.tokens_out, elapsed_ms=r.elapsed_ms, reason=r.reason)
            envelope.append(dict(component="intelligence", cls=icls, provider=(r.adapter_id or "").split(":")[0] or icls, service=(r.adapter_id or icls),
                                 native_meter=("tokens" if icls in ("L", "F", "M") else "invocation"), native_quantity=dict(tokens_in=r.tokens_in, tokens_out=r.tokens_out) if icls in ("L", "F", "M") else dict(calls=1),
                                 contract_rate=None, direct_cost=None, allocated_cost=spec["cost"], currency=self.p.get("currency", "EUR"),
                                 quantity_source=("RESPONSE" if icls in ("L", "F", "M") else "DERIVED"), cost_evidence="ESTIMATED"))   # ESTIMATED until a bill reconciles it
            path.append(step)
            if r.outcome_code != "OK":                                       # policy-specified failure handling: no implicit escalation
                reason = f"invocation_{r.outcome_code.lower()}"; break
            conf, verdict = r.confidence, r.verdict
            if conf >= b["evidence"] and ceiling != "H": reason = "threshold"; break      # 370
            level += 1
            if ceiling == "H": continue
            if level > ceiling: reason = "ceiling"; break                     # 380
        if reason is None: reason = "human_terminated" if ceiling == "H" else "ceiling"
        ref = pol.get("shadow_reference")
        if ref and len(path) > 1 and path[0]["cls"] == ref and shadow is None:
            shadow = dict(cls=ref, verdict=path[0]["verdict"], confidence=path[0]["confidence"], outcome_code="OK")
        for s in path[:-1]:   # every lower class that ran before escalation is a shadow "below" the deciding class
            shadows.append(dict(role="shadow", position="below", cls=s["cls"], verdict=s["verdict"], confidence=s["confidence"], outcome_code=s["outcome_code"], cost=s["cost"]))
        # shadow ABOVE: the next eligible class after the one that decided; run and stored, never used. Off by default (a call per case);
        # enable per class (shadow_above: true) or globally with EQAL_SHADOW_ABOVE=1 on measurement runs. Needed for under-intelligence (UIR).
        if not observe_only and path and reason == "threshold" and (pol.get("shadow_above") or os.getenv("EQAL_SHADOW_ABOVE") == "1"):
            nxt = [c for c in pol["path"][pol["path"].index(path[-1]["cls"]) + 1:] if pol.get("validation", {}).get(c, "permitted") == "permitted"]
            if nxt:
                r2 = self.prov.invoke(nxt[0], k, case); sp2 = self.C[nxt[0]]
                shadows.append(dict(role="shadow", position="above", cls=nxt[0], verdict=r2.verdict, confidence=round(r2.confidence, 4), outcome_code=r2.outcome_code, cost=sp2["cost"]))
                envelope.append(dict(component="shadow", cls=nxt[0], provider=(r2.adapter_id or "").split(":")[0] or nxt[0], service=(r2.adapter_id or nxt[0]), native_meter="tokens",
                                     native_quantity=dict(tokens_in=r2.tokens_in, tokens_out=r2.tokens_out), contract_rate=None, direct_cost=None, allocated_cost=sp2["cost"],
                                     currency=self.p.get("currency", "EUR"), quantity_source="RESPONSE", cost_evidence="ESTIMATED"))
        acts = reason == "threshold" and eff in ("ACT", "ACT_NOTIFY")
        hr = pol["human_rule"]
        if acts:   # the path that did NOT run: a person. Modelled, never counted as a saving without an accounting basis.
            envelope.append(dict(component="human_alternative", cls="H", provider="tenant", service=hr["role"], native_meter="touches", native_quantity=dict(touches=hr["approvers"]),
                                 contract_rate=self.p["human_touch_cost"], direct_cost=None, allocated_cost=hr["approvers"] * self.p["human_touch_cost"], currency=self.p.get("currency", "EUR"),
                                 quantity_source="DERIVED", cost_evidence="COUNTERFACTUAL"))
        if acts: action, human = ("act" if eff == "ACT" else "act_notify"), None
        else:
            human = dict(role=hr["role"], approvers=hr["approvers"], when=hr["when"], reason=reason,
                         recommendation=(None if eff == "NONE" else verdict))
            action = "recommend" if eff != "NONE" else "enqueue"
        return dict(
            case_id=case.case_id, version=1, tenant_id=tenant_id,
            pack=f"{self.p['pack']}/{self.p['version']}", pack_lifecycle=self.p["lifecycle"],
            exception_class=k, classification=clog, conservatively_routed=conservative,
            input_refs=case.input_refs, evidence_required=pol["evidence_required"], evidence_hashes=case.evidence_hashes,
            harm_class=case.harm_class, reversible=case.reversible,
            eligibility=eligibility, path=path, declined=declined, shadow=shadow, shadows=shadows,
            capability_type=pol.get("capability_type", self.p.get("capability_type", "document_judgement")),
            task_fingerprint=f"{k}:{pol.get('capability_type', self.p.get('capability_type', 'document_judgement'))}",
            budget=dict(max_cost=b["max_cost"], evidence=b["evidence"], max_latency_ms=b.get("max_latency_ms"), consequence=cons),
            cost=round(cost, 4), latency_ms=lat, **tokens, adapter_ids=sorted(adapters), provider_regions=sorted(regions),
            confidence=conf, risk_score=score, lens_ceiling=lens, autonomy_policy=aut, autonomy_effective=eff,
            observe_only=observe_only, action=action, human=human, reason=reason, maturity="PENDING",
            cost_envelope=envelope,                                   # Decision Cost Envelope: components with native meters; human component appended at outcome
            evidence_label=(case.input_refs.get("provenance") or {}).get("evidence_label") or dict(models=("SIMULATED" if type(self.prov).__name__ == "SimulatedProvider" else "REAL"), cases="SYNTHETIC", outcomes="CONSTRUCTED"),
            record_hash=None)

def seal(rec: dict) -> dict:
    """Hash of the version's content, stored on the record so later versions can reference it."""
    body = json.dumps({k: v for k, v in rec.items() if k != "record_hash"}, sort_keys=True, default=str)
    rec["record_hash"] = hashlib.sha256(body.encode()).hexdigest()[:24]
    return rec
