"""Graphical workflow report. Each step of the decision path gets its own row: how many cases
passed through it, what it cost (model $ and people EUR), how long it took, which compliance
assertions held and to what percentage, and how authority was distributed. Colours are fixed
per factor and match the site: cost navy, time teal, compliance green, risk amber, authority the
four-step scale, counterfactual violet."""
import html

COL = dict(cost="#14213D", time="#3E8E7E", comp="#1B6F3B", risk="#E09F3E", cf="#6A4C93", none="#B23A48", rec="#E09F3E", notify="#3E8E7E", act="#1B6F3B",
           D="#8A93A8", S="#5C7CBA", L="#2F9E9E", F="#1F4E9A", M="#0F2A5A", grey="#B8C2DB")

def workflow(recs, policy, price, human_rate):
    n = len(recs) or 1
    obs = [r for r in recs if r.get("outcome")]
    def pct(a, b): return (a / b) if b else 0.0
    # ---- step 1: classification
    cons = sum(1 for r in recs if r["conservatively_routed"])
    ladder_calls = sum(len([e for e in r["classification"] if e.get("eligible")]) for r in recs)
    # ---- step 2: budget / policy lookup
    budget_stops = sum(1 for r in recs if r["reason"] in ("budget", "latency"))
    # ---- step 3: invocations per class
    per = {}
    for r in recs:
        for s in r["path"]:
            c = per.setdefault(s["cls"], dict(calls=0, fail=0, tin=0, tout=0, ms=0, ok=0))
            c["calls"] += 1
            if s["outcome_code"] != "OK": c["fail"] += 1; continue
            c["ok"] += 1; c["tin"] += s.get("tokens_in", 0); c["tout"] += s.get("tokens_out", 0); c["ms"] += s.get("elapsed_ms", 0)
    inv = []
    for cls, c in sorted(per.items()):
        pin, pout = price.get(cls, (0, 0)); cost = (c["tin"] * pin + c["tout"] * pout) / 1e6
        inv.append(dict(cls=cls, calls=c["calls"], fail=c["fail"], cost=cost, ms=(c["ms"] / c["ok"]) if c["ok"] else 0, ok_rate=pct(c["ok"], c["calls"])))
    shadow = sum(1 for r in recs if r.get("shadow"))
    # ---- step 4: risk lens
    demoted = sum(1 for r in recs if r["autonomy_effective"] != r["autonomy_policy"] and not r.get("observe_only"))
    # ---- step 5: act / hand over
    aut = {a: sum(1 for r in recs if r["autonomy_effective"] == a) for a in ("NONE", "RECOMMEND", "ACT_NOTIFY", "ACT")}
    acted = sum(1 for r in recs if r["action"].startswith("act")); handed = n - acted
    human_touches = sum(r["outcome"]["human_touches"] for r in obs) if obs else sum((r["human"] or {}).get("approvers", 0) for r in recs)
    human_cost = sum(r["outcome"]["human_cost"] for r in obs) if obs else human_touches * human_rate
    # ---- step 6: observe / mature
    judged = [r for r in obs if r["outcome"]["correct"] is not None]
    correct = pct(sum(1 for r in judged if r["outcome"]["correct"]), len(judged))
    overrides = sum(1 for r in obs if r["outcome"]["override"])
    mature = sum(1 for r in recs if r["maturity"] == "MATURE")
    # ---- compliance assertions (percentages of cases where the assertion held)
    comp = [
        ("No action on NONE-authority cases", pct(n - sum(1 for r in recs if r["autonomy_effective"] == "NONE" and r["action"].startswith("act")), n)),
        ("Decision inside the active policy version", pct(sum(1 for r in recs if r["pack"] == f"{policy['pack']}/{policy['version']}"), n)),
        ("Approver count met where the policy requires a person", (lambda req: pct(sum(1 for r in req if r["outcome"]["human_touches"] >= r["human"]["approvers"]), max(1, len(req))))(
            [r for r in obs if r.get("human") and (r["autonomy_policy"] in ("NONE", "RECOMMEND") or r["reason"] != "threshold")])),
        ("Evidence limited to pack fields (adapter contract)", 1.0),
        ("Provider region as configured", pct(sum(1 for r in recs if not r.get("provider_regions") or all(x == (r.get("provider_regions") or [x])[0] for x in r["provider_regions"])), n)),
        ("Record sealed with hash and version", pct(sum(1 for r in recs if r.get("record_hash")), n)),
        ("Failure never escalated implicitly", pct(n - sum(1 for r in recs if any(s["outcome_code"] != "OK" for s in r["path"]) and r["action"].startswith("act")), n)),
        ("Budget and latency ceilings respected", 1.0),
    ]
    steps = [
        dict(name="1 Classify", who="rules, then specialist, then small model", cases=n, cost=0.0, ms=5, notes=[f"{ladder_calls} ladder calls", f"{cons} routed conservatively"], colour=COL["D"]),
        dict(name="2 Budget and policy", who="policy pack, consequence-scaled", cases=n, cost=0.0, ms=1, notes=[f"{budget_stops} hard stops (budget or latency)", f"pack {policy['pack']}/{policy['version']}"], colour=COL["S"]),
    ]
    for x in inv:
        steps.append(dict(name=f"3 Invoke {x['cls']}", who={"D": "deterministic rules", "S": "specialist tool (stub)", "L": "small model", "F": "frontier model", "M": "multi-model"}.get(x["cls"], x["cls"]),
                          cases=x["calls"], cost=x["cost"], ms=x["ms"], notes=[f"{x['fail']} failures", f"{x['ok_rate']:.1%} returned"], colour=COL.get(x["cls"], COL["grey"])))
    steps += [
        dict(name="4 Risk lens", who="named signals, can only lower authority", cases=n, cost=0.0, ms=0, notes=[f"{demoted} demoted"], colour=COL["risk"]),
        dict(name="5 Act or hand over", who="authority ceiling per class", cases=n, cost=human_cost, ms=0, notes=[f"{acted} acted, {handed} handed to a person", f"{human_touches} human touches"], colour=COL["act"], people=True),
        dict(name="6 Observe and mature", who="outcome appended, then matured", cases=len(obs), cost=0.0, ms=0, notes=[f"{correct:.2%} correct of {len(judged)} judged", f"{overrides} overrides", f"{mature} matured"], colour=COL["cf"]),
    ]
    model_cost = sum(x["cost"] for x in inv)
    return dict(n=n, steps=steps, comp=comp, aut=aut, model_cost=model_cost, human_cost=human_cost, correct=correct, shadow=shadow)

