# Fedintel — What It Is and How It Works

## The point

A federal contractor's hardest recurring question is not *"what was posted
today?"* — SAM.gov answers that for free. It is:

> **Should my company pursue this opportunity, and what evidence supports that
> decision?**

Answering it properly takes an analyst hours per opportunity: read the notice,
download the attachments, look up who has bought this work before, find who won
it last time and when that contract ends, judge whether this is a recompete or a
genuine new start, estimate the likely dollar value from comparable awards, check
whether you're even eligible to bid, and decide what to do next. Most small and
midsize contractors don't have that analyst. They subscribe to a keyword alert
service, drown in irrelevant notices, and miss the opportunities where they had
a real advantage.

**Fedintel compresses that research from hours to minutes, and shows its work.**

It ingests federal opportunities, enriches each one with historical award and
market intelligence, scores it against a specific company's capabilities and
eligibility, and presents a decision — pursue, track, team, or ignore — where
every claim is traceable to a stored public record.

### Who it is for

Small and midsize federal contractors, launching with the segment where the
scoring model is sharpest: **software, data, cyber, engineering, and technical
services firms**. Other verticals (construction, fiber/telecom, medical,
logistics) need different qualification logic and are planned as separately
tested vertical packs rather than being marketed prematurely.

### What makes it different

Not a prettier search page. Three things a keyword tool cannot do:

1. **Per-organization scoring.** The same solicitation scores differently for a
   software firm and a fiber contractor, driven by each org's own profile and
   its accumulated feedback.
2. **Document intelligence.** The requirements that decide bid/no-bid live in
   the PWS and SOW attachments, not the notice metadata. Fedintel reads them.
3. **Evidence discipline.** Every conclusion carries its confidence, its source
   record, and its caveat. The product would rather say *"no defensible basis
   yet"* than produce a confident-sounding number.

### The design principle everything follows

**Pipeline first, AI second.** All scoring, matching, and requirement extraction
is deterministic and explainable. The system works completely with AI disabled;
AI is an optional layer that may only summarize records already stored, and may
never invent an incumbent, a dollar figure, an awardee, or a funding link.

---

## Truthfulness rules

These are enforced in code, not just in copy, because a procurement decision
made on a fabricated detail is worse than no product at all.

| Rule | Why |
|---|---|
| Evidence tiers are never blurred | "No known incumbent" ≠ "no incumbent". "Budget-aligned" ≠ "funded". |
| Funding gets one of four exclusive labels | *Direct funding link found* / *Likely related funding account* / *Agency-level budget context* / *No public funding context found* — never "this is funded" without direct evidence. |
| District inflows are facts about the place | Appropriations are institutional. Only congressionally directed spending (CPF/earmarks) is attributed to a member. |
| Corporations cannot donate to federal candidates | FEC "employer" rows are aggregated *individual* contributions by reported employer; PAC receipts are separate and labeled as such. |
| No synthetic voter sentiment | No reliable public feed exists, so none is invented. A partisan lean is *computed* from imported election results, and the seat outlook says "context, not a forecast." |
| District confidence is explicit | Street-address geocode 90, city centroid 60 (cities span districts — badged "estimated"), state-only shows senators alone. |
| Silence is never capability | An empty company profile yields "unknown", never a disqualification. |
| Silence is never absence | No extracted requirement means no rule matched — not that the requirement isn't in the document. |
| Staff names are never fabricated | No free machine-readable staff directory exists; named staff only ever come from sourced imports. Until then, the UI names the *roles* to ask for. |

---

## Data sources

### Automated live APIs

