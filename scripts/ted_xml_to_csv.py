"""TED eForms (UBL) contract-award notices -> award CSV for build_cases_awards.py (--jurisdiction EU).

  python3 ted_xml_to_csv.py --in ~/Downloads/ted_bulk_2026-01-05 --out "$E/07-data/raw/EU/ted_awards.csv"

Walks the folder (recursively) for *.xml; keeps ContractAwardNotice documents; emits one row per lot result.
Columns: notice_id, publication_date, buyer, buyer_type, procedure, result_code, supplier, awarded_amount, estimated_value,
currency, bids, description, justification, cpv, lot_id, country. Fields absent in a notice are left empty - the builder treats
them as missing, never as zero. Reuse of TED data is permitted with attribution ("Source: TED, Publications Office of the EU").
"""
import argparse, csv, os, sys, re
from xml.etree import ElementTree as ET

def L(tag): return tag.split('}')[-1]
def text(el): return (el.text or "").strip() if el is not None else ""

def first(root, name, pred=None):
    for el in root.iter():
        if L(el.tag) == name and (pred is None or pred(el)) and text(el): return el
    return None

def parse(path):
    try: root = ET.parse(path).getroot()
    except ET.ParseError: return []
    if L(root.tag) != "ContractAwardNotice": return []
    notice_id = text(first(root, "NoticeID")) or text(first(root, "ID", lambda e: text(e).startswith("20"))) or os.path.basename(path)
    pub = text(first(root, "IssueDate"))
    proc = text(first(root, "ProcedureCode"))
    # buyer: ContractingParty -> Party -> PartyName/Name
    buyer = ""; btype = ""; country = ""
    for el in root.iter():
        if L(el.tag) == "ContractingParty":
            n = first(el, "Name"); buyer = text(n); t = first(el, "ContractingPartyTypeCode"); btype = text(t); c = first(el, "IdentificationCode"); country = text(c); break
    if not buyer:
        n = first(root, "Name"); buyer = text(n)
    estimated = text(first(root, "EstimatedOverallContractAmount")); currency = ""
    e = first(root, "EstimatedOverallContractAmount")
    if e is not None: currency = e.attrib.get("currencyID", "")
    desc = text(first(root, "Description")); cpv = text(first(root, "ItemClassificationCode")) or text(first(root, "ClassificationCode"))
    just = ""
    for el in root.iter():
        if L(el.tag) in ("ProcessJustification", "ProcessReason", "ProcessReasonCode", "Justification") and text(el): just = text(el); break
    # organizations by id (for winner names)
    orgs = {}
    for el in root.iter():
        if L(el.tag) == "Organization":
            oid = ""; oname = ""
            for sub in el.iter():
                if L(sub.tag) == "ID" and sub.attrib.get("schemeName", "").startswith("organization") and text(sub): oid = text(sub)
                if L(sub.tag) == "Name" and text(sub) and not oname: oname = text(sub)
            if oid: orgs[oid] = oname
    # tenders by id: payable amount and tendering party -> org
    tenders = {}
    for el in root.iter():
        if L(el.tag) == "LotTender":
            tid = ""; amt = ""; cur = ""; party = ""
            for sub in el.iter():
                n = L(sub.tag)
                if n == "ID" and sub.attrib.get("schemeName") == "tender" and text(sub): tid = text(sub)
                if n == "PayableAmount" and text(sub): amt = text(sub); cur = sub.attrib.get("currencyID", cur)
                if n == "ID" and sub.attrib.get("schemeName") == "tendering-party" and text(sub): party = text(sub)
            if tid: tenders[tid] = dict(amount=amt, currency=cur, party=party)
    parties = {}
    for el in root.iter():
        if L(el.tag) == "TenderingParty":
            pid = ""; org = ""
            for sub in el.iter():
                n = L(sub.tag)
                if n == "ID" and sub.attrib.get("schemeName") == "tendering-party" and text(sub): pid = text(sub)
                if n == "ID" and sub.attrib.get("schemeName", "").startswith("organization") and text(sub): org = text(sub)
            if pid: parties[pid] = org
    rows = []
    for el in root.iter():
        if L(el.tag) != "LotResult": continue
        lot = ""; result = ""; bids = ""; tid = ""
        for sub in el.iter():
            n = L(sub.tag)
            if n == "ID" and sub.attrib.get("schemeName") == "Lot" and text(sub): lot = text(sub)
            if n == "TenderResultCode" and text(sub): result = text(sub)
            if n == "ReceivedTenderQuantity" and text(sub) and not bids: bids = text(sub)
            if n == "ID" and sub.attrib.get("schemeName") == "tender" and text(sub): tid = text(sub)
        t = tenders.get(tid, {}); supplier = orgs.get(parties.get(t.get("party", ""), ""), "")
        rows.append(dict(notice_id=notice_id, publication_date=pub, buyer=buyer, buyer_type=btype, procedure=proc, result_code=result, supplier=supplier,
                         awarded_amount=t.get("amount", ""), estimated_value=estimated, currency=(t.get("currency") or currency), bids=bids, description=desc[:300],
                         justification=just[:300], cpv=cpv, lot_id=lot, country=country))
    if not rows:   # notice without lot results: one row with the notice-level fields
        rows.append(dict(notice_id=notice_id, publication_date=pub, buyer=buyer, buyer_type=btype, procedure=proc, result_code="", supplier="", awarded_amount="",
                         estimated_value=estimated, currency=currency, bids="", description=desc[:300], justification=just[:300], cpv=cpv, lot_id="", country=country))
    return rows

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--in", dest="inp", required=True, nargs="+"); ap.add_argument("--out", required=True)
    a = ap.parse_args(); files = []
    for p in a.inp:
        if os.path.isdir(p):
            for d, _, fs in os.walk(p): files += [os.path.join(d, f) for f in fs if f.lower().endswith(".xml")]
        elif p.lower().endswith(".xml"): files.append(p)
    rows = []; n_can = 0
    for f in files:
        r = parse(f)
        if r: n_can += 1; rows += r
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    cols = ["notice_id", "publication_date", "buyer", "buyer_type", "procedure", "result_code", "supplier", "awarded_amount", "estimated_value", "currency", "bids", "description", "justification", "cpv", "lot_id", "country"]
    with open(a.out, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols); w.writeheader(); w.writerows(rows)
    print(f"{len(files)} xml files scanned; {n_can} contract-award notices; {len(rows)} lot results -> {a.out}", file=sys.stderr)
    print("Attribution: Source: TED (Tenders Electronic Daily), Publications Office of the European Union.", file=sys.stderr)

if __name__ == "__main__": main()
