# Public Beta Checklist

## Before inviting the first external user
- [ ] Deploy the five Railway services per deploy/README.md (web + ingest-daily +
      digests-hourly + enrich-nightly + awards-weekly) — the hourly digest worker
      is what makes local-morning delivery true
- [ ] `REQUIRE_EMAIL_VERIFICATION` left at default (on); web has RESEND_API_KEY
      so verification emails actually send
- [ ] `DB_POOL_MIN=1 DB_POOL_MAX=5` on web (workers default to 1 connection)
- [ ] Web boot runs `python -m scripts.migrate` (in the Dockerfile CMD) — verify
      schema_migrations shows 001–007 after first deploy
- [ ] `APP_SECRET` set (long random string) — signs action/unsubscribe/verify/reset tokens
- [ ] `EARLY_ACCESS_CODE` set — signup requires the invite code
- [ ] `COOKIE_SECURE` unset (defaults on) — HTTPS-only cookies + HSTS
- [ ] `DATABASE_URL` on the web service; `SAM_API_KEY`/`RESEND_API_KEY` ONLY on the worker
- [ ] `db/schema.sql` applied (or migrations 001–005 in order)
- [ ] `python -m scripts.backfill_office_keys` run once (if data predates migration 005)
- [ ] `INTEL_API_ENABLED` NOT set anywhere public (API is admin-only, off by default)
- [ ] Daily cron: `python -m src.main` (ingest → classify → per-org match → per-subscription digests)
- [ ] Weekly cron: enrichment + materialization jobs (see DEPLOYMENT.md)
- [ ] At least one admin: `update users set is_admin=true where email='...'`
- [ ] /healthz monitored; database backups scheduled and restore tested once

- [ ] Instant alerts: subscriptions opt in under Alerts; delivery is idempotent
      per (subscription, stage-transition event) and gated by plan entitlements
- [ ] Account deletion: /app/account — soft delete (login blocked, sessions
      revoked, digests stopped). Hard purge runbook: verify no other org members
      need the data, then `delete from users where id=... and deleted_at is not null`

## Verified security posture (tested in CI)
- Session cookies: HttpOnly, SameSite=Lax, Secure, hashed at rest, 14-day expiry
- CSRF required on every authenticated POST; token is session-bound
- Login rate limited (8/15min per email AND per IP); signup and reset also limited
- Digest links: GET shows confirmation only (scanner-safe); POST commits; tokens are
  HMAC-bound to opportunity+action+subscription+organization+expiry
- Password reset revokes all sessions; reset/verify tokens are purpose-bound
- Unsubscribe links signed and subscription-scoped; every digest has manage/why text
- Strict CSP with zero inline styles; HSTS in production; X-Frame-Options DENY
- Feedback, matches, watchlists, digests: organization-scoped with DB constraints

## Runbook: failed jobs
- **Failed digests**: /app/admin → "Digest sends not confirmed". Deliveries are unique
  per (subscription, day); rerunning `python -m src.main` retries unsent ones only.
- **Failed enrichments**: /app/admin lists them with the requeue command
  (`python -m src.tools.regenerate_dossier <opp_id>`).
- **Job history**: /app/admin → Job runs (from the `job_runs` table). A `failed`
  status includes the exception summary.

## Database migration guide
1. Back up: `pg_dump "$DATABASE_URL" > backup.sql`
2. Apply next migration: `psql "$DATABASE_URL" -f db/migrations/00N_*.sql`
3. Migration 005 only: run `python -m scripts.backfill_office_keys`
4. Verify: `python -m pytest tests/integration` with TEST_DATABASE_URL pointed
   at a COPY of production (never production itself).

## Onboarding the first customer
1. Send them the early-access code.
2. They sign up → onboarding walks them through the company profile.
3. Profile save triggers an immediate per-org rescore of the last 14 days.
4. They enable the daily digest under Alerts (their timezone, their min score).
5. Next pipeline run delivers their personalized digest with working action links.
