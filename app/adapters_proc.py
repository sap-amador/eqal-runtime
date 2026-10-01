"""Procurement deterministic adapter (class D) and evidence-pack builder for award cases built by build_cases_awards.py.
Rules compute facts: variance to estimate, bid count, amendment %, supplier share, status flags. Judgement questions go to
models only where facts leave one: is this justification plausible? Thresholds come from the pack's jurisdiction variant."""
import hashlib, json, os, re

class ProcDeterministic:
    def __init__(self, thresholds=None):
        self.t = thresholds or {}
    def build(self, case):
        aw = case["docs"]["award"]; est = aw.get("estimated_value") or 0; amt = aw["awarded_value"]
        var = ((amt - est) / est) if est else None
        single = (aw.get("bid_count") == 1)
        amend = bool(aw.get("modification")) and str(aw.get("modification")) not in ("0", "00", "P00000")
        emergency = bool(re.search(r"emergency|urgent|without prior|sole source|only one source", f"{aw.get('procedure_type','')} {aw.get('justification_text','')}", re.I))
        debar = bool(re.search(r"debar|exclud|suspend", aw.get("supplier_status") or "", re.I))
        share = aw.get("supplier_share_of_buyer_spend") or 0
        limit = self.t.get("single_bid_justification_required_above", 100000)
        # classification by rules
        proc_l = (aw.get("procedure_type") or "").lower(); ceilings = self.t.get("procedure_ceilings", {}); status = (aw.get("supplier_status") or aw.get("status") or "").lower()
        if emergency: cands = ["emergency_procurement"]
        elif proc_l == "quotation" and ceilings.get("quotation") and amt > float(ceilings["quotation"]): cands = ["procedure_threshold"]
        elif "no supplier" in status or "no award" in status: cands = ["market_failure"]
        elif debar: cands = ["award_eligibility"]
        elif single: cands = ["single_bid"]
        elif amend: cands = ["contract_amendment"]
        elif var is not None and abs(var) > 0.10: cands = ["price_vs_estimate"]
        elif share > 0.4: cands = ["supplier_concentration"]
        else: cands = ["award_eligibility"]
        # rule-decidable exception classes (US finding): single bid with a competed/statutory code or a stated authority; variance within tolerance; amendment within limit
        auth = aw.get("non_competition_authority") or ""; proc = (aw.get("procedure_type") or "").lower()
        rule_verdict = None
        if cands == ["procedure_threshold"]: rule_verdict = False
        if cands == ["market_failure"]: rule_verdict = None
        if cands == ["award_eligibility"] and proc_l in ("quotation", "tender") and ceilings: rule_verdict = True   # procedure consistent with value
        if cands == ["single_bid"]: rule_verdict = True if any(w in proc for w in ["competed under sap", "full and open", "not available for competition"]) else (bool(auth) if "not competed" in proc else None)
        if cands == ["price_vs_estimate"] and var is not None: rule_verdict = abs(var) <= float(self.t.get("variance_tolerance", 0.10))
        if cands == ["contract_amendment"] and est and abs(amt) < est * 0.999: rule_verdict = (abs(amt) / est) <= float(self.t.get("amendment_limit", 0.25))   # base == own obligation: not assessable
        rule_pass = (cands == ["award_eligibility"] and not debar) or (rule_verdict is not None)
        signals = dict(supplier_new_to_agency=False, supplier_concentration_high=share > 0.4, emergency_flag=emergency, amendment_large=amend, single_bid=single,
                       estimate_missing=not est, debarment_hit=debar, rule_candidates=cands, rule_class_confidence=1.0, rule_pass=rule_pass, rule_verdict=(rule_verdict if rule_verdict is not None else (not debar)),
                       rule_confidence=0.995 if rule_pass else 0.5, verified=not debar, verify_confidence=0.97 if not debar else 0.99, adapter_id="proc-deterministic-v0.1")
        flags = dict(any_flag=debar or emergency, above_threshold=amt > limit, share_above_limit=share > 0.4, amendment_above_limit=amend)
        evidence = dict(award=aw, status=aw.get("supplier_status"), variance_pct=(round(var * 100, 2) if var is not None else None), bid_count=aw.get("bid_count"), single_bid=single, amendment=amend,
                        supplier_share_of_buyer_spend=share, thresholds=self.t, justification_text=aw.get("justification_text", ""))
        return dict(case_id=case["case_id"], input_refs=evidence, signals=signals, flags=flags, harm_class="financial", reversible=not emergency,
                    evidence_hashes=dict(award=hashlib.sha256(json.dumps(aw, sort_keys=True).encode()).hexdigest()[:16]))