| Source | What it provides | Cadence |
|---|---|---|
| **SAM.gov Opportunities** (`api.sam.gov/opportunities/v2`) | Notices, solicitation numbers, notice types, NAICS/PSC, set-asides, deadlines, place of performance, raw JSON retained | Daily |
| **SAM.gov Award Notices** (same API, `ptype=a`) | Award notices — strongest incumbent evidence | Weekly |
| **SAM.gov Attachments** (resource links per notice) | PWS / SOW / RFP / amendment / Q&A PDFs | Hourly |
| **SAM.gov Federal Hierarchy** (`federalorganizations/v1`) | Department / subtier / office codes for buying-office identity | On enrichment |
| **USAspending** (`api.usaspending.gov/api/v2`) | Award history, obligations, recipients, agency budgetary resources, federal accounts | Daily recent / weekly 5-year / monthly deep backfill |
| **USAspending Geography** (`spending_by_geography`) | Obligations by congressional district (place of performance), per FY, per agency | Weekly |
| **congress-legislators** (public domain dataset) | All 537 current members: chamber, district, party, DC office contacts, websites, committee assignments, FEC candidate IDs | Weekly |
| **US Census Geocoder** (free, no key) | Place of performance → congressional district | On enrichment |
| **FEC** (`api.open.fec.gov/v1`) | Contributions aggregated by reported employer, PAC/committee receipts, committee financial totals, candidate filings per seat | Monthly |
| **Grants.gov** (`api.grants.gov/v1/api`) | Grant opportunities and forecasts — the separate grants vertical | Weekly |
| **DHS APFS forecasts** (`apfs-cloud.dhs.gov/api`) | Agency procurement forecasts — pre-solicitation demand signals, stated incumbents, anticipated dates | Weekly |
| **Resend** | Outbound email only (digests, alerts, account mail) | Per send |

### Operator-imported sources

No free machine-readable feed exists for these, so they arrive as CSV imports
and **every row must carry a source** or it is rejected.

- **Agency procurement forecasts** — most agencies publish XLSX/CSV on OSDBU
  pages (acquisition.gov keeps the directory); rows without provenance are
  rejected. See `docs/DATA_SOURCES.md` for the column contract.
- **Congressional staff rosters** — House Statement of Disbursements, commercial
  directories. Stored with source and as-of date.
- **Election results** — MIT Election Lab exports, state Secretary-of-State
  results. General, primary, and runoff; powers the computed partisan lean.
- **Congressionally directed spending (CPF/earmarks)** — House and Senate
  Appropriations disclosure tables. The only member-attributable funding.

### Derived intelligence

Computed by Fedintel and stored across 47 tables — not fetched from anywhere:

Per-organization match scores · buyer-office profiles and behavior labels ·
vendor profiles (obligations, top agencies/NAICS/offices) · office market stats
(FY × NAICS × PSC: median/average/largest award, vendor concentration,
small-business and set-aside share, competed share) · incumbent analysis with
confidence bands · work-origin classification (new start / recompete /
modernization / O&M) · funding context labels · market size and trend ·
competition concentration · comparable-award value estimates (median + IQR,
outliers excluded) · opportunity lifecycle lineage and stage transitions ·
extracted document requirements (42 rules, 11 types) · bid-qualification
verdicts · computed partisan lean and seat outlook · learned organization
preference weights · job-run telemetry and audit log · **capture decision
stacks** (ten separately-assessed dimensions per org per opportunity) ·
**contract families** with recompete clocks and public-signal incumbent
vulnerability · **Buyer DNA** (peer-normalized office behavior labels) ·
**requirement-to-proof mappings** against each org's private project library ·
per-dossier evidence ledgers.

---

## Features

### Opportunity workflow
- Dense, sortable opportunities grid: per-org match score, recommendation,
  incumbent status, days left, user status
- Filters (keyword, score, notice type), **saved views** (plan-limited), CSV
  export hardened against spreadsheet formula injection
- **Demand radar**: agency procurement forecasts scored against your profile —
  forecasted requirements, stated incumbents, and anticipated solicitation
  dates months before SAM.gov; matched forecasts render as forecast lineage on
  the opportunity page
- **Grants** (separate vertical): Grants.gov opportunities with eligibility,
  assistance listings, award ranges, and cost sharing — contract scoring is
  never applied to grants, and keyword relevance is labeled as exactly that
