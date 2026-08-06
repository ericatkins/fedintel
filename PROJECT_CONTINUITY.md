# PROJECT CONTINUITY — Fedintel

> Read this first. It is the source of truth for what we are building, why,
> and the architectural strategy every future change must respect.
> If you are an engineer (human or AI) picking this project up cold, this
> file plus README.md should be enough to continue the work.

## What we are building

Fedintel is a procurement intelligence service. It watches government
contracting sources — starting with SAM.gov — for opportunities where
**software is the key effort**, then classifies, scores, and delivers them
as a daily morning email digest (and eventually a dashboard + instant alerts).

The founding user is a builder in the Huntsville / Redstone Arsenal orbit who
wants to **build modern software for the government and replace legacy
systems** — not do staffing, not sell hardware. Every scoring decision
reflects that intent.

## The core strategic bets

1. **Pipeline first, AI second.** This is a reliable procurement data
   pipeline that happens to use AI, not an "AI agent." Deterministic rules
   classify everything; LLM enrichment is a later second pass applied only
   to plausible matches. Trust the ingest before you decorate it.
2. **Source adapter pattern.** SAM.gov is adapter #1, not the architecture.
   Every source (federal, state, city, vendor platforms like Bonfire/BidNet/
   OpenGov) maps into one normalized opportunity schema. Downstream code —
   dedup, classify, score, notify — never knows where a record came from.
   Adding a jurisdiction costs one adapter, never a new pipeline.
3. **Build adapters per platform, not per state.** Most states/cities run on
   a handful of procurement platforms. One Bonfire adapter unlocks dozens of
   jurisdictions.
4. **Lifecycle is first-class.** Sources Sought → RFI → Draft RFP → RFP →
   Amendment → Award are stages of one pursuit, linked by solicitation
   number in `opportunity_lineage`. The highest-value alert we will ever
   send is "the Sources Sought you scored 92 just became an RFP."
5. **Store raw JSON forever.** Scoring will improve; old notices get
   reclassified. Never throw away source data.
6. **Track changes, not just newness.** Amendments matter. `change_events`
   records new/amended/stage-change and powers future instant alerts.

## Architecture (current)

```
SAM.gov API (v2 search)
  → src/adapters/sam_gov.py     (adapter: fetch raw records)
  → src/normalize.py            (map to common schema + content hash)
  → src/db.py                   (upsert, dedup, change events, lineage)
  → src/classify.py             (rules: keywords + NAICS + notice type + geo)
  → src/digest.py               (HTML email render)
  → src/send_email.py           (Resend)
```

Hosting: **Railway** (Python worker on cron, 11:30 UTC / 6:30 AM Central) +
**Supabase** (Postgres) + **Resend** (email). Dashboard later on
the authenticated FastAPI web app (backend-for-frontend); the browser never holds database credentials.

## Scoring philosophy (0–100)

Positive: software keywords in title (+25), software NAICS (+20),
legacy-modernization language (+15), workflow/tooling problem (+10),
early-stage notice type (+10), small-business set-aside (+10),
Huntsville/Redstone/DoD (+10), integration/API work (+8), deadline >7 days (+5).
Negative: award notices (−25), staffing body-shops (−20), hardware-only (−20),
incumbent-favored recompetes (−15). Clamped 0–100. Tune in `src/classify.py`.

## Roadmap (in order)

1. ✅ MVP: SAM.gov ingest → score → daily digest (this repo)
1b. ✅ Hardening pass: autoescaped email rendering, URL allowlisting,
    send-state tracking, timezone correctness, batch-resilient ingest,
    component scoring + company profiles, 54-test suite, security CI
    (see SECURITY.md — its rules bind all future code, dashboard included)
