"""AP deterministic adapter (intelligence class D) and evidence-pack builder.

Runs on the adapter side of the line, before the runtime is called:
- three-way match of invoice lines against PO and goods receipts, with tolerance;
- duplicate detection by content hash over the last N invoices seen;
- bank-detail change detection (payee IBAN differs from the vendor's IBAN on file);
- rule candidates for the classification ladder, with confidence 1.0 when the rules are
  conclusive and 0.5 when they cannot exclude a restrictive class;
- the evidence pack: only the fields the pack's evidence list names. No real IBAN leaves
  the adapter (synthetic, masked values here; in production, booleans and hashes).
"""
import hashlib, json

TOLERANCE_PCT = 0.5      # price tolerance, percent of PO line value
TOLERANCE_ABS = 5.00     # euros, per invoice

class APDeterministic:
    def __init__(self): self.seen = {}
    def match(self, docs):
        inv, po, gr = docs["invoice"], docs["po"], docs["goods_receipts"]
        po_by = {l["item"]: l for l in po["lines"]}; gr_by = {g["item"]: g["qty_received"] for g in gr}
        variance = 0.0; extra = []; qty_issue = False
        for l in inv["lines"]:
            p = po_by.get(l["item"])
            if not p: extra.append(l); variance += l["qty"] * l["unit_price"]; continue
            variance += l["qty"] * (l["unit_price"] - p["unit_price"])
            if l["qty"] > gr_by.get(l["item"], 0): qty_issue = True
        po_total = sum(l["qty"] * l["unit_price"] for l in po["lines"])
        within = abs(variance) <= max(TOLERANCE_ABS, po_total * TOLERANCE_PCT / 100)
        return dict(variance=round(variance, 2), extra_lines=len(extra), qty_issue=qty_issue, within_tolerance=within, po_total=round(po_total, 2))

    def duplicate(self, inv):
        """A duplicate is the same vendor invoice number, or the same vendor + amount + invoice date.
        Recurring identical orders on different dates are legitimate and must not trip this."""
        k1 = hashlib.sha256(json.dumps([inv["vendor_ref"], inv["invoice_ref"]]).encode()).hexdigest()
        k2 = hashlib.sha256(json.dumps([inv["vendor_ref"], inv["amount"], inv["date"]]).encode()).hexdigest()
        dup = k1 in self.seen or k2 in self.seen
        self.seen[k1] = inv["invoice_ref"]; self.seen[k2] = inv["invoice_ref"]; return dup

    def build(self, case):
        docs = case["docs"]; inv = docs["invoice"]; m = self.match(docs)
        bank_changed = "bank_change_letter" in docs or (inv.get("payee_iban") != docs.get("vendor_iban_on_file", inv.get("payee_iban")))
        dup = self.duplicate(inv)
        # classification by rules
        if bank_changed: cands, cconf = ["bank_detail_change"], 1.0
        elif m["within_tolerance"] and not m["extra_lines"] and not m["qty_issue"]: cands, cconf = ["clean_match"], 1.0
        else: cands, cconf = ["price_variance"], 1.0
        # D verdict: rules alone approve only a clean match; anything else is not decidable by rules
        rule_pass = (cands == ["clean_match"]) and not dup
        signals = dict(payee_bank_changed=bank_changed, vendor_contact_anomaly=False, first_invoice=False, just_below_threshold=False,
                       adapter_version="ap-deterministic-v0.5.1",
                       po_match_exact=m["within_tolerance"], master_data_complete=True, duplicate_suspected=dup,
                       rule_candidates=cands, rule_class_confidence=cconf, rule_pass=rule_pass, rule_confidence=0.998 if rule_pass else 0.5,
                       verified=False, verify_confidence=0.0, adapter_id="ap-deterministic-v0.5")
        if bank_changed:
            letter = docs["bank_change_letter"]; hist = docs["vendor_history"]
            signals["vendor_contact_anomaly"] = letter["sender"] != hist["contact_on_file"] or not letter["letterhead_matches_vendor"]
            signals["first_invoice"] = hist["invoices_12m"] < 3
        # evidence pack: what the models may see (pack evidence lists)
        pl = docs["price_list"]
        evidence = dict(invoice=dict(ref=inv["invoice_ref"], vendor=inv["vendor_name"], date=inv["date"], amount=inv["amount"], currency=inv["currency"], terms=inv["terms"], note=inv.get("note"),
                                     lines=[dict(item=l["item"], qty=l["qty"], unit=l["unit"], unit_price=l["unit_price"]) for l in inv["lines"]]),
                        po=dict(ref=docs["po"]["po_ref"], date=docs["po"]["date"], terms=docs["po"]["terms"], lines=docs["po"]["lines"]),
                        goods_receipts=docs["goods_receipts"], contracted_price_list={l["item"]: pl.get(l["item"]) for l in inv["lines"]},
                        three_way_match=m, duplicate_suspected=dup, variance=m["variance"])
        if bank_changed:
            letter = docs["bank_change_letter"]; hist = docs["vendor_history"]
            evidence["bank_change_request"] = dict(sender=letter["sender"], subject=letter["subject"], body=letter["body"], signed_by=letter["signed_by"],
                                                  letterhead_matches_vendor=letter["letterhead_matches_vendor"], new_account_country=letter["new_iban"][:2],
                                                  previous_account_country=hist["previous_iban_country"], contact_on_file=hist["contact_on_file"],
                                                  invoices_from_vendor_12m=hist["invoices_12m"], previous_bank_changes_24m=hist["previous_bank_changes_24m"],
                                                  phone_verification_available=hist["phone_verification_available"])
        flags = dict(variance_lte=abs(m["variance"]) <= 250)
        return dict(case_id=case["case_id"], input_refs=evidence, signals=signals, flags=flags, harm_class="financial", reversible=not bank_changed,
                    evidence_hashes=dict(invoice=hashlib.sha256(json.dumps(inv, sort_keys=True).encode()).hexdigest()[:16]))
