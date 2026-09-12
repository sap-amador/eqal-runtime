"""Providers. simulated: same behaviour model as the frozen v0.3 reference, so a run of
the service on synthetic cases reproduces the reference numbers. gateway: D and S are
attached by the adapter (rule results, verification results, classification candidates);
L, F, M go to an OpenAI-compatible endpoint (LiteLLM / OpenRouter / Azure), one alias
per class, EU region only. Only the evidence fields in case.input_refs are sent."""
import os, json, random, urllib.request
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

PROMPT = """You review a business-process exception. Decide whether it is legitimate.
Exception class: {cls}
Evidence (the only fields available): {evidence}
Answer with JSON only: {{"approve": true|false, "confidence": 0.0-1.0, "reason": "<one sentence>"}}"""

class GatewayProvider:
    def __init__(self):
        self.base = os.environ["EQAL_GATEWAY_URL"].rstrip("/"); self.key = os.environ["EQAL_GATEWAY_KEY"]
        self.models = {c: os.getenv(f"EQAL_MODEL_{c}", c.lower()) for c in ("L", "F", "M")}
        self.region = os.getenv("EQAL_PROVIDER_REGION", "eu")
    def invoke(self, icls, cls, case):
        s = case.signals
        if icls == "D": return Invocation(verdict=bool(s.get("rule_pass", True)), confidence=float(s.get("rule_confidence", 0.998)), adapter_id=s.get("adapter_id", "adapter-D"))
        if icls == "S": return Invocation(verdict=bool(s.get("verified", False)), confidence=float(s.get("verify_confidence", 0.97)), adapter_id=s.get("adapter_id", "adapter-S"))
        body = {"model": self.models[icls], "temperature": 0, "messages": [{"role": "user", "content": PROMPT.format(cls=cls, evidence=json.dumps(case.input_refs))}]}
        req = urllib.request.Request(f"{self.base}/v1/chat/completions", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.key}"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r: out = json.load(r)
            j = json.loads(out["choices"][0]["message"]["content"].strip().strip("`").removeprefix("json"))
            u = out.get("usage", {})
            return Invocation(verdict=bool(j["approve"]), confidence=float(j["confidence"]), tokens_in=u.get("prompt_tokens", 0), tokens_out=u.get("completion_tokens", 0), adapter_id=f"gw-{self.models[icls]}", provider_region=self.region)
        except TimeoutError: return Invocation(verdict=None, confidence=0.0, outcome_code="TIMEOUT")
        except (KeyError, ValueError, json.JSONDecodeError): return Invocation(verdict=None, confidence=0.0, outcome_code="MALFORMED")
        except Exception: return Invocation(verdict=None, confidence=0.0, outcome_code="ERROR")
    def classify(self, icls, case):
        s = case.signals
        if icls == "D": return list(s.get("rule_candidates", ["clean_match"])), float(s.get("rule_class_confidence", 1.0))
        return list(s.get("classifier_candidates", s.get("rule_candidates", ["clean_match"]))), float(s.get("classifier_confidence", 0.0))

def get_provider(name: str):
    return {"simulated": SimulatedProvider, "gateway": GatewayProvider}[name]()