1c. ✅ Market Intelligence layer: per-opportunity dossiers (buyer profile,
    last-10-relevant awards, incumbent analysis, work origin, funding context,
    market trend, competition, pursuit recommendation) built by src/intel/*,
    enriched asynchronously (src/enrich.py) so ingest/digest never block on
    award or budget APIs. Truthfulness rules are code: confidence bands on
    every claim (src/intel/confidence.py), 'confirmed incumbent' only on
    identifier match, budget context never presented as funding.
1d. ✅ Public MVP foundation: authenticated web app (backend-for-frontend,
    Option A), org-scoped store layer with tenant-isolation tests, digest
    action-link handler with expiring HMAC tokens, capture-pipeline statuses,
    stage-transition lineage detection, SAM award-notice refresh job, vendor
    profile + office market stats materialization, office identity fix
    (buying office vs mailing city), hierarchy enrichment, deployment guide,
    demo seed script. Terminal UX v1: dark shell, command palette, j/k nav.
1e. ✅ Working prototype pass: Agencies/Vendors intelligence pages, Reports hub
    (daily brief + pursuit pipeline from stored data), lifecycle timeline UI on
    opportunity detail, CSV export (formula-injection safe), admin ops page
    (is_admin gated; failed enrichments + unsent digests), EARLY_ACCESS_CODE
    signup gating, config made boot-safe (require() at use time — web app runs
    with only DATABASE_URL). Live smoke: every route 200 behind auth, 303 to
    /login without a session.
1f. ✅ Public-beta pass (this session): org-scoped feedback + per-org
    profile_opportunity_matches (migration 005) with matching service and
    per-subscription digest engine (org-scored rows, signed unsubscribe/manage
    footer, digest_deliveries unique per sub/day, org+sub-bound action tokens);
    action links GET=confirm POST=commit (email-scanner safe); CSRF on all
    authed POSTs; login/signup/reset rate limiting; email verification +
    password reset (revokes sessions) + logout-all + audit_log; intel API
    admin-only and disabled by default; buyer_offices office_key dedup upsert
    + backfill script; office_market_stats null-safe generated-key identity +
    psc/category/small-biz fields; lineage unique + amendment-driven stage
    transitions; DB check constraints; CSP-clean (zero inline styles, static
    report.css) + HSTS + Permissions-Policy; Market Intel page; expanded admin
    (job runs, deliveries, signups, feedback); job_runs observability;
    organizations.plan entitlement column; Postgres integration suite (9 tests)
    run against a real database in CI and locally; seed adds subscription +
    per-org matches; Decimal-safe dossier JSON (real bug found by real-DB run).
1g. ✅ Ship pass: instant stage-transition alerts (src/alerts.py — idempotent
    per subscription+event via instant_alert_deliveries, entitlement-gated,
    wired into the daily pipeline after digests); account deletion path
    (/app/account, soft delete blocks login + revokes sessions + stops digests,
    users.deleted_at, migration 006); saved views (reuses saved_searches with
    unique org+name, plan-limited, org-scoped load/delete, view chips UI);
    dashboard decision panels (closing soon, org stage transitions, pursuit
    pipeline, last digest delivery); opportunity-detail decision strip
    (verdict/value range from similar awards/incumbent/top risk/next action —
    all from the stored dossier); entitlements module (PLAN_FLAGS, no pricing);
    tz-flake fix in integration test (digest dates computed in subscription tz).
    11 Postgres integration tests + 140 unit tests.
1h. ✅ Launch-hardening pass (reviewer P0s): dashboard.html malformation fixed
    (panel grid had been injected into the title block AND duplicated);
    PgStore rebuilt on ThreadedConnectionPool with one transaction per
    operation (signup/subscription-replace/deletion now atomic; pool queues
    briefly under burst instead of 500ing — found live with 8 parallel
    requests); Resend Idempotency-Keys on digests (fedintel-digest:sub:date)
    and instant alerts; hourly digest worker src/run_digests.py +
    delivery_hour_local/minute on subscriptions (migration 007) makes "your
    local morning" TRUE; email verification ENFORCED at login
    (REQUIRE_EMAIL_VERIFICATION default on; resend flow; signup keeps a grace
    session for onboarding); deterministic feedback learning (src/learning.py:
    feedback → org feature weights capped ±10 in DB, ±15 applied at scoring,
    reasons annotated, visible + resettable on profile) — "improves your
    future matches" is now true; server-side entitlement gates on
    vendors/agencies/reports/CSV; comparable-award estimate = median + IQR
    with 3×-median outlier exclusion; Dockerfile + five Railway service
    configs + deploy/README + scripts/migrate.py (schema_migrations table).
    150 unit + 15 Postgres integration tests, all verified live on a clean DB.
1i. ✅ Delegation intelligence (migration 008): place of performance →
    senators (state, 95) + House member (Census-geocoder tiered: address 90 /
    city 60 with "district estimated" badge / state-only = senators alone);
    committee seats filtered to buying-agency jurisdiction
    (AGENCY_COMMITTEE_MAP + always-relevant Small Business, subcommittees
    deduped to parent); legislator drilldown page (committees, sourced staff
    rosters via --import-staff CSV — NO free staff source, so guidance shows
    the role playbook until imported; FEC funding aggregates with truthful
    labels — employer rows are INDIVIDUAL contributions aggregated by
    employer, never "company donated"; PAC receipts separate); legislative
    calendar tie-ins (approps/CPF season, NDAA cycle, Q4 push, CR risk);
    FAR 3.104 engagement-guardrail note on every surface; delegation panel on
    opportunity detail + report section; entitlement flag delegation_intel
    (scout excluded, 403 verified live); adapters: congress-legislators
    gh-pages JSON (public domain — REAL 537-member dataset loaded and
    verified live in Postgres: Huntsville DoD opp → Tuberville/SASC,
    Britt/Approps, Strong AL-5), Census geocoder, FEC by_employer +
    schedule_a; enrichment queue upgrades matches with geocoder; jobs
    --refresh-legislators / --refresh-legislator-funding / --import-staff;
    civic-weekly Railway service. 159 unit + 17 integration tests.
1j. ✅ District intelligence (migration 009): district_spending (USAspending
    spending_by_geography by place of performance, FY × agency × district,
    5-yr history, idempotent refresh) with /app/districts rankings joined to
    real reps + per-agency filter; /app/districts/{st}/{cd} profile (FY
    series, top agencies, rep card); ATTRIBUTION DISCIPLINE everywhere —
    inflows describe the place, only congressionally-directed spending
    (directed_spending, CSV import from approps disclosure tables) is
    member-attributable; election_results import (mandatory source,
    district_key generated column for statewide uniqueness) → computed
    partisan lean (3-cycle winning margins + trend) + member primary history;
    candidate_finance (FEC totals + challenger filings) → seat_outlook():
    deterministic reasoned labels (safe/likely/lean/competitive-CONTEXT,
    "context not a forecast"); SENTIMENT_NOTE: we do NOT scrape/estimate
    sentiment — computed lean + FEC facts instead; adapters usaspending_geo
    (shape-code parser) + fec committee_totals/district_candidates; enrich
    flags --refresh-district-spending/--refresh-candidate-finance/
    --import-election-results/--import-directed-spending; civic-weekly cron
    extended; entitlement delegation_intel gates it. Live-verified: rankings
    with real 537-member join, AL-5 profile (29.6-pt computed lean, sourced
    primary history, safe-context outlook with reasons, CPF items). 167 unit
    + 20 integration tests. FBI = DOJ subtier (subtier splits on roadmap).
1k. ✅ Document intelligence (migration 010) — the reviewer's #1 differentiator:
    opportunity_documents + document_requirements (evidence-bearing: quote,
    page, rule name, confidence; doc_key generated column for null-safe
    uniqueness); src/documents/ = fetch.py (SECURITY BOUNDARY: SAM-only SSRF
    allowlist, 20MB streamed cap enforced past a lying content-length, no
    redirects, sanitized filenames, key never logged), extract.py (pypdf,
    400-page/1.2M-char bounds, honest 'unsupported' for scanned image PDFs),
    requirements.py (~45 named regex rules → clearances/vehicles/set-asides/
    certifications/wage/evaluation/submission/personnel/place/deliverables/
    bonding, with tier suppression so TS-SCI hides bare Secret and CMMC L3
    hides bare CMMC), qualification.py (per-org verdicts: not-eligible-to-prime
    /blocked-unless-teaming/gap/unknown; score CAPPED not zeroed at 15/55 so
    teaming stays visible; empty profile → 'unknown', never punished);
    db_documents.py queue/process pipeline; wired into matching (per-org caps)
    + detail-page compliance matrix with <details> evidence drilldown +
    verdict banner + report section; profile gains contract_vehicles/
    clearances/certifications; entitlement document_intel (scout excluded);
    documents-hourly Railway service. Verified on a REAL generated 3-page
    solicitation PDF: 16 requirements with correct page attribution, live UI
    showed 'blocked unless teaming' with met/blocking/gap statuses.
    FOUND+FIXED live: log redaction blind-replaced short secret values
    ('extracted' → 'e[SAM_API_KEY-redacted]tracted'); now bounded to
    credential-length (>=8) values with a regression test. Bandit false
    positive on CLEARANCE_RANK resolved by deriving the map (zero
    suppressions preserved). 181 unit + 23 integration tests.
ROADMAP (reviewer sprints 2-4, deliberate deferrals): contracting-officer extraction + buyer engagement intel,
    hard disqualifiers in the qualification model (vehicles / clearances /
    set-aside eligibility), Stripe, Sentry, market-page drilldowns, ROI
    dashboard, vertical packs (launch software/technical-services first).
    Pricing is a business decision: reviewer suggests $29/$79/$199 vs the
    plan's $49/$149/$399 given HigherGov/GovTribe positioning.
3. LLM second pass: AI summaries + "why this is a good fit" on score ≥ 60
4. Dashboard: DONE — authenticated FastAPI app (src/web/)
5. First vendor-platform adapter (Bonfire or BidNet) → states + cities in bulk
6. Multi-user: Supabase auth, per-user profiles/alert rules → subscription product

## Intelligence-layer rules (in addition to everything below)

- Dossier logic lives in pure functions (src/intel/*) over plain dicts:
  testable without DB or network. Persistence is db_intel.py; orchestration
  is enrich.py. Keep it that way.
- Deterministic first: similarity is token cosine + identifier matching.
  Embeddings/AI may REPLACE the semantic slots later but the dossier must
  always build with AI disabled, and AI may never fabricate incumbents,
  values, offices, budgets, or award history — all AI claims must cite
  stored source record IDs.
- Never blur evidence tiers: confirmed fact > strong signal > weak signal >
  inferred likelihood > unavailable. "No known incumbent found" is not
  "there is no incumbent." "Budget-aligned" is not "funded."

## Rules for anyone touching this code

- Never scrape SAM.gov's website; use the API. Scrape state/city portals
  politely only where no API/feed exists.
- Any new source = new file in `src/adapters/` that yields raw dicts + a
  normalizer function. Nothing else changes.
- Keep the classifier deterministic and testable. AI augments, never replaces.
- The digest must send even when the AI layer fails. Reliability > cleverness.
- SECURITY.md rules are architecture, not suggestions: autoescape-only HTML,
  safe_sam_url on every link, parameterized/static SQL, sanitized structured
  logs, and no browser ever holding broad DB credentials.
- A digest counts as sent only when the provider confirms (sent_at). Failed
  sends persist with error state and are retried on the next cron run.