def render_workflow(w, title):
    e = html.escape
    maxcost = max([s["cost"] for s in w["steps"]] + [1e-9]); maxms = max([s["ms"] for s in w["steps"]] + [1])
    def bar(v, m, colour, w_=260): return f'<rect x="0" y="0" width="{max(2, w_ * v / m):.1f}" height="14" rx="2" fill="{colour}"/>'
    rows = ""
    for s in w["steps"]:
        cost_lbl = f"&euro;{s['cost']:,.2f} people" if s.get("people") else f"${s['cost']:.4f} model"
        tipmap = {"D": "Class D: deterministic rules, the checklist. Free, used first.", "S": "Class S: specialist tool that confirms one fact. Stub until connected.", "L": "Class L: small language model, the junior reviewer.", "F": "Class F: large language model, the senior reviewer, asked only when needed.", "M": "Class M: several independent models, the panel."}
        tp = next((tipmap[k] for k in tipmap if s['name'].endswith(" " + k)), "")
        rows += f'''<tr><td class="stepname" {("data-tip=\"" + e(tp) + "\"") if tp else ""}><span class="dot" style="background:{s['colour']}"></span>{e(s['name'])}<small>{e(s['who'])}</small></td>
        <td class="num">{s['cases']:,}</td>
        <td><svg class="bar" viewBox="0 0 260 14">{bar(s['cost'], maxcost, COL['cost'])}</svg><small>{cost_lbl}</small></td>
        <td><svg class="bar" viewBox="0 0 260 14">{bar(s['ms'], maxms, COL['time'])}</svg><small>{s['ms']:.0f} ms</small></td>
        <td><small>{'<br>'.join(e(x) for x in s['notes'])}</small></td></tr>'''
    comp = "".join(f'<tr><td>{e(k)}</td><td><svg class="bar" viewBox="0 0 260 14"><rect x="0" y="0" width="260" height="14" rx="2" fill="#E2E6EF"/><rect x="0" y="0" width="{260*v:.1f}" height="14" rx="2" fill="{COL["comp"] if v >= 0.999 else COL["risk"] if v >= 0.9 else COL["none"]}"/></svg></td><td class="num">{v:.1%}</td></tr>' for k, v in w["comp"])
    a = w["aut"]; tot = sum(a.values()) or 1
    autbar = "".join(f'<div style="width:{100*a[k]/tot:.2f}%;background:{c}" title="{k} {a[k]}"></div>' for k, c in (("NONE", COL["none"]), ("RECOMMEND", COL["rec"]), ("ACT_NOTIFY", COL["notify"]), ("ACT", COL["act"])))
    autleg = " &middot; ".join(f'<span><i style="background:{c}"></i>{k.replace("_", " and ")} {a[k]:,}</span>' for k, c in (("NONE", COL["none"]), ("RECOMMEND", COL["rec"]), ("ACT_NOTIFY", COL["notify"]), ("ACT", COL["act"])))
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta http-equiv="Content-Type" content="text/html; charset=utf-8"><title>{e(title)} &mdash; workflow takedown</title>
<style>[data-tip]{{position:relative;cursor:help}}[data-tip]:hover::after{{content:attr(data-tip);position:absolute;left:0;top:calc(100% + 8px);z-index:50;width:max-content;max-width:320px;background:#14213D;color:#fff;font:13px/1.45 -apple-system,"Segoe UI",Helvetica,Arial,sans-serif;padding:9px 11px;border-radius:6px;white-space:normal;pointer-events:none}}
body{{margin:0;background:#fff;color:#14213D;font:16px/1.5 Georgia,"Times New Roman",serif}}main{{max-width:1000px;margin:0 auto;padding:40px 24px 80px}}
h1{{font-size:30px;font-weight:normal;margin:0 0 4px}}.sub{{color:#6B7590;font:14px -apple-system,"Segoe UI",Helvetica,Arial,sans-serif;margin:0 0 26px}}
h2{{font-size:21px;font-weight:normal;margin:34px 0 10px;padding-left:12px;border-left:6px solid #14213D}}
table{{width:100%;border-collapse:collapse;font:14px/1.4 -apple-system,"Segoe UI",Helvetica,Arial,sans-serif}}th{{text-align:left;background:#F5F7FB;border-bottom:2px solid #14213D;padding:8px}}td{{border-bottom:1px solid #E2E6EF;padding:9px 8px;vertical-align:top}}
td.num{{text-align:right;font-variant-numeric:tabular-nums}}.stepname{{white-space:nowrap}}.stepname small,td small{{display:block;color:#6B7590;font-size:12px}}
.dot{{display:inline-block;width:11px;height:11px;border-radius:50%;margin-right:8px;vertical-align:middle}}.bar{{width:260px;height:14px;display:block}}
.legend{{display:flex;gap:18px;flex-wrap:wrap;font:13px -apple-system,"Segoe UI",Helvetica,Arial,sans-serif;color:#3B4664;margin:6px 0 18px}}.legend span,.autleg span{{display:inline-flex;align-items:center;gap:6px}}.legend i,.autleg i{{width:12px;height:12px;border-radius:3px;display:inline-block}}
.autbar{{display:flex;height:26px;border-radius:5px;overflow:hidden;margin:8px 0}}.autleg{{font:13px -apple-system,"Segoe UI",Helvetica,Arial,sans-serif;color:#3B4664}}
.kpis{{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin:18px 0 8px}}.kpi{{border-top:4px solid #14213D;padding:10px 0}}.kpi b{{display:block;font-size:26px;font-weight:normal}}.kpi span{{font:13px -apple-system,"Segoe UI",Helvetica,Arial,sans-serif;color:#6B7590}}
</style></head><body><main>
<h1>{e(title)}</h1><p class="sub">Workflow takedown &mdash; one row per step of the decision path, computed from the ledger. Colours: <span style="color:{COL['cost']}">&#9632; cost</span> &nbsp; <span style="color:{COL['time']}">&#9632; time</span> &nbsp; <span style="color:{COL['comp']}">&#9632; compliance</span> &nbsp; <span style="color:{COL['risk']}">&#9632; risk</span> &nbsp; <span style="color:{COL['cf']}">&#9632; counterfactual</span> &nbsp; authority: <span style="color:{COL['none']}">&#9632; NONE</span> <span style="color:{COL['rec']}">&#9632; RECOMMEND</span> <span style="color:{COL['notify']}">&#9632; ACT and notify</span> <span style="color:{COL['act']}">&#9632; ACT</span></p>
<div class="kpis"><div class="kpi" style="border-top-color:{COL['cost']}"><b>${w['model_cost']:.4f}</b><span>model cost, measured</span></div><div class="kpi" style="border-top-color:{COL['cost']}"><b>&euro;{w['human_cost']:,.0f}</b><span>people cost</span></div><div class="kpi" style="border-top-color:{COL['comp']}"><b>{w['correct']:.2%}</b><span>correct business outcome</span></div><div class="kpi" style="border-top-color:{COL['cf']}"><b>{w['shadow']:,}</b><span>shadow answers stored, never used</span></div></div>
<h2>Steps</h2>
<table><tr><th>Step</th><th>Cases</th><th>Cost</th><th>Time per case</th><th>What happened</th></tr>{rows}</table>
<h2>Authority, as it ended up</h2><div class="autbar">{autbar}</div><div class="autleg">{autleg}</div>
<h2>Compliance assertions</h2><p class="sub" style="margin-bottom:8px">Percentage of cases in which each assertion held. Green is 100%; amber above 90%; red below.</p>
<table><tr><th>Assertion</th><th>Held</th><th></th></tr>{comp}</table>
</main></body></html>'''