- **Opportunity detail** — the most important page: a decision strip (verdict,
  deadline, comparable-award estimate, likely incumbent, top risk, next
  action, completeness), the **Capture Decision Stack** (ten separately
  assessed dimensions — see `docs/OPPORTUNITY_DOSSIER.md`), contract family
  timeline with recompete clock and incumbent vulnerability, Buyer DNA,
  amendment history, the full intelligence dossier, a per-dossier evidence
  ledger, and evidence drilldowns
- **Watchlist** with seven capture statuses: watching → researching → pursuing
  → submitted → won / lost / ignored
- Printable intelligence report (11–13 sections, depending on available intel)
- Terminal-style UX: ⌘K command palette, `j`/`k` navigation, dark-first, dense

### Document intelligence *(Pro / Team)*
- Automatic attachment fetch and text extraction, with **bounded OCR** for
  scanned PDFs (first 20 pages, hard timeouts; OCR-derived requirements are
  confidence-capped and method-tagged)
- **Compliance matrix** from 42 deterministic rules across 11 requirement
  types: clearances, contract vehicles, set-asides, certifications, wage
  regimes, evaluation approach, submission mechanics, personnel, place-of-work,
  deliverables, bonding
- Per-row **evidence drilldown**: the source sentence, page number, rule name,
  and confidence
- **Bid qualification verdict** with hard disqualifiers. Scores are *capped, not
  zeroed* — a barred opportunity stays visible because teaming is a real
  strategy:

  | Verdict | Meaning | Score cap |
  |---|---|---|
  | not eligible to prime | set-aside status you don't hold | 15 |
  | blocked unless teaming | vehicle/clearance gate, clearable with a partner | 55 |
  | qualified with gaps | obtainable or subcontractable gaps | none |
  | qualified — profile incomplete | profile doesn't list vehicles/clearances/certs | none |
  | qualified | profile satisfies every extracted requirement | none |

### Market and buyer intelligence
- **Agency / buyer-office** pages: FY × NAICS stats, recent awards, behavior
  labels, office-identity confidence *(all plans)*
- **Vendor intelligence**: obligations, top agencies/offices/NAICS, and a
  teaming-vs-competitor read *(Pro / Team)*
- **Market Intel**: category rollups (opportunity flow, award counts,
  obligations, average award value)
- **Reports hub**: daily opportunity brief, pursuit pipeline report — all
  generated from stored data, never live API calls

### Delegation and district intelligence *(Pro / Team)*
- **Congressional delegation on every opportunity**: both senators (state-certain)
  plus the House member (confidence-tiered), with committee-jurisdiction badges
  mapped across 12 agency groups
- **Legislator pages**: committee seats, sourced staff rosters (or the role
  playbook — MLA, appropriations LA, district director, grants coordinator,
  scheduler), FEC funding context, legislative calendar tie-ins
  (appropriations/CPF season, NDAA cycle, Q4 obligation push, CR risk), and
  FAR 3.104 engagement guardrails on every surface
- **District rankings** by federal inflow, per agency and fiscal year, joined to
  who represents each district
- **District profiles**: multi-year spending history, top agencies, computed
  partisan lean and margin trend, the member's primary history, seat outlook
  with reasons, and attributable CPF items

### Alerts and delivery
- **Daily digest at each subscriber's own local morning** (hourly worker plus a
  per-subscription delivery time — the promise is true by construction)
- **Instant stage-transition alerts** — the highest-value signal: *"the Sources
  Sought you tracked six months ago just became a solicitation"* *(not on Scout)*
- Signed, subscription-scoped unsubscribe and manage-preferences links
- **Scanner-safe action links**: GET renders a confirmation page and changes
  nothing; POST commits. Email security scanners that prefetch links are
  harmless.

### Account, organization, and admin
- Email/password auth with enforced verification, password reset (revoking all
  sessions), session management, logout-all, and account deletion
- Organization-scoped everything; company profile including the qualification
  fields (contract vehicles, clearances, certifications, set-aside eligibility)
- **Learned preferences**: feedback adjusts per-org feature weights — visible on
  the profile page, capped, and resettable
- **Admin ops**: job runs, failed enrichments, unsent digests, delivery stats,
  recent signups, feedback stats
