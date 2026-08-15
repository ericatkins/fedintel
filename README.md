# Fedintel

**New here? Read [docs/OVERVIEW.md](docs/OVERVIEW.md)** — what the product is for, every data source, every feature, the tech stack, and how the pipeline works.


**Federal demand intelligence and capture** — Fedintel ingests SAM.gov
opportunities, reconstructs the contract history and buyer behavior behind
each one, scores it against *your* company's profile and evidence library,
and renders a decision-grade dossier: an executive intelligence brief, a
ten-dimension capture decision stack, contract family + recompete clock,
incumbent vulnerability (protests, oversight findings, bridges), peer-
normalized Buyer DNA, competitive/teaming candidates, a funding ladder, an
OCR-capable compliance matrix mapped to your past-performance proof, and a
capture task plan — every claim traceable to a stored public record. A
demand radar surfaces agency forecasts before SAM.gov, and grants run as a
separate vertical. Daily digests and instant stage-transition alerts keep it
recurring.

Start here: [PROJECT_CONTINUITY.md](PROJECT_CONTINUITY.md) (strategy & architecture) ·
[BUSINESS_PLAN.md](BUSINESS_PLAN.md) · [BRAND.md](BRAND.md)

```
SAM.gov API → ingest → normalize → dedup/change-detect → classify → score → 6:30 AM digest
```

## Setup

### 1. Get your keys
- **SAM.gov API key:** sign in at sam.gov → Account Details → request/copy API key.
- **Supabase:** create a project at supabase.com → SQL Editor → paste and run
  `db/schema.sql` → Project Settings → Database → copy the connection string
  (use the *session pooler* URI for a cron worker).
