"""Evidence Library — build procurement cases from public AWARD datasets (not AP ledgers).

Supported out of the box (columns auto-detected; override with --col-* flags):
  USAspending transactions/awards CSV (US, public domain)      -> --jurisdiction US
  GeBIZ procurement awards CSV, data.gov.sg (SG, Open Data Licence) -> --jurisdiction SG
  TED award notices export (EU, reuse with attribution)        -> --jurisdiction EU
  UK Contracts Finder OCDS/CSV export (OGL v3)                 -> --jurisdiction UK

Exception types are REAL where the dataset carries the field (bid_count==1 -> single_bid; modification/amount change
-> contract_amendment; debarment/status fields -> award_eligibility; procedure=emergency/negotiated-without-notice ->
emergency_procurement) and CONSTRUCTED otherwise (price_vs_estimate when no estimate column exists). Outcomes are
CONSTRUCTED. Every case carries its provenance code, e.g. R/R.C/C, and the dataset registration.

  python3 build_cases_awards.py --csv ~/Downloads/usaspending_fy2026_q3.csv --jurisdiction US --n 2000 --seed 11 \
      --source "USAspending.gov transaction download, FY2026 Q3" --licence "US public domain" --out cases_us_awards.jsonl
"""
import argparse, csv, json, hashlib, random, re, sys, collections
from pathlib import Path

CANDS = {
 "buyer":    ["awarding_agency_name", "agency", "buyer", "contracting_authority", "ca_name", "buyer name", "authority", "awarding agency"],
 "supplier": ["recipient_name", "supplier_name", "supplier", "awardee", "win_name", "winner", "vendor", "contractor"],
 "amount":   ["federal_action_obligation", "total_obligated_amount", "awarded_amt", "awarded amount", "award_value", "value_euro_fin_1", "award value", "contract value", "amount", "value"],
 "estimate": ["base_and_all_options_value", "estimated_value", "value_euro", "estimated value", "budget", "estimated_amt"],
 "date":     ["action_date", "award_date", "date_of_dispatch", "award date", "awarded_date", "published date", "date"],
 "desc":     ["award_description", "tender_description", "description", "title", "object", "tender_no"],
 "bids":     ["number_of_offers_received", "bids", "number_of_bids", "offers", "nb_tenders"],
 "procedure":["extent_competed", "procedure_type", "procedure", "top_type", "type_of_procedure", "award_procedure"],
 "modnum":   ["modification_number", "mod_number", "amendment", "modification"],
 "status":   ["award_status", "status", "tender_status", "supplier_status"],
 "cpv":      ["naics_code", "cpv", "product_or_service_code", "cpv_code"],
}
EMERGENCY_WORDS = ["emergency", "urgent", "negotiated without", "without prior publication", "sole source", "only one source", "unusual and compelling"]

def pick(cols, key, override=None):
    if override: return override
    low = {c.lower().strip(): c for c in cols}
    for cand in CANDS[key]:
        for lc, orig in low.items():
            if lc == cand or cand in lc: return orig
    return None

