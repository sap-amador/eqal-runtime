"""Historical-export mapping shared by scripts/retro_ingest.py and POST /v1/ingest/csv."""
import csv, io, hashlib
APPROVE_RIGHT = {"POSTED", "PARKED_THEN_POSTED"}
REJECT_RIGHT = {"REJECTED", "REVERSED", "DISPUTED", "FRAUD_CONFIRMED", "DUPLICATE_CONFIRMED"}
def b(x): return str(x).strip().lower() in ("1", "true", "yes", "y")
def f(x, d=0.0):
    try: return float(x)
    except (TypeError, ValueError): return d
def h(x): return hashlib.sha256(str(x).encode()).hexdigest()[:16]

def to_case(row, tol):
    code = (row.get("exception_code") or "OTHER").strip().upper()
    variance = abs(f(row.get("price_variance")))
    bank = b(row.get("payee_bank_changed"))
    # classification signals for the deterministic rung; candidates the rule cannot exclude go conservative
    cands = ["bank_detail_change"] if bank or code == "BANK" else (["clean_match"] if code == "MATCH" and variance <= tol else ["price_variance"])
    if code in ("OTHER", "NOPO", "DUP") and not bank: cands.append("bank_detail_change") if row.get("payee_bank_changed", "") == "" else None
    signals = dict(payee_bank_changed=bank, vendor_contact_anomaly=False, first_invoice=b(row.get("first_invoice_from_vendor")),
                   just_below_threshold=False, po_match_exact=(code == "MATCH"), master_data_complete=(row.get("payee_bank_changed", "") != ""),
                   rule_candidates=cands, rule_class_confidence=(1.0 if len(cands) == 1 else 0.5),
                   rule_pass=(code == "MATCH"), rule_confidence=0.998, verified=False, verify_confidence=0.0, adapter_id="retro-csv-v0.1")
    truth = (row.get("resolution") or "").strip().upper() in APPROVE_RIGHT
    signals["_truth"] = truth                      # used only by the simulated provider; stripped before storage
    signals["_true_class"] = cands[0]
    return dict(case_id=f"H-{h(row['case_id'])}", input_refs=dict(amount=f(row.get("amount")), currency=row.get("currency", ""), variance=variance,
                exception_code=code, gr_exists=b(row.get("gr_exists")), company_code=row.get("company_code", "")),
                signals=signals, flags=dict(variance_lte=variance <= 250), harm_class="financial", reversible=not (bank or code == "BANK"),
                evidence_hashes=dict(vendor=h(row.get("vendor_ref", "")), po=h(row.get("po_ref", ""))), observe_only=True), truth

def to_outcome(row, truth, dec, rates, minutes):
    res = (row.get("resolution") or "").strip().upper()
    touched = int(f(row.get("touched_by"), 0)); roles = [r.strip().lower() for r in (row.get("roles_touched") or "").split(";") if r.strip()]
    rate = rates["treasury"] if any("treasur" in r for r in roles) else rates["supervisor"] if any("superv" in r for r in roles) else rates["clerk"]
    human_cost = touched * minutes / 60 * rate
    rec_verdict = (dec.get("path") or [{}])[-1].get("verdict")
    held = res in ("FRAUD_CONFIRMED", "DUPLICATE_CONFIRMED")
    value = ("impersonation_blocked" if res == "FRAUD_CONFIRMED" else "duplicate_held" if res == "DUPLICATE_CONFIRMED" else
             "posted_ok" if truth else "rejected_ok")
    correct = None if rec_verdict is None else (rec_verdict == truth)     # would EQAL's recommendation have matched what was right
    return dict(kind="observed", value=value, correct=correct, truth=truth, realised_effect=(f(row.get("amount")) if held else 0.0),
                human=dict(touches=touched, decision=("approve" if truth else "reject"), override=(rec_verdict is not None and rec_verdict != truth),
                           approver_ids=[], human_cost_override=round(human_cost, 2)),
                detail=dict(resolution=res, resolved_at=row.get("resolved_at"), received_at=row.get("received_at")))


def rows_from_csv(text):
    return list(csv.DictReader(io.StringIO(text)))
