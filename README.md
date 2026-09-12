# EQAL runtime service v0.4 — aligned to the filed specification (plan step 1.3)

Replaces v0.3 entirely. Same deployment shape as before (FastAPI, Postgres, Docker,
Railway); different inside.

## What changed (why: spec paragraph)
- One record per case, versioned ([0039]–[0041], [0056]): `records` table, unique
  (tenant, case_id, version). Decision = v1; outcome = v2; maturity = v3. INSERT only.
- Spec vocabulary: NONE < RECOMMEND < ACT_NOTIFY < ACT; level ceiling {0,1,2,3,H}; D/S/L/F/M.
- Validation matrix before the budget gate; shadow_only invoked and stored, never used ([0029], [0034]).
- Consequence per case and consequence-relative budgets ([0028]); pack predicates evaluated
  by the adapter and passed as booleans in `flags` (the runtime is pack-neutral).
- Classification ladder with conservative routing ([0030]–[0031]); risk lens as min() ([0042]).
- Explainability: per-class eligibility with reason codes; invocation outcome codes with no
  implicit escalation on failure; declined paths; adapter ids; provider regions; tokens;
  harm class; reversibility; evidence hashes; pack lifecycle; record hash and prior hash.
- Outcome maturity PENDING → OBSERVED → MATURE (`POST /v1/mature`), spend by maturity, and
  the *unproven* line: attribution on OBSERVED-only outcomes is reported as unproven, never
  as waste or as saving ([0064]–[0066]).
- Observe-only mode: `observe_only: true` forces effective autonomy NONE and marks the record ([0076]).
- `GET /v1/governance`: assertions, not scores — actions on NONE-autonomy cases, inside active
  pack, approver counts met, overrides, invocation failures, declined paths, evidence coverage per class.

## API
    POST /v1/decide                    {case_id, input_refs, signals, flags, consequence, harm_class, reversible, evidence_hashes, observe_only}
    POST /v1/outcomes/{case_id}        {kind, value, correct, truth, realised_effect, human{touches,decision,override,approver_ids}, detail}
    POST /v1/mature?days=30            promotes OBSERVED -> MATURE by new versions
    GET  /v1/ledger?limit&human_only   latest version per case
    GET  /v1/ledger/{case_id}/versions all versions
    GET  /v1/pnl · GET /v1/pnl/report · GET /v1/governance · GET /v1/policy · /health · /health/full

## Run locally (step 2.1)
    docker compose up --build
    EQAL_URL=http://localhost:8000 EQAL_API_KEY=demo-key python3 scripts/seed_demo.py --n 2000 --seed 11
    curl -H "X-API-Key: demo-key" localhost:8000/v1/pnl/report > report.html
    curl -H "X-API-Key: demo-key" localhost:8000/v1/governance

Expected on seed 11 (simulated provider): ~90% touchless, 99.9% correct, 0 unauthorised,
~57 conservatively routed, attribution "justified" on OBSERVED outcomes.

## Providers
- `simulated` — AP-only synthetic behaviour, reproduces the frozen reference. Do not use with the SCM pack.
- `gateway` — D and S from adapter fields in `signals` (rule_pass, rule_confidence, verified,
  rule_candidates, classifier_candidates …); L/F/M via an OpenAI-compatible endpoint, one alias
  per class (`EQAL_MODEL_L/F/M`), EU region. Failures return outcome codes, never escalate.
  The SCM pack loads and decides under `gateway` (tested with an unreachable gateway: the F
  call records `ERROR` and the case goes to the human rule).

## Production hardening (step 2.2)
Once, as the DB owner: `REVOKE UPDATE, DELETE ON records FROM <app role>;`

## v0.4.1 — Phase 3 preparation
- `scripts/retro_ingest.py` — retrospective / observe-only ingestion of `invoices.csv` in the
  historical-export format ([0076]). Booleans computed adapter-side; truth derived from the
  owner's resolution codes; human cost from their rates and minutes per touch. Under
  `EQAL_PROVIDER=simulated` it is a pipeline test; under `gateway` it is the read-out.
- `GET /v1/graduation?min_mature=200&basis=MATURE` — autonomy-graduation proposals ([0063],
  [0067]): a DRAFT pack diff with evidence attached when a class meets its own threshold on
  enough matured outcomes. Proposed, never applied.
- P&L for observe-only runs shows touchless *as it actually was* (owner data) and touchless
  *the policy would have allowed* (counterfactual) side by side.
- `gateway/` — LiteLLM service definition and alias config for step 3.1 (fill the EU endpoints
  and keys; the runtime only ever sees eqal-L / eqal-F / eqal-M).
- `outcome.human.human_cost_override` — lets an adapter pass the owner's actual cost per case.

Retrospective run:
    docker compose up --build
    EQAL_URL=http://localhost:8000 EQAL_API_KEY=<key> python3 scripts/retro_ingest.py --csv invoices.csv --rate-clerk 48 --rate-supervisor 75 --rate-treasury 90 --minutes 6
    curl -H "X-API-Key: <key>" -X POST "localhost:8000/v1/mature?days=0"     # historical outcomes are already mature
    curl -H "X-API-Key: <key>" localhost:8000/v1/pnl/report > readout.html
    curl -H "X-API-Key: <key>" "localhost:8000/v1/graduation?min_mature=200"