def money(x):
    s = re.sub(r"[^\d.\-]", "", str(x or ""))
    try: return round(float(s), 2)
    except ValueError: return None

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True, nargs="+"); ap.add_argument("--jurisdiction", required=True, choices=["UK", "US", "SG", "EU"])
    ap.add_argument("--n", type=int, default=2000); ap.add_argument("--seed", type=int, default=11); ap.add_argument("--out", default="cases_awards.jsonl")
    ap.add_argument("--source", required=True); ap.add_argument("--licence", required=True); ap.add_argument("--dataset-version", default="")
    ap.add_argument("--truth-mode", default="rule", choices=["rule", "none"], help="rule: outcome derived by a stated rule from the evidence; none: outcome NULL (routing, cost, agreement only). Random outcomes are not allowed.")
    ap.add_argument("--amend-limit-pct", type=float, default=25.0); ap.add_argument("--var-tolerance-pct", type=float, default=10.0)
    for k in CANDS: ap.add_argument(f"--col-{k}")
    a = ap.parse_args(); rng = random.Random(a.seed)
    rows = []; detected = {}
    for path in a.csv:
        with open(path, newline="", encoding="utf-8-sig", errors="replace") as fh:
            rd = csv.DictReader(fh); cols = rd.fieldnames or []
            m = {k: pick(cols, k, getattr(a, f"col_{k}")) for k in CANDS}
            if not (m["supplier"] and m["amount"]): sys.exit(f"{path}: need supplier and amount columns; found {cols[:30]}; use --col-supplier/--col-amount")
            detected[Path(path).name] = {k: v for k, v in m.items() if v}
            for r in rd:
                amt = money(r.get(m["amount"]))
                if amt is None or amt <= 0 or not (r.get(m["supplier"]) or "").strip(): continue
                rows.append(dict(buyer=(r.get(m["buyer"]) or "unknown buyer").strip() if m["buyer"] else "unknown buyer", supplier=r[m["supplier"]].strip(), amount=amt,
                                 estimate=money(r.get(m["estimate"])) if m["estimate"] else None, date=(r.get(m["date"]) or "").strip() if m["date"] else "",
                                 desc=(r.get(m["desc"]) or "").strip()[:160] if m["desc"] else "", bids=(money(r.get(m["bids"])) if m["bids"] else None),
                                 procedure=(r.get(m["procedure"]) or "").strip() if m["procedure"] else "", modnum=(r.get(m["modnum"]) or "").strip() if m["modnum"] else "",
                                 status=(r.get(m["status"]) or "").strip() if m["status"] else "", cpv=(r.get(m["cpv"]) or "").strip() if m["cpv"] else "", file=Path(path).name))
    if not rows: sys.exit("no usable awards")
    by_buyer_total = collections.defaultdict(float); by_pair = collections.defaultdict(float)
    for r in rows: by_buyer_total[r["buyer"]] += r["amount"]; by_pair[(r["buyer"], r["supplier"])] += r["amount"]
    real_fields = {k for k in ("estimate", "bids", "procedure", "modnum", "status") if any(r[k] not in (None, "") for r in rows)}
    print(f"{len(rows)} real awards, {len({r['supplier'] for r in rows})} suppliers, {len(by_buyer_total)} buyers; real exception fields: {sorted(real_fields) or 'none'}", file=sys.stderr)
    out = open(a.out, "w"); n = 0; counts = collections.Counter()
    registration = dict(source=a.source, licence=a.licence, dataset_version=a.dataset_version, jurisdiction=a.jurisdiction, files=sorted(detected), columns=detected, seed=a.seed)
    while n < a.n:
        r = rng.choice(rows); share = by_pair[(r["buyer"], r["supplier"])] / by_buyer_total[r["buyer"]] if by_buyer_total[r["buyer"]] else 0
        exc_real = False; legit = True; cls = None; note = r["desc"]; truth_rule = None
        proc_low = r["procedure"].lower()
        LAWFUL_SOLE = ["not available for competition", "follow on", "follow-on", "only one source", "sole source", "simplified acquisition", "set-aside", "set aside"]
        if any(w in proc_low or w in note.lower() for w in EMERGENCY_WORDS):
            cls, exc_real = "emergency_procurement", True; legit = None; truth_rule = "none: emergency legitimacy needs the file; always a person"
        elif r["bids"] == 1:
            cls, exc_real = "single_bid", True
            if "full and open" in proc_low or any(w in proc_low for w in LAWFUL_SOLE): legit, truth_rule = True, "rule: one offer under a lawful procedure code (full and open / stated non-competitive basis)"
            elif "not competed" in proc_low or "not available" not in proc_low and proc_low == "": legit, truth_rule = False, "rule: one offer with 'not competed' or no procedure basis"
            else: legit, truth_rule = None, "none: procedure code does not state a basis"
        elif r["modnum"] and r["modnum"] not in ("0", "00", "P00000"):
            cls, exc_real = "contract_amendment", True
            if r["estimate"] and r["estimate"] > 0: pct = abs(r["amount"]) / r["estimate"] * 100; legit, truth_rule = (pct <= a.amend_limit_pct), f"rule: modification obligation {pct:.1f}% of base-and-all-options vs limit {a.amend_limit_pct}%"
            else: legit, truth_rule = None, "none: no base value to compare"
        elif r["status"] and re.search(r"debar|exclud|suspend", r["status"], re.I):
            cls, exc_real = "award_eligibility", True; legit, truth_rule = False, "rule: supplier status excluded/debarred/suspended"
        else:
            u = rng.random()
            if u < 0.62: cls = "award_eligibility"; legit, truth_rule = True, "rule: registered, no exclusion, no flags"
            elif u < 0.90:
                cls = "price_vs_estimate"
                if r["estimate"] and r["estimate"] > 0: exc_real = True; var = (r["amount"] - r["estimate"]) / r["estimate"]; legit, truth_rule = (abs(var) * 100 <= a.var_tolerance_pct), f"rule: |variance| {abs(var)*100:.1f}% vs tolerance {a.var_tolerance_pct}%"
                else: var = rng.choice([0.03, 0.08, 0.18, 0.35, -0.12]); legit, truth_rule = (abs(var) * 100 <= a.var_tolerance_pct), f"rule (constructed variance): |variance| vs tolerance {a.var_tolerance_pct}%"
                note = note or ("Price reflects indexation clause in the framework." if legit else "")
            else: cls = "supplier_concentration"; legit, truth_rule = (share <= 0.4), "rule: supplier share of buyer spend <= 40%"
        if a.truth_mode == "none": legit, truth_rule = None, "none: outcomes withheld by --truth-mode none"
        est = r["estimate"] if (r["estimate"] and r["estimate"] > 0) else round(r["amount"] / (1 + (0 if cls != "price_vs_estimate" else rng.choice([0.03, 0.08, 0.18, 0.35, -0.12]))), 2)
        ref = f"{a.jurisdiction}{a.seed}-{n:05d}"
        docs = dict(award=dict(award_ref=ref, buyer=r["buyer"], supplier=r["supplier"], awarded_value=r["amount"], estimated_value=est, variance_pct=round((r["amount"] - est) / est * 100, 2) if est else None,
                               date=r["date"], description=r["desc"], procedure_type=r["procedure"], bid_count=r["bids"], modification=r["modnum"], supplier_status=r["status"], category=r["cpv"],
                               supplier_share_of_buyer_spend=round(share, 4), justification_text=note, currency={"UK": "GBP", "US": "USD", "SG": "SGD", "EU": "EUR"}[a.jurisdiction]))
        code = f"R/{'R' if exc_real else 'C'}/{'C' if legit is not None else '-'}"
        case = dict(case_id=f"H-{hashlib.sha256(ref.encode()).hexdigest()[:10]}", true_class=cls, truth=legit, resolution=("UPHELD" if legit else "CHALLENGED" if legit is not None else "UNKNOWN"), docs=docs,
                    provenance=dict(dataset=registration, evidence_code=code, exception_from_real_field=exc_real, truth_rule=truth_rule,
                                    evidence_label=dict(inputs="REAL", exceptions=("REAL" if exc_real else "CONSTRUCTED"), outcomes=("CONSTRUCTED (rule-derived)" if legit is not None else "NONE"))))
        out.write(json.dumps(case) + "\n"); n += 1; counts[(cls, ("real" if exc_real else "constructed") + ("" if legit is not None else " / outcome none"))] += 1
    print(f"wrote {n} cases -> {a.out}", file=sys.stderr)
    for (c, k), v in sorted(counts.items()): print(f"  {c:24s} {k:11s} {v}", file=sys.stderr)
    print(f"Attribution: {a.source} - {a.licence}", file=sys.stderr)

if __name__ == "__main__": main()
