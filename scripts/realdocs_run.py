"""Level 1 — real documents, constructed scenarios, constructed outcomes.

Reads raw/cord/docs.jsonl (from the other chat's fetch_cord.py), sends each real receipt image to a
Mistral vision model for extraction (the real 'S' step: document -> structured fields), wraps the
extracted fields in a constructed AP scenario in *our* adapter's contract (docs.invoice/po/
goods_receipts/price_list/bank_change_letter), runs it through the runtime, and appends the
constructed outcome. Extraction model, latency, tokens and prompt hash are written on the record.

  export EQAL_GATEWAY_KEY=...            # Mistral key (same as the runtime's)
  EQAL_URL=http://localhost:8000 EQAL_API_KEY=demo-key \
  python3 scripts/realdocs_run.py --docs 07-data/raw/cord/docs.jsonl --n 400 --seed 11

Evidence label on every case: models REAL, documents REAL (CORD v2, CC BY 4.0, receipts),
scenarios CONSTRUCTED, outcomes CONSTRUCTED. Receipts are not invoices; they are real documents
with real layout noise, which is what the extraction step needs to face.
"""
import argparse, base64, hashlib, json, os, random, sys, time, urllib.request, urllib.error
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app.adapters_ap import APDeterministic

URL, KEY = os.getenv("EQAL_URL", "http://localhost:8000"), os.getenv("EQAL_API_KEY", "demo-key")
GW, GWKEY = os.getenv("EQAL_GATEWAY_URL", "https://api.mistral.ai"), os.environ.get("EQAL_GATEWAY_KEY", "")
EXTRACT_MODEL = os.getenv("EQAL_EXTRACT_MODEL", "pixtral-12b-latest")
EXTRACT_PRICE = (float(os.getenv("EQAL_PRICE_X_IN", "0.15")), float(os.getenv("EQAL_PRICE_X_OUT", "0.15")))   # USD per 1M, check mistral.ai/pricing
PROMPT = ("You are an accounts-payable extraction service. From the document image, return ONLY a JSON object with keys: "
          "vendor_name (string), invoice_total (number), currency (string or null), invoice_lines (array of {desc: string, qty: number, price: number}). No prose.")
PROMPT_HASH = hashlib.sha256(PROMPT.encode()).hexdigest()[:16]
REASONS_LEGIT = ["We have moved our business account to a new bank as of this month.", "Following our merger with the parent group, all payments are to be made to the group treasury account."]
REASONS_FRAUD = ["Due to an audit at our bank, payments must temporarily go to the account below. Please process urgently before the next payment run.",
                 "Please note our new remittance details effective immediately. Kindly confirm by reply to this email address only."]

def call(m, path, body=None):
    req = urllib.request.Request(URL + path, method=m, data=json.dumps(body).encode() if body is not None else None, headers={"Content-Type": "application/json", "X-API-Key": KEY})
    with urllib.request.urlopen(req, timeout=120) as r: return json.load(r)

