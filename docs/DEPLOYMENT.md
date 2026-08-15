# Fedintel Deployment Guide

Architecture: Option A — backend-for-frontend. The browser talks only to the
FastAPI web app; the web app talks to Postgres. No DB credentials or API keys
ever reach the client (enforced by design + CSP).

## Components

| Component | Where | Command |
|---|---|---|
| Postgres | Supabase (or any Postgres 14+) | run `db/schema.sql` (fresh) or migrations 001→004 (existing) |
| Daily pipeline | Railway cron 11:30 UTC | `python -m src.main` |
| Enrichment | Railway cron hourly | `python -m src.enrich` |
| SAM award refresh | Railway cron daily | `python -m src.enrich --refresh-sam-awards` |
| USAspending refresh | Railway cron weekly | `python -m src.enrich --refresh-awards` |
| Vendor profiles | Railway cron weekly | `python -m src.enrich --build-vendor-profiles` |
| Office market stats | Railway cron weekly | `python -m src.enrich --build-office-market-stats` |
| Demand signals (forecasts + grants + oversight links) | Railway cron weekly (`deploy/railway/demand-weekly.json`) | `python -m src.enrich --refresh-forecasts && --refresh-grants && --link-oversight` |
| Operator imports (as published) | manual | `--import-forecasts` / `--import-oversight` / `--import-protests` CSV files per docs/DATA_SOURCES.md |
| Web app | Railway service | `uvicorn src.web.app:app --host 0.0.0.0 --port $PORT` |

Install: `pip install -r requirements.txt -r requirements-api.txt`
(web app needs fastapi/uvicorn/python-multipart).

## Environment variables

Required: `SAM_API_KEY`, `DATABASE_URL`, `RESEND_API_KEY`, `DIGEST_FROM`, `DIGEST_TO`.
Web app + digest actions: `ACTION_BASE_URL` (the web app's public URL) and
`ACTION_SECRET` (long random string) — action buttons appear in the digest only
when both are set. Optional: `TIMEZONE` (default America/Chicago),
`MIN_DIGEST_SCORE`, `LOOKBACK_DAYS`, `ADMIN_TOKEN` (intelligence API admin),
`EARLY_ACCESS_CODE` (when set, signup requires this invite code),
`COOKIE_SECURE=0` only for local HTTP development.

Environment split (least privilege):

| Variable | Web service | Cron worker |
|---|---|---|
| DATABASE_URL | yes | yes |
| APP_SECRET (or ACTION_SECRET) | yes | yes |
| ACTION_BASE_URL | yes | yes |
| EARLY_ACCESS_CODE | yes | no |
| SAM_API_KEY | **no** | yes |
| RESEND_API_KEY | no (unless account emails) | yes |
| DIGEST_TO (dogfood only) | no | optional |

The web app boots with only DATABASE_URL; ingest settings are validated at use
time. Once any digest subscription exists, `python -m src.main` sends
per-subscription digests and ignores DIGEST_TO. The same run then delivers
instant stage-transition alerts to subscriptions that opted in (idempotent —
safe to rerun; each event alerts once per subscription).
Grant admin access (ops page at /app/admin) with:
`update users set is_admin=true where email='you@company.com';`

## First deploy checklist

1. Create the database; run `db/schema.sql`.
2. Deploy the web service; confirm `/healthz`.
3. Set `ACTION_BASE_URL` to the web service URL; redeploy the cron worker.
4. Seed demo data (optional): `python -m scripts.seed_demo`, then log in as
   `demo@fedintel.local` / `fedintel-demo-password` and delete the demo org
   before real launch.
5. Sign up your real account at `/signup`; complete onboarding.
6. Run `python -m src.main` once manually; confirm the digest arrives.
7. Run `python -m src.enrich` once; open an opportunity and confirm the dossier.

## Operations

- Failed digests: `select * from email_digests where send_status='failed'` —
  they retry on the next cron run automatically.
- Failed enrichments: `select id, title from opportunities where
  enrichment_status='failed'`; requeue with
  `python -m src.tools.regenerate_dossier <id>`.
- Sessions are DB-backed (`user_sessions`) and revocable; only sha256 hashes
  are stored.
- Security posture and non-negotiables: SECURITY.md. CI (ruff, pytest, bandit,
  pip-audit, secret guard) must stay green.