- Four plans (Early Access / Scout / Pro / Team) with **server-side** entitlement
  enforcement — hiding a nav link is not access control

---

## Tech stack

Deliberately boring and cheap to operate. No Kubernetes, no message broker, no
frontend framework.

| Layer | Choice | Why |
|---|---|---|
| Language | Python 3.12 | One language across web and workers |
| Web | FastAPI + Uvicorn | Backend-for-frontend; the browser never touches the database |
| Templates | Jinja2, autoescape always on | Server-rendered HTML; no build step |
| Frontend | Vanilla JS + CSS (~3 files) | No React/bundler; the command palette and keyboard nav are a few hundred lines |
| Database | PostgreSQL (Supabase-compatible) | 47 tables, 13 ordered migrations, check constraints in the schema |
| DB access | `psycopg2` + `ThreadedConnectionPool` | Pooled, one transaction per operation; static/parameterized SQL only |
| Documents | `pypdf` | Pure-Python, parses structure only, never executes content |
| Email | Resend | With idempotency keys so retries can't double-send |
| Hosting | Railway (Docker), one image | Web service + 7 cron workers |
| CI | GitHub Actions | ruff, pytest, bandit, pip-audit, secret guard, and a real Postgres integration job |

**Scale of the codebase:** ~10,200 lines of application code, ~3,700 lines of
tests (258 unit + 27 Postgres integration), 26 templates, 5 runtime dependencies.

### Security posture

- Session cookies: HttpOnly, SameSite=Lax, Secure, **hashed at rest**, 14-day expiry
- Passwords: `scrypt` (n=2^14), 10-character minimum
- CSRF required on every authenticated POST, token derived from the session
- Rate limiting on login, signup, and reset — per identifier *and* per IP
- Strict CSP with **zero inline styles**; HSTS, `X-Frame-Options: DENY`,
  `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`,
  `Permissions-Policy`
- SSRF defense: outbound document fetches restricted to an HTTPS SAM.gov
  allowlist; 20 MB streamed cap enforced even when `content-length` lies;
  no redirects; sanitized filenames
- `organization_id` is derived **only** from the session or a signed token,
  never accepted from the client
- Static/parameterized SQL only; bandit suppressions require an inline
  written justification (currently two, both for the sandboxed OCR
  subprocess calls in `src/documents/ocr.py`)
- Logs redact secrets and query strings; API keys never reach the browser
- Optional intelligence API refuses to import unless explicitly enabled, and
  then demands an admin token on every endpoint

---

## How it works

### Architecture

```
                    ┌─────────────────────────────┐
   Browser ───────▶ │  Railway: FastAPI web       │
   (HTML only)      │  session auth, org scoping  │
                    └──────────────┬──────────────┘
                                   │ pooled, transactional
                    ┌──────────────▼──────────────┐
                    │   PostgreSQL (Supabase)     │
                    │   47 tables, 11 migrations  │
                    └──────────────▲──────────────┘
                                   │
        ┌──────────────────────────┴───────────────────────────┐
        │            Railway cron workers (same image)         │
        │  ingest-daily · digests-hourly · documents-hourly    │
        │  enrich-nightly · awards-weekly · civic-weekly       │
        └──────────────────────┬───────────────────────────────┘
                               │
              SAM.gov · USAspending · Census · FEC
              congress-legislators · Resend
```

The browser holds no database credentials and no API keys. Every user-facing
query is scoped server-side by the organization derived from the session.

### The daily pipeline

```
1. INGEST      SAM.gov search → normalize → upsert
               ├─ raw JSON retained for reprocessing
               ├─ content hash detects amendments
               └─ lineage recorded → stage transitions detected
2. CLASSIFY    deterministic global score per opportunity
3. MATCH       for each org profile: rescore, apply learned weights,
               apply document-based qualification caps
               → profile_opportunity_matches (per org)
4. ENRICH      async queue builds dossiers from cached award data
               (never live API calls at read time)
5. DOCUMENTS   fetch attachments → extract text → mine 42 rules
               → requirements with evidence
6. DELIVER     hourly: digests for subscribers whose local time has arrived,
               plus instant alerts for tracked-opportunity stage changes
```

