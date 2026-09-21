"""Agreement test — is 'cheaper model more accurate' real on these cases?

Runs the SAME cases through two (or more) gateway models with the SAME per-class prompt, outside the
runtime (no policy, no escalation), and reports per class and per model: n, accuracy, 95% Wilson interval,
invalid-output rate, mean tokens and cost; then the agreement matrix (both right / A only / B only / both
wrong) and the reasons each model gave where they disagreed. Ground truth is the case label — synthetic
or constructed — and the report says so.

  export EQAL_GATEWAY_KEY=...
  python3 scripts/agreement_test.py --cases cases.jsonl --limit 200 --models mistral-small-latest,mistral-large-latest \
      --classes price_variance,bank_detail_change --price mistral-small-latest=0.15:0.60 --price mistral-large-latest=0.50:1.50
"""
import argparse, json, math, os, sys, time, collections, datetime
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app.adapters_ap import APDeterministic
from app.providers import GatewayProvider
from app.runtime import Case

def wilson(k, n, z=1.96):
    if n == 0: return (0.0, 0.0)
    p = k / n; d = 1 + z * z / n; c = p + z * z / (2 * n); a = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return ((c - a) / d, (c + a) / d)

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--cases", required=True); ap.add_argument("--limit", type=int, default=200)
    ap.add_argument("--models", default="mistral-small-latest,mistral-large-latest"); ap.add_argument("--classes", default="price_variance,bank_detail_change")
    ap.add_argument("--price", action="append", default=[], help="model=in:out USD per 1M"); ap.add_argument("--out", default="reports")
    a = ap.parse_args(); models = a.models.split(","); classes = set(a.classes.split(","))
    price = {}
    for p in a.price: m, io = p.split("="); i, o = io.split(":"); price[m] = (float(i), float(o))
    os.environ.setdefault("EQAL_GATEWAY_URL", "https://api.mistral.ai")
    ad = APDeterministic(); rows = []
    # select cases: only the classes under test, in file order
    for line in open(a.cases):
        c = json.loads(line)
        if c.get("true_class") in classes: rows.append(c)
        if len(rows) >= a.limit: break
    print(f"{len(rows)} cases across {sorted(classes)}; models {models}", file=sys.stderr)
    results = []   # (case_id, cls, truth, {model: (verdict, conf, code, reason, tin, tout, ms)})
    t0 = time.time()
    for idx, c in enumerate(rows):
        body = ad.build(c); case = Case(body["case_id"], body["input_refs"], body["signals"], body["flags"])
        per = {}
        for m in models:
            os.environ["EQAL_MODEL_L"] = m; prov = GatewayProvider()   # same prompt for every model: PROMPTS[cls]
            inv = prov.invoke("L", c["true_class"], case)
            per[m] = dict(verdict=inv.verdict, conf=inv.confidence, code=inv.outcome_code, reason=inv.reason, tin=inv.tokens_in, tout=inv.tokens_out, ms=inv.elapsed_ms)
        results.append((c["case_id"], c["true_class"], c["truth"], per))
        if (idx + 1) % 25 == 0: print(f"{idx+1}/{len(rows)}, {time.time()-t0:.0f}s", file=sys.stderr)
    # ---- report
    L = [f"# Agreement test — {datetime.date.today()}", f"cases: {len(rows)} from {a.cases} · models: {', '.join(models)} · prompt: identical per class (PROMPTS in app/providers.py)",
         "ground truth: the case label (synthetic or constructed) — this measures agreement with the generator's label, not with the world", ""]
    L += ["| class | model | n | valid | invalid | accuracy | 95% CI | mean tokens in/out | mean cost/call | mean latency |", "|---|---|---|---|---|---|---|---|---|---|"]
    for cls in sorted(classes):
        for m in models:
            sel = [r for r in results if r[1] == cls]; valid = [r for r in sel if r[3][m]["code"] == "OK"]
            k = sum(1 for r in valid if r[3][m]["verdict"] == r[2]); n = len(valid); lo, hi = wilson(k, n)
            tin = sum(r[3][m]["tin"] for r in valid) / max(1, n); tout = sum(r[3][m]["tout"] for r in valid) / max(1, n); ms = sum(r[3][m]["ms"] for r in valid) / max(1, n)
            pin, pout = price.get(m, (0, 0)); cost = (tin * pin + tout * pout) / 1e6
            L.append(f"| {cls} | {m} | {len(sel)} | {n} | {len(sel)-n} | {k/n:.1%} | {lo:.1%}–{hi:.1%} | {tin:.0f}/{tout:.0f} | ${cost:.5f} | {ms:.0f} ms |" if n else f"| {cls} | {m} | {len(sel)} | 0 | {len(sel)} | — | — | — | — | — |")
    if len(models) >= 2:
        A, B = models[0], models[1]
        L += ["", f"## Agreement matrix: {A} (A) vs {B} (B)", "| class | both right | A only | B only | both wrong | invalid either |", "|---|---|---|---|---|---|"]
        for cls in sorted(classes):
            cnt = collections.Counter()
            for r in [r for r in results if r[1] == cls]:
                pa, pb = r[3][A], r[3][B]
                if pa["code"] != "OK" or pb["code"] != "OK": cnt["invalid"] += 1; continue
                ra, rb = pa["verdict"] == r[2], pb["verdict"] == r[2]
                cnt["both right" if ra and rb else "A only" if ra else "B only" if rb else "both wrong"] += 1
            L.append(f"| {cls} | {cnt['both right']} | {cnt['A only']} | {cnt['B only']} | {cnt['both wrong']} | {cnt['invalid']} |")
        L += ["", "## Disagreements (first 12): what each model said and why"]
        shown = 0
        for r in results:
            pa, pb = r[3][A], r[3][B]
            if pa["code"] != "OK" or pb["code"] != "OK" or pa["verdict"] == pb["verdict"]: continue
            L.append(f"- **{r[1]}** truth={'legit' if r[2] else 'not legit'} · A: {'approve' if pa['verdict'] else 'reject'} @{pa['conf']:.2f} — {pa['reason'][:110]} · B: {'approve' if pb['verdict'] else 'reject'} @{pb['conf']:.2f} — {pb['reason'][:110]}")
            shown += 1
            if shown >= 12: break
        L += ["", "## Calibration by stated confidence bucket", "| class | model | bucket | n | accuracy |", "|---|---|---|---|---|"]
        for cls in sorted(classes):
            for m in models:
                b = collections.defaultdict(lambda: [0, 0])
                for r in results:
                    if r[1] != cls or r[3][m]["code"] != "OK": continue
                    key = f"{int(r[3][m]['conf']*20)/20:.2f}"; b[key][0] += 1; b[key][1] += (r[3][m]["verdict"] == r[2])
                for key, (n, k) in sorted(b.items()): L.append(f"| {cls} | {m} | {key} | {n} | {k/n:.0%} |")
    L += ["", "## Reading rule", "Overlapping intervals mean parity on these cases, not 'cheaper wins'. A difference in invalid-output rate is a contract problem, not a capability one. "
          "Where the models disagree and the label sides with one of them, read the reasons: on constructed labels the 'winner' may simply agree with the generator."]
    os.makedirs(a.out, exist_ok=True); path = os.path.join(a.out, f"agreement_{datetime.datetime.now():%Y%m%d_%H%M}.md")
    open(path, "w").write("\n".join(L)); print("\n".join(L)); print(f"\n-> {path}")

if __name__ == "__main__": main()
