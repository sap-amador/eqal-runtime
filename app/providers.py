"""Providers. simulated: same behaviour model as the frozen v0.3 reference, so a run of
the service on synthetic cases reproduces the reference numbers. gateway: D and S are
attached by the adapter (rule results, verification results, classification candidates);
L, F, M go to an OpenAI-compatible endpoint (LiteLLM / OpenRouter / Azure), one alias
per class, EU region only. Only the evidence fields in case.input_refs are sent."""
import os, json, random, time, urllib.request, urllib.error
from .runtime import Invocation, Case

class SimulatedProvider:
    """Ground truth arrives in case.signals['_truth'] and ['_true_class'] from the seed
    script; never stored (main.py strips underscore keys)."""
    def __init__(self, seed=None): self.rng = random.Random(seed)
    @staticmethod
    def behaviour(icls, cls, case):
        v = case.input_refs.get("variance", 0.0)
        if cls == "clean_match":     return (0.999, 0.998, 0.002) if icls == "D" else (0.998, 0.998, 0.002)
        if cls == "price_variance":
            if icls == "L":          return (0.99, 0.985, 0.012) if v <= 250 else (0.93, 0.955, 0.03)
            return (0.992, 0.992, 0.006)
        return (0.97, 0.97, 0.02) if icls == "S" else (0.95, 0.94, 0.03)
    def invoke(self, icls, cls, case):
        acc, mu, sd = self.behaviour(icls, cls, case); r = self.rng
        truth = case.signals.get("_truth", True)
        correct = r.random() < acc
        conf = min(0.9999, max(0.5, r.gauss(mu, sd)))
        if not correct: conf = min(conf, r.uniform(0.85, 0.99))
        return Invocation(verdict=truth if correct else (not truth), confidence=round(conf, 4), adapter_id=f"sim-{icls}", provider_region="eu")
    def classify(self, icls, case):
        s, r = case.signals, self.rng
        if icls == "D":
            if s.get("payee_bank_changed"): return ["bank_detail_change"], 1.0
            cands = ["clean_match"] if s.get("po_match_exact") else ["price_variance"]
            if not s.get("master_data_complete", True): cands.append("bank_detail_change")
            return cands, (1.0 if len(cands) == 1 else 0.5)
        acc, mu, sd = (0.97, 0.97, 0.02) if icls == "S" else (0.95, 0.955, 0.03)
        true = s.get("_true_class", "clean_match")
        right = r.random() < acc
        guess = true if right else r.choice([c for c in ("clean_match", "price_variance") if c != true])
        return [guess], min(0.9999, max(0.5, r.gauss(mu, sd)))

PROMPTS = {
 "clean_match": "You are an accounts-payable reviewer. The rules already found a three-way match within tolerance. Confirm the invoice may be posted, or flag anything in the documents that contradicts that.",
 "price_variance": "You are an accounts-payable reviewer. The invoice differs from the purchase order in price or lines. Using the PO, the contracted price list, the goods receipts and any note on the invoice, decide whether the variance is legitimate (contract clause, agreed surcharge, rounding) or not (wrong price, unagreed increase, extra items).",
 "bank_detail_change": "You are a treasury reviewer. A vendor has requested a change of bank details. Using the request, the vendor's history and the contact on file, assess whether the request appears genuine or shows signs of payment-diversion fraud (urgency, sender mismatch, letterhead mismatch, country change, reply-only instructions). You only recommend; a person decides.",
 "_default": "You review a business-process exception and decide whether it is legitimate."}
PROMPT = """{task}
Exception class: {cls}
Evidence (the only information available; do not assume anything beyond it):
{evidence}
Answer with a single JSON object and nothing else:
{{"approve": true or false, "confidence": <0.50 to 0.99, your calibrated probability that your answer is right>, "reason": "<one sentence>"}}"""

class GatewayProvider:
    def __init__(self):
        self.base = os.environ["EQAL_GATEWAY_URL"].rstrip("/"); self.key = os.environ["EQAL_GATEWAY_KEY"]
        self.models = {c: os.getenv(f"EQAL_MODEL_{c}", c.lower()) for c in ("L", "F", "M")}
        self.price = {c: (float(os.getenv(f"EQAL_PRICE_{c}_IN", "0")), float(os.getenv(f"EQAL_PRICE_{c}_OUT", "0"))) for c in ("L", "F", "M")}   # USD per 1M tokens
        self.region = os.getenv("EQAL_PROVIDER_REGION", "eu")
    def invoke(self, icls, cls, case):
        s = case.signals
        if icls == "D": return Invocation(verdict=bool(s.get("rule_pass", True)), confidence=float(s.get("rule_confidence", 0.998)), adapter_id=s.get("adapter_id", "adapter-D"))
        if icls == "S": return Invocation(verdict=bool(s.get("verified", False)), confidence=float(s.get("verify_confidence", 0.97)), adapter_id=s.get("adapter_id", "adapter-S"))
        prompt = PROMPT.format(task=PROMPTS.get(cls, PROMPTS["_default"]), cls=cls, evidence=json.dumps(case.input_refs, indent=1))
        body = {"model": self.models[icls], "temperature": 0, "response_format": {"type": "json_object"},
                "messages": [{"role": "system", "content": "Answer with one JSON object only."}, {"role": "user", "content": prompt}]}
        req = urllib.request.Request(f"{self.base}/v1/chat/completions", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.key}"})
        t0 = time.time(); last = None
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=60) as r: out = json.load(r)
                txt = out["choices"][0]["message"]["content"].strip().strip("`")
                if txt.startswith("json"): txt = txt[4:]
                j = json.loads(txt); u = out.get("usage", {})
                conf = min(0.9999, max(0.5, float(j["confidence"])))
                return Invocation(verdict=bool(j["approve"]), confidence=conf, tokens_in=u.get("prompt_tokens", 0), tokens_out=u.get("completion_tokens", 0),
                                  adapter_id=f"gw-{self.models[icls]}:self-report-v1", provider_region=self.region, elapsed_ms=int((time.time() - t0) * 1000), reason=str(j.get("reason", ""))[:200])
            except urllib.error.HTTPError as ex:
                detail = ""
                try: detail = ex.read().decode()[:200]
                except Exception: pass
                last = f"HTTP {ex.code} {detail}"
                if ex.code in (429, 500, 502, 503, 504): time.sleep(1.5 * (attempt + 1)); continue
                return Invocation(verdict=None, confidence=0.0, outcome_code="ERROR", elapsed_ms=int((time.time() - t0) * 1000), reason=last)
            except (TimeoutError, urllib.error.URLError) as ex:
                last = f"{type(ex).__name__}: {ex}"[:200]; time.sleep(1.5 * (attempt + 1)); continue
            except (KeyError, ValueError, json.JSONDecodeError) as ex:
                return Invocation(verdict=None, confidence=0.0, outcome_code="MALFORMED", elapsed_ms=int((time.time() - t0) * 1000), reason=f"{type(ex).__name__}: {ex}"[:200])
        return Invocation(verdict=None, confidence=0.0, outcome_code="TIMEOUT", elapsed_ms=int((time.time() - t0) * 1000), reason=str(last)[:200])
    def classify(self, icls, case):
        s = case.signals
        if icls == "D": return list(s.get("rule_candidates", ["clean_match"])), float(s.get("rule_class_confidence", 1.0))
        return list(s.get("classifier_candidates", s.get("rule_candidates", ["clean_match"]))), float(s.get("classifier_confidence", 0.0))

def get_provider(name: str):
    return {"simulated": SimulatedProvider, "gateway": GatewayProvider}[name]()