Every job records to `job_runs` (started, finished, status, records
fetched/inserted/amended/failed, API calls, error summary) so nothing fails
silently, and the admin page surfaces failures.

### Why enrichment is asynchronous

Dossier building touches multiple external APIs and is far too slow for a page
load. Ingestion marks opportunities `pending`; a worker builds dossiers into
`opportunity_dossiers`; the web app reads only cached intelligence. A page
without a dossier honestly says *"dossier pending"* rather than blocking or
faking one.

### Global facts vs. per-organization judgments

The split that makes multi-tenancy correct:

- **Global** (computed once, shared): opportunities, classifications, award
  history, buyer offices, vendor profiles, dossiers, document requirements,
  delegation, district spending. These are facts about the world.
- **Per organization** (never shared): match scores, capture status, feedback,
  learned weights, saved views, subscriptions, digest deliveries, qualification
  verdicts. These are judgments about *your* company.

Tenant isolation is enforced in the store layer and proven by tests that assert
one organization cannot reach another's profile, watchlist, preferences, digest
history, or feedback.

### Request lifecycle (opportunity detail)

1. Session cookie → hashed lookup → user + `organization_id` + admin flag
2. Opportunity fetched with the per-org match score coalesced over the global
   classification
3. Cached dossier read (or "pending" shown)
4. Comparable-award estimate computed: median + interquartile range, excluding
   outliers above 3× the median
5. Document requirements read, then assessed against *this org's* profile into a
   qualification verdict
6. Delegation read from cache (resolving on first view)
7. Rendered server-side with autoescape; every external link passes the SAM.gov
   allowlist; CSRF token minted for the action forms

---

## Repository map

```
src/
  main.py            daily pipeline entrypoint
  run_digests.py     hourly delivery worker
  adapters/          8 external-source clients
  documents/         fetch · extract · requirements · qualification
  intel/             15 modules: dossier, incumbent, funding, market,
                     offices, vendors, delegation, district, value_estimate…
  web/               FastAPI app, store (Pg + Memory), auth, entitlements,
                     templates/ (26), static/ (3)
  classify.py  matching.py  learning.py  alerts.py  jobs.py  digest.py
db/
  schema.sql         full current schema
  migrations/        001 → 010, applied in order by scripts/migrate.py
deploy/railway/      8 service configs (1 web + 7 cron)
docs/                DEPLOYMENT · PUBLIC_BETA_CHECKLIST · DOCUMENT_INTEL ·
                     DELEGATION_INTEL · DISTRICT_INTEL · this file
tests/               258 unit tests + tests/integration (27, real Postgres)
```

## Running it

```bash
pip install -r requirements.txt -r requirements-api.txt
export DATABASE_URL=postgres://...        # the web app needs only this
python -m scripts.migrate                 # idempotent, tracked in schema_migrations
python -m scripts.seed_demo               # demo@fedintel.local / fedintel-demo-password
COOKIE_SECURE=0 uvicorn src.web.app:app --reload
```

Ingest credentials (`SAM_API_KEY`) belong to the workers only and are validated
at use time, so the web service never holds them. See `docs/DEPLOYMENT.md` for
the full environment-variable split and `docs/PUBLIC_BETA_CHECKLIST.md` before
inviting real users.

## What is deliberately not built yet

Named honestly, because a roadmap presented as shipped is its own kind of lie
(full register: `docs/KNOWN_LIMITATIONS.md`):

document-version diffing (notice-field amendment history and lineage-stage
requirement deltas ARE built) · contracting-officer extraction · protest/IG/
GAO signal ingestion · grant readiness scoring and recipient intelligence
(the grants foundation IS built) · appropriations-bill status in the funding
ladder · Stripe billing (entitlement flags are in place and enforced; only
payment collection is missing) · Sentry · state and local opportunity sources
(Bonfire/BidNet) · agency subtier splits (FBI within DOJ) · vertical packs
for non-technical industries · grounded AI summaries · win probability
(deliberately withheld until outcomes exist to calibrate it).
