"""Level 2 — real transactions, constructed exceptions.

Builds AP cases on a real payables ledger: UK local-authority "spend over £500" files (Open Government
Licence v3, attribution required) or any CSV with supplier, amount and date columns. Real suppliers, real
amounts, real dates, real payment patterns; exceptions and outcomes constructed around them, seed on record.

  # download one or more CSVs from a council's transparency page, then:
  python3 scripts/build_cases_ukspend.py --csv ~/Downloads/spend-over-500-2026-Q1.csv --n 2000 --seed 11 --out cases_ukspend.jsonl
  # column names are auto-detected; override with --supplier-col/--amount-col/--date-col/--desc-col if needed

Evidence label: models REAL (when run) · transactions REAL (source on record) · exceptions CONSTRUCTED · outcomes CONSTRUCTED.
"""
import argparse, csv, json, random, hashlib, re, sys, collections
from pathlib import Path

CANDS = dict(supplier=["supplier", "supplier name", "vendor", "payee", "beneficiary", "supplier_name", "merchant"],
             amount=["amount", "net amount", "gross amount", "amount paid", "value", "total", "amount_paid", "net", "gross"],
             date=["date", "payment date", "transaction date", "paid date", "date paid", "invoice date", "payment_date"],
             desc=["description", "expense type", "expenditure type", "service", "purpose", "narrative", "expense area", "expense_type"])
REASONS_LEGIT = ["We have moved our business account to a new bank as of this month.", "Following restructuring, all payments are to be made to the group treasury account."]
REASONS_FRAUD = ["Due to an audit at our bank, payments must temporarily go to the account below. Please process urgently.", "Kindly confirm by reply to this email address only; our old number is no longer in service."]

def pick(cols, key, override):
    if override: return override
    low = {c.lower().strip(): c for c in cols}
    for cand in CANDS[key]:
        for lc, orig in low.items():
            if cand == lc or cand in lc: return orig
    return None

def money(x):
    s = re.sub(r"[^\d.\-]", "", str(x or ""))
    try: return round(float(s), 2)
    except ValueError: return None

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--csv", required=True, nargs="+"); ap.add_argument("--n", type=int, default=2000); ap.add_argument("--seed", type=int, default=11)
    ap.add_argument("--out", default="cases_ukspend.jsonl"); ap.add_argument("--source", default="UK local-authority spend over £500 (Open Government Licence v3)")
    for k in ("supplier", "amount", "date", "desc"): ap.add_argument(f"--{k}-col")
    a = ap.parse_args(); rng = random.Random(a.seed)
    tx = []
    for path in a.csv:
        with open(path, newline="", encoding="utf-8-sig", errors="replace") as fh:
            rd = csv.DictReader(fh); cols = rd.fieldnames or []
            sc, ac, dc, xc = pick(cols, "supplier", a.supplier_col), pick(cols, "amount", a.amount_col), pick(cols, "date", a.date_col), pick(cols, "desc", a.desc_col)
            if not (sc and ac): sys.exit(f"{path}: could not find supplier/amount columns in {cols}; use --supplier-col/--amount-col")
            for row in rd:
                amt = money(row.get(ac));
                if amt is None or amt <= 0 or not (row.get(sc) or "").strip(): continue
                tx.append(dict(supplier=row[sc].strip(), amount=amt, date=(row.get(dc) or "").strip() if dc else "", desc=(row.get(xc) or "").strip() if xc else "", file=Path(path).name))
    if not tx: sys.exit("no usable transactions")
    by_sup = collections.defaultdict(list)
    for t in tx: by_sup[t["supplier"]].append(t)
    print(f"{len(tx)} real transactions, {len(by_sup)} suppliers, from {len(a.csv)} file(s)", file=sys.stderr)
    out = open(a.out, "w"); n = 0
    while n < a.n:
        t = rng.choice(tx); sup = t["supplier"]; vref = "V" + hashlib.sha1(sup.encode()).hexdigest()[:6].upper(); contact = f"ap@{vref.lower()}.example"
        hist = by_sup[sup]
        # one or two lines that add up to the real amount
        k = 1 if t["amount"] < 2000 or rng.random() < 0.6 else 2
        split = [t["amount"]] if k == 1 else [round(t["amount"] * 0.6, 2), round(t["amount"] * 0.4, 2)]
        lines = [dict(item=(t["desc"] or "Services")[:60] + (f" ({i+1})" if k > 1 else ""), qty=1, unit_price=v, unit="pcs") for i, v in enumerate(split)]
        scen = rng.choices(["clean_match", "price_variance", "bank_detail_change"], [0.74, 0.20, 0.06])[0]
        po_lines = [dict(l) for l in lines]; legit = True; note = None
        if scen == "price_variance":
            j = rng.randrange(len(po_lines)); pct = rng.choice([0.02, 0.04, 0.08, 0.15, 0.25]); po_lines[j]["unit_price"] = round(po_lines[j]["unit_price"] / (1 + pct), 2)
            legit = pct <= 0.04; note = "Uplift per framework agreement indexation clause." if legit else rng.choice([None, "Revised rates."])
        if scen == "bank_detail_change": legit = rng.random() < 0.8
        inv_ref = f"UK{a.seed}-{n:05d}"
        docs = dict(invoice=dict(invoice_ref=inv_ref, vendor_ref=vref, vendor_name=sup, po_ref=f"PO{rng.randint(100000,999999)}", lines=lines, amount=round(sum(l["unit_price"] for l in lines), 2), currency="GBP",
                                 terms="30 days net", note=note, date=t["date"] or "2026-06-15", payee_iban="GB00 XXXX 0000", sender=contact),
                    po=dict(po_ref=f"PO{rng.randint(100000,999999)}", vendor_ref=vref, lines=po_lines, terms="30 days net", date=t["date"] or "2026-06-01"),
                    goods_receipts=[dict(item=l["item"], qty_received=1) for l in lines], price_list={l["item"]: l["unit_price"] for l in po_lines})
        if scen == "bank_detail_change":
            sender = contact if legit else rng.choice([contact, f"finance.{vref.lower()}@mail.example"])
            docs["bank_change_letter"] = dict(sender=sender, subject="Change of bank details", body=rng.choice(REASONS_LEGIT if legit else REASONS_FRAUD),
                                              new_iban=("GB" if legit else rng.choice(["GB", "LT", "AE"])) + "00 XXXX 0000", letterhead_matches_vendor=(legit or rng.random() < 0.6), signed_by="Finance Director")
            docs["vendor_history"] = dict(invoices_12m=len(hist), previous_iban_country="GB", previous_bank_changes_24m=0, contact_on_file=contact, phone_verification_available=True)
        case = dict(case_id=f"H-{hashlib.sha256(inv_ref.encode()).hexdigest()[:10]}", true_class=scen, truth=legit,
                    resolution=("FRAUD_CONFIRMED" if scen == "bank_detail_change" and not legit else "POSTED" if legit else "REJECTED"), docs=docs,
                    provenance=dict(source=a.source, file=t["file"], seed=a.seed, real_amount=t["amount"], real_supplier_invoices_in_file=len(hist),
                                    evidence_label=dict(models="REAL when run", transactions="REAL", exceptions="CONSTRUCTED", outcomes="CONSTRUCTED")))
        out.write(json.dumps(case) + "\n"); n += 1
    print(f"wrote {n} cases -> {a.out}. Attribution: contains public sector information licensed under the Open Government Licence v3.0.", file=sys.stderr)

if __name__ == "__main__": main()
