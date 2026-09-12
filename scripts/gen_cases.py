"""Generate a realistic synthetic accounts-payable world for Level 1 measurement.

Unlike the v0.3 simulator, cases carry documents: an invoice with line items, the
matching PO, the vendor's contracted price list, goods receipts, and for bank-detail
changes the vendor letter and the vendor's recent history. The intelligence classes
have to read and judge; nothing is pre-scored. Ground truth and a resolution code are
kept for measurement only.

  python3 scripts/gen_cases.py --n 2000 --seed 11 --out cases.jsonl
"""
import argparse, json, random, hashlib, datetime as dt

PRODUCTS = [("Hex bolt M8x40 A2", "pcs", 0.18), ("Bearing 6205-2RS", "pcs", 4.20), ("Hydraulic hose 3/8in", "m", 11.50),
            ("Copper busbar 30x5", "m", 27.90), ("Filter element HP-2", "pcs", 46.00), ("Servo motor 400W", "pcs", 312.00),
            ("Control cable 4x1.5", "m", 2.35), ("Safety relay PNOZ", "pcs", 148.00), ("Pallet EUR wood", "pcs", 9.80),
            ("Cutting oil 20L", "pcs", 84.00), ("Steel sheet 2mm 1x2m", "pcs", 39.50), ("Pneumatic cylinder 32/100", "pcs", 71.20)]
VENDORS = ["Nordmetall GmbH", "Vela Componentes SL", "Brenner Antriebstechnik", "Lauwers Industrial BV", "Ostrava Steel a.s.",
           "Halden Hydraulik AS", "Piedmont Fasteners Srl", "Rheinland Elektro KG", "Kaunas Cables UAB", "Aalto Fluid Oy"]
BANKS = ["DE", "ES", "AT", "NL", "CZ", "NO", "IT", "DE", "LT", "FI"]
REASONS_LEGIT = ["We have moved our business account to a new bank as of this month.", "Following our merger with the parent group, all payments are to be made to the group treasury account.",
                 "Our previous bank has closed its corporate branch; please update our details."]
REASONS_FRAUD = ["Due to an audit at our bank, payments must temporarily go to the account below. Please process urgently before the next payment run.",
                 "Please note our new remittance details effective immediately. Kindly confirm by reply to this email address only.",
                 "Our accounts team has changed; use the following account for all outstanding invoices. Do not call the old number, it is no longer in service."]

def iban(rng, cc): return f"{cc}{rng.randint(10,99)} XXXX {rng.randint(1000,9999)} {rng.randint(1000,9999)} {rng.randint(10,99)}"   # synthetic, masked
def h(x): return hashlib.sha256(str(x).encode()).hexdigest()[:10]

def make_world(rng):
    vendors = []
    for i, name in enumerate(VENDORS):
        items = rng.sample(PRODUCTS, k=rng.randint(3, 6))
        pl = {p[0]: round(p[2] * rng.uniform(0.85, 1.2), 2) for p in items}
        vendors.append(dict(vendor_ref=f"V{i+1:04d}", name=name, country=BANKS[i], price_list=pl, iban=iban(rng, BANKS[i]),
                            terms=rng.choice(["30 days net", "14 days 2% discount, 30 net", "60 days net"]), contact=f"ap@{name.split()[0].lower()}.example",
                            history=dict(invoices_12m=rng.randint(4, 60), avg_amount=round(rng.uniform(800, 20000), 2), last_bank_change=None)))
    return vendors

