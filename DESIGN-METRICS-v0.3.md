# EQAL — Design & Metrics v0.3 (aligned to runtime v0.7, 22 Sep 2026)

Supersedes the weekend "Design & Metrics v0.2 addendum", which was written against the frozen reference
simulator (02-reference, v0.3) rather than the deployed runtime. Same intent; this version says what already
exists in the runtime, what was added today, and what stays unbuilt until there is real data.

## 1. Status of the v0.2 items against the actual runtime

| v0.2 item | Runtime status (v0.7) |
|---|---|
| Shadow results persisted with a role | Done. `shadows[]` on every record: `position` = validation / below / above, class, verdict, confidence, cost; scored (`correct`) when the outcome is appended. The old single `shadow` field is kept for the attribution line. |
| Shadow for every eligible configuration above and below | Below: every lower class that ran before escalation (free — they ran anyway). Above: the next permitted class, run and stored, never used — **off by default** (it costs a call per case); `shadow_above: true` per class or `EQAL_SHADOW_ABOVE=1` on measurement runs. Its cost lands in the envelope as component `shadow`, ESTIMATED. |
| `capability_type` and `task_fingerprint` | Done. Pack- or class-level `capability_type` (default `document_judgement`); `task_fingerprint = exception_class:capability_type`. Metrics group by it. |
| Rename confidence → evidence score | Not renamed (breaks the frozen reference and the site). The record's `confidence` is the model's stated confidence; the threshold it is compared with is `budget.evidence`. The plain-words glossary says so. |
| Metrics MEAR/OIR/UIR/AIS/CPSO/IAR/escalation precision | Done: `GET /v1/metrics?basis=MATURE|OBSERVED`, per fingerprint, each with a label: SAR and CPSO OBSERVED; the shadow-derived ones COUNTERFACTUAL on matured outcomes, UNPROVEN otherwise. UIR reports its shadow-above coverage and is a lower bound when coverage < 1. |
| Real-time computation | Computed on request from the ledger; no stream. Maturity and reconciliation both append versions, so "real time" is "as of the latest version". Adequate until tens of thousands of decisions a day. |
| Decision templates / playbooks | Not built. The pack already is the template (path, ceiling, budget, validation, human rule). Automated authoring waits for real data. |
| Learning loop (promote / demote / drift) | Promotion proposals exist (`/v1/graduation`, human-approved). Demotion by evidence coverage exists in governance. Drift detection: not built; on synthetic data it would learn the generator. |
| Evidence Bench | `scripts/agreement_test.py` (same cases, same prompt, every configuration, Wilson intervals, agreement matrix). Enough until a second real provider is being evaluated. |
| Capability orchestration (FIG. 9, composite records) | Not built, and **not in the filed claims** — off the site, out of the dossier and out of the room until a second provisional or the non-provisional covers it. |
| Decision Cost Envelope, cost evidence classes, reconciliation | Done (v0.6.x): components with native meters and `quantity_source`; METERED / ALLOCATED / ESTIMATED / COUNTERFACTUAL; `POST /v1/reconcile`; attribution coverage on the manifest. |

## 2. The KPI set, as computed (per task fingerprint)

| KPI | Formula (fields on the record) | Label |
|---|---|---|
| SAR — sufficient allocation rate | correct / n | OBSERVED |
| CPSO — cost per successful outcome | (Σ intelligence cost + Σ human cost) / correct | OBSERVED |
| MEAR — minimum-effective allocation rate | 1 − (correct cases where a *below* shadow was right and met the class threshold) / correct | COUNTERFACTUAL (UNPROVEN until matured) |
| OIR — over-intelligence rate | cases where a below shadow was right and met the threshold / n | same |
| UIR — under-intelligence rate | wrong cases that escalated to the ceiling/budget, or wrong while an *above* shadow was right / n | same; lower bound unless shadow-above coverage = 1 |
| AIS — avoidable intelligence spend | Σ cost of classes above the cheapest sufficient one, over OIR cases | same |
| IAR — allocation regret (median, p90) | actual cost − cheapest sufficient class in hindsight | same |
| Escalation precision | escalations where the lower class was wrong and the higher right / escalations | same |

Reading rule: MEAR high and OIR low means the policy is spending what the evidence needs; OIR is the
input to the graduation proposal for a cheaper class; UIR is the input to a demotion; escalation
precision low with OIR low means the threshold is doing nothing and should be re-examined. None of
these is reported without its label.

## 3. Build order from here
1. Level 1 and Level 2 runs with `EQAL_SHADOW_ABOVE=1` so UIR and IAR are measured, not bounded.
2. Publish the KPI definitions (this table) as a page on eqal.net after Wharton, with dated numbers.
3. IP Master: add MEAR/OIR/UIR/AIS/CPSO/IAR/escalation precision as named instances of the filed
   ledger-derived reports; add capability orchestration to the list for the next filing.
4. Unbuilt until real data: template automation, drift detection, learning loop, capability records.
