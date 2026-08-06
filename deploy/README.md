# Deploying Fedintel on Railway

One Docker image, five Railway services (same repo, different config paths —
set "Config file path" per service in Railway settings):

| Service | Config | Schedule | Env needed |
|---|---|---|---|
| web | deploy/railway/web.json | always on | DATABASE_URL, APP_SECRET, ACTION_BASE_URL, EARLY_ACCESS_CODE, RESEND_API_KEY (account emails) |
| ingest-daily | deploy/railway/ingest-daily.json | 10:15 UTC daily | + SAM_API_KEY |
| digests-hourly | deploy/railway/digests-hourly.json | :05 hourly | DATABASE_URL, APP_SECRET, ACTION_BASE_URL, RESEND_API_KEY |
| enrich-nightly | deploy/railway/enrich-nightly.json | 04:45 UTC daily | DATABASE_URL, SAM_API_KEY |
| awards-weekly | deploy/railway/awards-weekly.json | Sun 06:00 UTC | DATABASE_URL, SAM_API_KEY |
| civic-weekly | deploy/railway/civic-weekly.json | Sun 07:00 UTC | DATABASE_URL, FEC_API_KEY |
| documents-hourly | deploy/railway/documents-hourly.json | :35 hourly | DATABASE_URL, SAM_API_KEY |

civic-weekly also refreshes district spending (USAspending, 5-year history) and
candidate finance; election results and CPF tables are operator CSV imports.

Web runs `scripts/migrate.py` on every boot (idempotent). Set DB_POOL_MIN=1,
DB_POOL_MAX=5 on web; workers use their own single connection.

The hourly digest worker is what makes "6:30 AM in your timezone" true: each
subscription stores delivery_hour_local/delivery_minute_local, the worker runs
every hour, and the unique (subscription, day) delivery row guarantees exactly
one send per local day. Resend Idempotency-Keys make provider retries safe.
