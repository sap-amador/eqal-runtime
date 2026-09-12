"""A stand-in OpenAI-compatible endpoint for pipeline tests only (not a model)."""
import json, random
from fastapi import FastAPI, Request
app = FastAPI()
@app.post("/v1/chat/completions")
async def chat(req: Request):
    body = await req.json(); txt = body["messages"][-1]["content"]; rng = random.Random(hash(txt) & 0xffff)
    ev = json.loads(txt.split("do not assume anything beyond it):\n", 1)[1].split("\nAnswer with a single JSON", 1)[0])
    if "bank_change_request" in ev:
        b = ev["bank_change_request"]; bad = (b["sender"] != b["contact_on_file"]) + (not b["letterhead_matches_vendor"]) + (b["new_account_country"] != b["previous_account_country"]) + ("urgent" in b["body"].lower() or "reply" in b["body"].lower() or "do not call" in b["body"].lower())
        approve = bad == 0 and rng.random() < 0.97 or (bad == 1 and rng.random() < 0.5); conf = 0.9 if bad != 1 else 0.7
    else:
        m = ev["three_way_match"]; note = (ev["invoice"].get("note") or "").lower()
        legit = m["within_tolerance"] or "clause" in note or "surcharge" in note or abs(m["variance"]) < ev["three_way_match"]["po_total"] * 0.045
        approve = legit if rng.random() < 0.96 else not legit; conf = 0.95 if m["within_tolerance"] else 0.85
    content = json.dumps({"approve": approve, "confidence": conf, "reason": "mock"})
    return {"choices": [{"message": {"content": content}}], "usage": {"prompt_tokens": len(txt) // 4, "completion_tokens": 20}}
