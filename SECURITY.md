# Security Policy — Fedintel

## Threat model in one line
All SAM.gov (and future state/city) data is hostile input; all secrets live in
environment variables; email HTML is the primary injection surface today.

## Non-negotiable rules
1. **HTML rendering:** only through Jinja `Environment` with autoescape ON
   (`src/digest.py`). Never `Template(...)` or `|safe` on untrusted fields —
   this applies to the current dashboard too.
2. **Links:** every outbound href passes `safety.safe_sam_url()` (HTTPS +
   SAM.gov host allowlist, fallback to notice-id URL, else no link).
3. **SQL:** parameterized queries only. No query text may be assembled from
   variables (static SQL enforced by import-time checks in `src/db.py`).
4. **Secrets:** never log request URLs (SAM key rides in the query string),
   auth headers, provider response bodies, or env values. All log output goes
   through `src/log.py`, which sanitizes URLs and known secret values.
5. **CI gates:** ruff (incl. bandit rules), bandit, pip-audit, and pytest all
   block merge. A finding may only be suppressed inline with a written
   justification, reviewed like any other code change.
6. **Tenant isolation (current dashboard):** browsers never receive broad DB
   credentials. Access goes through a backend API scoped by organization, or
   Supabase RLS policies keyed to `auth.uid()`.

## Reporting
Email the maintainer; do not open public issues for exploitable findings.


## Public-beta additions (verified by tests/test_security_features.py and
## tests/integration/test_postgres_integration.py)
- CSRF: session-derived token on every authenticated POST
- Rate limiting: login/signup/reset, per identifier AND per IP, DB-backed
- Email verification and password reset: purpose-bound HMAC tokens; reset
  revokes every session
- Digest actions: GET = confirmation page only (email-scanner safe);
  POST = commit; tokens bind opportunity+action+subscription+organization+expiry
- Tenant model: feedback/matches/deliveries carry organization_id with DB
  check constraints; org_id still derives only from the session or signed token
- Intelligence API: disabled unless INTEL_API_ENABLED=1 and then requires
  X-Admin-Token on every endpoint — never deploy publicly
- Audit log: login, logout, profile/alert updates, status changes, digest actions