def extract(image_path):
    """Real extraction: image -> fields. Returns (fields|None, meta). Contract failures -> fields None, meta.code MALFORMED."""
    b64 = base64.b64encode(open(image_path, "rb").read()).decode()
    body = {"model": EXTRACT_MODEL, "temperature": 0, "response_format": {"type": "json_object"},
            "messages": [{"role": "user", "content": [{"type": "text", "text": PROMPT}, {"type": "image_url", "image_url": f"data:image/png;base64,{b64}"}]}]}
    req = urllib.request.Request(f"{GW}/v1/chat/completions", data=json.dumps(body).encode(), headers={"Content-Type": "application/json", "Authorization": f"Bearer {GWKEY}"})
    t0 = time.time()
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=90) as r: out = json.load(r)
            u = out.get("usage", {}); ms = int((time.time() - t0) * 1000)
            meta = dict(model=out.get("model", EXTRACT_MODEL), prompt_hash=PROMPT_HASH, latency_ms=ms, tokens_in=u.get("prompt_tokens", 0), tokens_out=u.get("completion_tokens", 0),
                        cost_usd=round((u.get("prompt_tokens", 0) * EXTRACT_PRICE[0] + u.get("completion_tokens", 0) * EXTRACT_PRICE[1]) / 1e6, 6), code="OK")
            try:
                txt = out["choices"][0]["message"]["content"].strip().strip("`")
                if txt.startswith("json"): txt = txt[4:]
                f = json.loads(txt); assert isinstance(f.get("invoice_lines"), list); float(f["invoice_total"])
                return f, meta
            except Exception as ex:
                meta["code"] = "MALFORMED"; meta["detail"] = str(ex)[:120]; return None, meta
        except urllib.error.HTTPError as ex:
            if ex.code in (429, 500, 502, 503, 504): time.sleep(2 * (attempt + 1)); continue
            return None, dict(model=EXTRACT_MODEL, prompt_hash=PROMPT_HASH, latency_ms=int((time.time() - t0) * 1000), code="ERROR", detail=f"HTTP {ex.code}")
        except Exception as ex:
            time.sleep(2 * (attempt + 1)); last = str(ex)
    return None, dict(model=EXTRACT_MODEL, prompt_hash=PROMPT_HASH, latency_ms=int((time.time() - t0) * 1000), code="TIMEOUT")

def money(x):
    try: return round(float(str(x).replace(",", "").replace("Rp", "").replace("$", "").strip()), 2)
    except Exception: return None

