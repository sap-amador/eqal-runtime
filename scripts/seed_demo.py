"""Seed a tenant with N synthetic AP cases through the runtime and append observed outcomes.
Reproduces the frozen reference's synthetic world (02-reference/simulate.py make_case).
  EQAL_URL=http://localhost:8000 EQAL_API_KEY=demo-key python3 scripts/seed_demo.py --n 2000 --seed 11
"""
import argparse, json, os, random, urllib.request
URL, KEY = os.getenv("EQAL_URL", "http://localhost:8000"), os.getenv("EQAL_API_KEY", "demo-key")
def call(m, path, body=None):
    req = urllib.request.Request(URL + path, method=m, data=json.dumps(body).encode() if body is not None else None, headers={"Content-Type": "application/json", "X-API-Key": KEY})
    with urllib.request.urlopen(req, timeout=60) as r: return json.load(r)

def make_case(i, rng):
    r = rng.random()
    if r < 0.80:   true, variance, legit = "clean_match", 0.0, True
    elif r < 0.98: true, variance, legit = "price_variance", round(rng.uniform(250, 4000) if rng.random() < 0.3 else rng.uniform(5, 250), 2), rng.random() < 0.85
    else:          true, variance, legit = "bank_detail_change", 0.0, rng.random() < 0.82
    hidden = rng.random() < 0.03
    if hidden and rng.random() < 0.10 and true == "clean_match": true, legit = "bank_detail_change", rng.random() < 0.6
    sig = dict(payee_bank_changed=(true == "bank_detail_change" and not hidden),
               vendor_contact_anomaly=(true == "bank_detail_change" and not legit and rng.random() < 0.8) or rng.random() < 0.04,
               first_invoice=rng.random() < 0.05, just_below_threshold=rng.random() < 0.03,
               po_match_exact=(true == "clean_match"), master_data_complete=not hidden, _truth=legit, _true_class=true)
    if true == "bank_detail_change" and not legit and rng.random() < 0.3: sig["vendor_contact_anomaly"] = True
    return dict(case_id=f"51004{i:05d}", input_refs=dict(amount=round(rng.lognormvariate(7, 1), 2), variance=variance),
                signals=sig, flags=dict(variance_lte=variance <= 250), harm_class="financial", reversible=(true != "bank_detail_change")), true, legit

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--n", type=int, default=2000); ap.add_argument("--seed", type=int, default=11); ap.add_argument("--observe-only", action="store_true")
    a = ap.parse_args(); rng = random.Random(a.seed)
    for i in range(a.n):
        body, true, legit = make_case(i, rng); body["observe_only"] = a.observe_only
        d = call("POST", "/v1/decide", body)
        human = None
        if d["human"]:
            hv = legit if rng.random() < 0.995 else (not legit)
            rec = d["human"]["recommendation"]
            human = dict(touches=d["human"]["approvers"], decision="approve" if hv else "reject", override=(rec is not None and hv != rec), approver_ids=[f"{d['human']['role']}-{k}" for k in range(d["human"]["approvers"])])
            final = hv
        else:
            final = d["path"][-1]["verdict"] if d["path"] else None
        ok = final == legit
        if true == "bank_detail_change": value = "impersonation_blocked" if (not legit and not final) else ("change_applied" if (legit and final) else ("fraud_paid" if final else "legit_change_rejected"))
        else: value = "posted_ok" if (ok and final) else ("rejected_ok" if ok else ("wrong_post" if final else "wrong_reject"))
        call("POST", f"/v1/outcomes/{d['case_id']}", dict(kind="observed", value=value, correct=ok, truth=legit, realised_effect=(body["input_refs"]["amount"] if value == "impersonation_blocked" else 0.0), human=human))
        if i % 500 == 499: print(i + 1, "cases")
    s = call("GET", "/v1/pnl")
    print(json.dumps({k: v for k, v in s.items() if k not in ("by_class", "sample")}, indent=1))

if __name__ == "__main__": main()