- **Resend:** create account at resend.com, verify your sending domain, copy API key.
  (No domain yet? Resend's `onboarding@resend.dev` sender works for testing to your own address.)

### 2. Run locally
```bash
git clone <your-repo-url> && cd fedintel
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # fill in your keys
python -m src.main
```
First run pulls the last `LOOKBACK_DAYS` days, stores everything in Supabase,
and emails the digest (or stores it unsent if email isn't configured yet).

### 3. Push to GitHub
```bash
git add -A && git commit -m "Fedintel MVP: SAM.gov ingest, scoring, daily digest"
gh repo create fedintel --private --source . --push
# or create the repo on github.com and:
# git remote add origin git@github.com:YOURUSER/fedintel.git && git push -u origin main
```
Never commit `.env` — it's gitignored. Secrets live in Railway variables.

### 4. Deploy on Railway
1. railway.app → New Project → **Deploy from GitHub repo** → select `fedintel`.
2. Variables tab → add everything from your `.env`.
3. `railway.json` already sets the start command and cron
   (`30 11 * * *` = 6:30 AM Central during CDT; change to `30 12 * * *` for winter/CST,
   or just pick a UTC time you like).
4. Trigger a manual deploy/run once to verify logs show `[ingest]` and `[digest]`.

## Development
```bash
pip install -r requirements-dev.txt
pytest                        # 300+ tests incl. tenant isolation + golden gate
python -m src.tools.run_eval  # golden evaluation scorecard (release gate)
ruff check .                  # lint incl. bandit security rules
bandit -r src                 # security scan (justified #nosec only)
pip-audit -r requirements.txt
```
CI runs all of the above plus a committed-secrets guard on every push.
Personalize scoring: `cp company_profile.example.json company_profile.json` and edit.

## Tuning
- Score weights, keyword lists & component scoring: `src/classify.py`
- Company profile (capabilities, agencies, set-asides, boosts): `company_profile.json`
- NAICS targets: `src/config.py`
- Digest threshold & lookback: `.env` (`MIN_DIGEST_SCORE`, `LOOKBACK_DAYS`)

## Rate-limit note
Personal SAM.gov keys are heavily rate-limited. The adapter makes one request
per NAICS target per run (~8/day) and backs off on 429. If you need more,
request a higher-limit key or trim `NAICS_TARGETS`.

## Web app (authenticated, org-scoped)

Fedintel now ships a dark, terminal-style web app (`src/web/`): signup/login
(scrypt + DB-backed revocable sessions), onboarding company-profile editor,
command-center dashboard, dense opportunities grid (j/k navigation, Ctrl+K
command bar), opportunity detail with the full dossier and a capture-status
panel (watching → researching → pursuing → submitted → won/lost), watchlist,
alert preferences, and printable dossier reports. Digest action buttons now
land on a real handler (`/a/{id}/{action}`) with expiring HMAC tokens.

Tenant isolation is enforced server-side: org_id comes only from the session,
never from the client, and `tests/test_tenant_isolation.py` proves org A can't
read or write org B's profile, watchlist, subscriptions, or feedback.

New in this pass: Agencies and Vendors intelligence pages (from materialized
buyer_offices / office_market_stats / vendor_profiles), a Reports hub (daily
brief + pursuit-pipeline report, all from stored data), a lifecycle timeline
on every opportunity (Sources Sought → RFP with links), CSV export with
spreadsheet-formula-injection defense, an admin ops page (failed enrichments
and unsent digests; users.is_admin gated), and optional early-access gating
(set EARLY_ACCESS_CODE to require an invite code at signup).

```bash
# Prototype quickstart (local)
pip install -r requirements.txt -r requirements-api.txt
export DATABASE_URL=postgres://...   # web app needs only the database
psql "$DATABASE_URL" -f db/schema.sql
python -m scripts.seed_demo          # demo login: demo@fedintel.local / fedintel-demo-password
COOKIE_SECURE=0 uvicorn src.web.app:app --reload   # http://localhost:8000
```

The web app boots without SAM/Resend credentials — ingest-only settings are
validated when the pipeline actually runs, not at import.

## Intelligence pipeline (Opportunity Dossiers)

Every opportunity can carry an **Opportunity Intelligence Dossier**: buyer
office profile, last 10 *relevant* awards, incumbent analysis with evidence
and confidence, work-origin assessment (new start / modernization / recompete
/ O&M), funding context with strict truthfulness labels, market size & trend,
competition landscape, acquisition pattern, and a pursuit recommendation.
Every assertion carries a 0–100 confidence and a band ("strong signal",
"weak signal", ...). Inference is always labeled as inference.

```
ingest (daily, fast)              enrichment (async, separate cron)
SAM.gov opps → classify → digest  queue → resolve office → link awards →
                                  incumbent → work origin → funding →
                                  market/competition → recommendation →
                                  store dossier → next digest shows intel line
```

Jobs:
```bash
python -m src.main                      # daily: ingest + digest (never blocked by intel)
python -m src.enrich                    # hourly: build dossiers for pending opportunities
python -m src.enrich --refresh-awards            # weekly: USAspending history
python -m src.enrich --refresh-sam-awards        # daily: SAM award notices (incumbent evidence)
python -m src.enrich --build-vendor-profiles     # weekly: materialize vendor_profiles
python -m src.enrich --build-office-market-stats # weekly: materialize office_market_stats
python -m src.tools.regenerate_dossier <id> --show   # admin: rebuild + inspect evidence
```

Data sources: SAM.gov opportunities, SAM.gov award notices (`src/adapters/sam_awards.py`),
USAspending awards + budgetary resources + federal accounts (`src/adapters/usaspending.py`),
SAM.gov federal hierarchy (`src/adapters/fed_hierarchy.py`). Budget/OMB rows load into
`funding_accounts` and are always presented as context, never as proof of funding.

Optional intelligence API (stored dossiers only; enqueues enrichment when missing):
```bash
pip install -r requirements-api.txt
ADMIN_TOKEN=... uvicorn src.api:app        # /api/opportunities/{id}/dossier, /report, ...
```

## What's next (see PROJECT_CONTINUITY.md roadmap)
Instant alert delivery on stage changes → optional grounded AI summaries →
state/city coverage via per-platform adapters (Bonfire, BidNet, OpenGov).
