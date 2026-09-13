# Phase 2 runbook — a URL other people can test (steps 0.5, 2.1, 2.2, 4.1 of the plan)

Order matters. About two hours end to end; nothing here needs me.

## A. Accounts (step 0.5) — 20 minutes
1. GitHub: create organisation `eqal-ai`. Create private repos `eqal-runtime`, `eqal-policy-packs`, `eqal-reference`
   and a repo `eqal.net` (private for now; it can stay private and still deploy Pages on a paid plan, or make it
   public once the filing receipt is in hand). Push each local folder:
       cd "$E/03-runtime" && git remote add origin git@github.com:eqal-ai/eqal-runtime.git && git push -u origin main
   (same for 02-reference, 04-policy-packs; for 05-site: git init, commit, push to eqal.net)
2. Railway: new account or new project `eqal` (not the ScanGuru project). Region: EU (Amsterdam).
3. Cloudflare: add zone `eqal.net`, move the nameservers at your registrar. Zero Trust -> Access is free for up to 50 users.
4. Mistral: create a second key `eqal-demo` with its own spend cap (EUR 25). Never reuse the laptop key.

## B. Railway API (step 2.2) — 40 minutes
1. Project `eqal` -> New -> Database -> PostgreSQL (EU). Note it injects DATABASE_URL.
2. New -> GitHub repo -> `eqal-ai/eqal-runtime`. Railway builds the Dockerfile.
3. Variables: paste `.env.example` and fill EQAL_GATEWAY_KEY (the demo key), EQAL_BOOTSTRAP_API_KEY (generate:
   `openssl rand -hex 24`), keep EQAL_DEMO_TENANT=demo and the three limits. No trailing whitespace.
4. Settings -> Networking -> custom domain `api.eqal.net`. Railway shows a CNAME target; add it in Cloudflare, proxied.
5. Check: `curl https://api.eqal.net/health/full` -> ok, provider GatewayProvider, limits shown.
6. Once, hardening (Railway -> Postgres -> Connect -> psql):
       CREATE ROLE eqal_app LOGIN PASSWORD '<pw>'; GRANT CONNECT ON DATABASE railway TO eqal_app;
       GRANT USAGE ON SCHEMA public TO eqal_app; GRANT SELECT, INSERT ON ALL TABLES IN SCHEMA public TO eqal_app;
       GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO eqal_app;
   then point DATABASE_URL at eqal_app. (Do this after the first boot created the tables. The demo reset endpoint
   needs DELETE: leave the demo instance on the owner role, and do the REVOKE on the first design-partner instance.)
7. Backups: Railway -> Postgres -> Backups -> daily. Sentry DSN if you have one. UptimeRobot on /health.
8. Seed the demo tenant from your laptop so visitors see a bill immediately:
       EQAL_URL=https://api.eqal.net EQAL_API_KEY=<demo key> python3 scripts/measure.py --cases cases.jsonl --limit 500

## C. The site (step 4.1) — 30 minutes
1. Push 05-site to `eqal-ai/eqal.net`; Settings -> Pages -> Deploy from branch main, root. Custom domain eqal.net.
2. Cloudflare DNS: apex A records 185.199.108.153 / .109.153 / .110.153 / .111.153, CNAME www -> eqal-ai.github.io, both proxied.
3. Cloudflare Zero Trust -> Access -> Applications -> Add: domain eqal.net (and www), policy Allow, include Emails
   ending in the cohort's domains or a list of addresses; login method One-time PIN. Now only invited people can open it.
   Do the same for api.eqal.net paths /v1/pnl/report and /v1/pnl/workflow if you want the reports gated too;
   otherwise they are protected by the key in the link.
4. On the site the runtime URL is pre-filled (https://api.eqal.net). Hand out the demo key with the invitation.
5. When the filing receipt exists: remove the Access policy, make the repo public if it was not, add "Patent pending".

## D. Docker locally (step 2.1) — optional, 15 minutes
   docker compose up --build   (Postgres + api on localhost:8000) — same seed/test commands as before.

## What visitors can do on the shared demo
Run the in-browser experiment (no server involved); connect to api.eqal.net with the demo key; upload an export-spec CSV
up to 3,000 rows and get the two reports; reset the demo ledger. The daily model-call budget (3,000 calls ~ EUR 1)
protects the Mistral cap; rules-only decisions continue when it is exhausted.
