"""Level 1 measurement (plan steps 3.2-3.3): real intelligence on realistic synthetic cases.

  python3 scripts/gen_cases.py --n 2000 --seed 11 --out cases.jsonl
  EQAL_URL=http://localhost:8000 EQAL_API_KEY=demo-key python3 scripts/measure.py --cases cases.jsonl [--limit 200]

For each case: adapter builds signals + evidence pack -> POST /v1/decide -> POST /v1/outcomes with the
synthetic truth. Then a calibration table per intelligence class from the ledger: accuracy, confidence
calibration by bucket, tokens, measured cost (from EQAL_PRICE_* USD per 1M tokens), latency, failure codes.
Writes calibration.json and calibration.md. These replace the assumed constants in packs and site.
"""
import argparse, json, os, sys, time, urllib.request, urllib.error, statistics as st
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app.adapters_ap import APDeterministic
URL, KEY = os.getenv("EQAL_URL", "http://localhost:8000"), os.getenv("EQAL_API_KEY", "demo-key")
PRICE = {c: (float(os.getenv(f"EQAL_PRICE_{c}_IN", "0")), float(os.getenv(f"EQAL_PRICE_{c}_OUT", "0"))) for c in ("L", "F", "M")}
def call(m, path, body=None):
    req = urllib.request.Request(URL + path, method=m, data=json.dumps(body).encode() if body is not None else None, headers={"Content-Type": "application/json", "X-API-Key": KEY})
    with urllib.request.urlopen(req, timeout=120) as r: return json.load(r)

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--cases", default="cases.jsonl"); ap.add_argument("--limit", type=int, default=0); ap.add_argument("--observe-only", action="store_true")
    a = ap.parse_args(); ad = APDeterministic(); n = 0; t0 = time.time()
    for line in open(a.cases):
        if a.limit and n >= a.limit: break
        case = json.loads(line); body = ad.build(case); body["observe_only"] = a.observe_only
        try: d = call("POST", "/v1/decide", body)
        except urllib.error.HTTPError as ex:
            if ex.code == 409: continue
            raise
        truth = case["truth"]; rec = (d.get("path") or [{}])[-1].get("verdict")
        human = None
        if d["human"]:
            human = dict(touches=d["human"]["approvers"], decision="approve" if truth else "reject", override=(rec is not None and rec != truth))
            final = truth
        else: final = rec
        ok = (final == truth) if final is not None else None
        value = ("impersonation_blocked" if case["resolution"] == "FRAUD_CONFIRMED" and not final else "fraud_paid" if case["resolution"] == "FRAUD_CONFIRMED" else "posted_ok" if (ok and truth) else "rejected_ok" if ok else "wrong_post" if final else "wrong_reject")
        call("POST", f"/v1/outcomes/{d['case_id']}", dict(kind="observed", value=value, correct=ok, truth=truth, realised_effect=(case["docs"]["invoice"]["amount"] if value == "impersonation_blocked" else 0.0), human=human, detail=dict(true_class=case["true_class"], resolution=case["resolution"])))
        n += 1
        if n % 50 == 0: print(f"{n} cases, {time.time()-t0:.0f}s", file=sys.stderr)
    print(f"decided {n} cases in {time.time()-t0:.0f}s", file=sys.stderr)
    # ---- calibration from the ledger
    recs = call("GET", "/v1/ledger?limit=20000")
    cal = {}
    for r in recs:
        truth = (r.get("outcome") or {}).get("truth")
        for s in r["path"]:
            c = cal.setdefault(s["cls"], dict(n=0, ok=0, fail=0, tin=[], tout=[], ms=[], buckets={}))
            if s["outcome_code"] != "OK": c["fail"] += 1; c.setdefault("fail_reasons", {}).setdefault(f"{s['outcome_code']}: {s.get('reason','')[:80]}", 0); c["fail_reasons"][f"{s['outcome_code']}: {s.get('reason','')[:80]}"] += 1; continue
            c["n"] += 1; c["tin"].append(s.get("tokens_in", 0)); c["tout"].append(s.get("tokens_out", 0)); c["ms"].append(s.get("elapsed_ms", 0))
            if truth is not None:
                right = s["verdict"] == truth; c["ok"] += right
                b = c["buckets"].setdefault(f"{int(s['confidence']*20)/20:.2f}", [0, 0]); b[0] += 1; b[1] += right
    out = {}
    for cls, c in cal.items():
        pin, pout = PRICE.get(cls, (0, 0)); mtin = st.mean(c["tin"]) if c["tin"] else 0; mtout = st.mean(c["tout"]) if c["tout"] else 0
        out[cls] = dict(calls=c["n"], failures=c["fail"], accuracy=(c["ok"] / c["n"]) if c["n"] else None, mean_tokens_in=round(mtin), mean_tokens_out=round(mtout),
                        measured_cost_usd=round((mtin * pin + mtout * pout) / 1e6, 6), mean_latency_ms=round(st.mean(c["ms"])) if c["ms"] else None,
                        calibration={k: dict(n=v[0], accuracy=round(v[1] / v[0], 3)) for k, v in sorted(c["buckets"].items())})
    json.dump(out, open("calibration.json", "w"), indent=1)
    md = ["| class | calls | failures | accuracy | tokens in/out | measured cost per call | latency |", "|---|---|---|---|---|---|---|"]
    NOTE = {"D": " (rules; 0.50 = not decidable by rules)", "S": " (STUB until a verification service is connected)"}
    for cls, c in out.items(): md.append(f"| {cls}{NOTE.get(cls, '')} | {c['calls']} | {c['failures']} | {'' if c['accuracy'] is None else format(c['accuracy'], '.1%')} | {c['mean_tokens_in']}/{c['mean_tokens_out']} | ${c['measured_cost_usd']:.5f} | {c['mean_latency_ms']} ms |")
    for cls, c in cal.items():
        if c.get("fail_reasons"): md.append(f"\nFailures for {cls}: " + "; ".join(f"{k} (x{v})" for k, v in c["fail_reasons"].items()))
    md.append("\nCalibration (stated confidence bucket -> observed accuracy):")
    for cls, c in out.items(): md.append(f"- {cls}: " + ", ".join(f"{k}: {v['accuracy']:.0%} (n={v['n']})" for k, v in c["calibration"].items()))
    open("calibration.md", "w").write("\n".join(md)); print("\n".join(md))
    print(json.dumps({k: v for k, v in call("GET", "/v1/pnl").items() if k not in ("by_class", "sample")}, indent=1))

if __name__ == "__main__": main()