def build_case(fields, doc, i, seed, rng):
    """Wrap extracted fields in a constructed scenario, in the adapter's contract."""
    lines = [dict(item=str(l.get("desc", "item"))[:60], qty=(money(l.get("qty")) or 1.0), unit_price=money(l.get("price")), unit="pcs")
             for l in fields["invoice_lines"] if money(l.get("price")) is not None]
    if not lines: return None
    vendor = fields.get("vendor_name") or f"Vendor-{doc['doc_id'][-5:]}"
    vref = "V" + hashlib.sha1(vendor.encode()).hexdigest()[:6].upper()
    contact = f"ap@{vref.lower()}.example"
    scen = rng.choices(["clean_match", "price_variance", "bank_detail_change"], [0.72, 0.22, 0.06])[0]
    po_lines = [dict(l) for l in lines]; legit = True; note = None
    if scen == "price_variance":
        k = rng.randrange(len(po_lines)); pct = rng.choice([0.02, 0.04, 0.08, 0.15, 0.25])
        po_lines[k]["unit_price"] = round(po_lines[k]["unit_price"] / (1 + pct), 2)
        legit = pct <= 0.04; note = "Price adjusted per contractual index clause (clause 7.2)." if legit else rng.choice([None, "Updated pricing."])
    if scen == "bank_detail_change": legit = rng.random() < 0.8
    inv_total = round(sum(l["qty"] * l["unit_price"] for l in lines), 2)
    inv = dict(invoice_ref=f"RD{seed}-{i:05d}", vendor_ref=vref, vendor_name=vendor, po_ref=f"PO{rng.randint(100000, 999999)}", lines=lines, amount=inv_total,
               currency=fields.get("currency") or "IDR", terms="30 days net", note=note, date="2026-06-15", payee_iban=f"XX{rng.randint(10,99)} XXXX 0000", sender=contact)
    docs = dict(invoice=inv, po=dict(po_ref=inv["po_ref"], vendor_ref=vref, lines=po_lines, terms="30 days net", date="2026-06-01"),
                goods_receipts=[dict(item=l["item"], qty_received=l["qty"]) for l in lines],
                price_list={l["item"]: l["unit_price"] for l in po_lines}, source_image=doc["image"])
    if scen == "bank_detail_change":
        sender = contact if legit else rng.choice([contact, f"finance.{vref.lower()}@mail.example"])
        docs["bank_change_letter"] = dict(sender=sender, subject="Change of bank details", body=rng.choice(REASONS_LEGIT if legit else REASONS_FRAUD),
                                          new_iban=("XX" if legit else rng.choice(["XX", "LT", "AE"])) + "00 XXXX 0000", letterhead_matches_vendor=(legit or rng.random() < 0.6), signed_by="CFO")
        docs["vendor_history"] = dict(invoices_12m=rng.randint(3, 40), previous_iban_country="XX", previous_bank_changes_24m=0, contact_on_file=contact, phone_verification_available=True)
    return dict(case_id=f"H-{hashlib.sha256(inv['invoice_ref'].encode()).hexdigest()[:10]}", true_class=scen, truth=legit,
                resolution=("FRAUD_CONFIRMED" if scen == "bank_detail_change" and not legit else "POSTED" if legit else "REJECTED"), docs=docs,
                provenance=dict(source_dataset=doc.get("source_dataset", "CORD v2"), doc_id=doc["doc_id"], seed=seed,
                                evidence_label=dict(models="REAL", documents="REAL", scenarios="CONSTRUCTED", outcomes="CONSTRUCTED")))

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--docs", required=True); ap.add_argument("--n", type=int, default=400); ap.add_argument("--seed", type=int, default=11); ap.add_argument("--out", default="cases_realdocs.jsonl")
    a = ap.parse_args(); rng = random.Random(a.seed); ad = APDeterministic()
    docs = [json.loads(l) for l in open(a.docs)]; n = failed = skipped = 0; xcost = 0.0; t0 = time.time()
    with open(a.out, "w") as fout:
        for i in range(a.n):
            doc = docs[i % len(docs)]
            fields, meta = extract(doc["image"]); xcost += meta.get("cost_usd", 0)
            if fields is None: failed += 1; fout.write(json.dumps(dict(doc_id=doc["doc_id"], extraction=meta, skipped="extraction_failed")) + "\n"); continue
            case = build_case(fields, doc, i, a.seed, rng)
            if not case: skipped += 1; continue
            body = ad.build(case); body["input_refs"]["extraction"] = dict(model=meta["model"], prompt_hash=meta["prompt_hash"], latency_ms=meta["latency_ms"], tokens_in=meta["tokens_in"], tokens_out=meta["tokens_out"], cost_usd=meta["cost_usd"])
            body["input_refs"]["provenance"] = case["provenance"]
            try: d = call("POST", "/v1/decide", body)
            except urllib.error.HTTPError as ex:
                if ex.code == 409: skipped += 1; continue
                raise
            truth = case["truth"]; rec = (d.get("path") or [{}])[-1].get("verdict")
            human = dict(touches=d["human"]["approvers"], decision="approve" if truth else "reject", override=(rec is not None and rec != truth)) if d["human"] else None
            final = truth if d["human"] else rec; ok = (final == truth) if final is not None else None
            value = ("impersonation_blocked" if case["resolution"] == "FRAUD_CONFIRMED" and not final else "fraud_paid" if case["resolution"] == "FRAUD_CONFIRMED" else "posted_ok" if (ok and truth) else "rejected_ok" if ok else "wrong_post" if final else "wrong_reject")
            call("POST", f"/v1/outcomes/{d['case_id']}", dict(kind="observed", value=value, correct=ok, truth=truth, realised_effect=(case["docs"]["invoice"]["amount"] if value == "impersonation_blocked" else 0.0), human=human,
                                                          detail=dict(true_class=case["true_class"], resolution=case["resolution"], provenance=case["provenance"], label="constructed outcome")))
            fout.write(json.dumps(case) + "\n"); n += 1
            if n % 25 == 0: print(f"{n} cases, extraction failures {failed}, {time.time()-t0:.0f}s, extraction ${xcost:.3f}", file=sys.stderr)
    print(f"decided {n} cases from real documents; extraction failures {failed}; skipped {skipped}; extraction cost ${xcost:.3f}; {time.time()-t0:.0f}s", file=sys.stderr)
    print("Evidence label: models REAL · documents REAL (CORD v2, CC BY 4.0, receipts) · scenarios CONSTRUCTED · outcomes CONSTRUCTED")

if __name__ == "__main__": main()