def make_case(i, rng, vendors):
    v = rng.choice(vendors)
    n_lines = rng.randint(1, 4)
    items = rng.sample(list(v["price_list"].items()), k=min(n_lines, len(v["price_list"])))
    po_lines = [dict(item=k, qty=rng.choice([10, 25, 50, 100, 200, 500]), unit_price=p, unit=next(x[1] for x in PRODUCTS if x[0] == k)) for k, p in items]
    po = dict(po_ref=f"PO{rng.randint(10000, 99999)}", vendor_ref=v["vendor_ref"], lines=po_lines, terms=v["terms"], date=(dt.date(2026, 6, 1) + dt.timedelta(days=rng.randint(0, 80))).isoformat())
    r = rng.random()
    cls, legit, note = "clean_match", True, None
    inv_lines = [dict(l) for l in po_lines]
    gr = [dict(item=l["item"], qty_received=l["qty"]) for l in po_lines]
    if r < 0.78:
        pass                                                   # clean: prices and quantities match
    elif r < 0.96:
        cls = "price_variance"
        l = rng.choice(inv_lines)
        if rng.random() < 0.85:                                # legitimate variance: contracted index clause, packaging surcharge, or rounding
            legit = True
            kind = rng.choice(["index", "surcharge", "rounding"])
            if kind == "index": l["unit_price"] = round(l["unit_price"] * rng.uniform(1.01, 1.04), 2); note = "Price adjusted per contractual steel-index clause (clause 7.2)."
            elif kind == "surcharge": inv_lines.append(dict(item="Packaging and pallet surcharge", qty=1, unit_price=round(rng.uniform(12, 60), 2), unit="pcs")); note = "Packaging surcharge as per framework agreement annex B."
            else: l["unit_price"] = round(l["unit_price"] + rng.choice([0.01, 0.02, -0.01]), 2); note = None
        else:                                                  # not legitimate: wrong list price, or old price applied
            legit = False
            l["unit_price"] = round(l["unit_price"] * rng.uniform(1.08, 1.35), 2); note = rng.choice([None, "Updated pricing 2026.", "As quoted."])
    else:
        cls = "bank_detail_change"
        legit = rng.random() < 0.82
    amount = round(sum(l["qty"] * l["unit_price"] for l in inv_lines), 2)
    variance = round(sum(l["qty"] * l["unit_price"] for l in inv_lines) - sum(l["qty"] * l["unit_price"] for l in po_lines), 2)
    inv = dict(invoice_ref=f"INV-{2026}-{i:06d}", vendor_ref=v["vendor_ref"], vendor_name=v["name"], po_ref=po["po_ref"], lines=inv_lines, amount=amount,
               currency="EUR", terms=v["terms"], note=note, date=(dt.date.fromisoformat(po["date"]) + dt.timedelta(days=rng.randint(3, 30))).isoformat(),
               payee_iban=v["iban"], sender=v["contact"])
    docs = dict(invoice=inv, po=po, goods_receipts=gr, price_list={k: p for k, p in v["price_list"].items()})
    if cls == "bank_detail_change":
        new_iban = iban(rng, v["country"] if legit or rng.random() < 0.5 else rng.choice(["LT", "PL", "GB", "AE"]))
        sender = v["contact"] if legit else rng.choice([v["contact"], v["contact"].replace(".example", "-accounts.example"), f"finance.{v['name'].split()[0].lower()}@mail.example"])
        docs["bank_change_letter"] = dict(sender=sender, subject="Change of bank details", body=rng.choice(REASONS_LEGIT if legit else REASONS_FRAUD),
                                          new_iban=new_iban, letterhead_matches_vendor=(legit or rng.random() < 0.6), signed_by=rng.choice(["CFO", "Accounts Receivable", "Managing Director"]))
        docs["vendor_history"] = dict(invoices_12m=v["history"]["invoices_12m"], previous_iban_country=v["country"], previous_bank_changes_24m=0 if legit else rng.choice([0, 1]),
                                      contact_on_file=v["contact"], phone_verification_available=True)
        inv["payee_iban"] = new_iban
    resolution = ("FRAUD_CONFIRMED" if cls == "bank_detail_change" and not legit else "POSTED" if legit else "REJECTED")
    return dict(case_id=f"H-{h(inv['invoice_ref'])}", true_class=cls, truth=legit, resolution=resolution, variance=variance, docs=docs)

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--n", type=int, default=2000); ap.add_argument("--seed", type=int, default=11); ap.add_argument("--out", default="cases.jsonl")
    a = ap.parse_args(); rng = random.Random(a.seed); vendors = make_world(rng)
    with open(a.out, "w") as f:
        for i in range(a.n): f.write(json.dumps(make_case(i, rng, vendors)) + "\n")
    print(f"wrote {a.n} cases to {a.out}")

if __name__ == "__main__": main()
