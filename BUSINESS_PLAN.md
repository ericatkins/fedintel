# Fedintel — Business Plan

## The business in one paragraph

Every day, agencies post thousands of contract notices, and the ones where
software is the real work are buried under staffing recompetes, hardware buys,
and janitorial contracts. Small software firms either pay $10K–$40K/year for
enterprise tools built for capture teams at large primes (GovWin, Bloomberg
Government), or they lose hours skimming SAM.gov. Fedintel is the opinionated
middle: it finds software-solvable government problems, scores them against
*your* firm's profile, and puts the top leads in your inbox before your
coffee is cold.

## Business objectives

1. **Year 1:** Dogfood — win our own federal software work using Fedintel,
   producing case-study proof ("we found and won X via our own tool").
2. **Year 1–2:** 100 paying subscribers among small gov-focused software
   firms (Huntsville/DC/San Antonio/Colorado Springs corridors first).
3. **Year 2–3:** Expand to state and local sources; become the default
   opportunity radar for small SIs and 8(a)/SDVOSB software shops.

## Cost to run (monthly)

| Item | MVP (single user) | Growth (~100 subs) |
|---|---|---|
| Railway worker (cron) | $5 | $20 |
| Supabase Postgres | $0 (free tier) | $25 (Pro) |
| Resend email | $0 (free 3K/mo) | $20 (50K/mo) |
| Domain + Cloudflare Pages | $1 | $1 |
| LLM enrichment (score ≥60 only) | $3–10 | $50–150 |
| Monitoring (BetterStack/Sentry free tiers) | $0 | $0–26 |
| **Total** | **~$10–16/mo** | **~$120–240/mo** |

The economics are the point: gross margins above 90% at even modest scale,
because the pipeline is boring and the expensive part (AI) only runs on
plausible leads.

## Revenue model

**Subscriptions (core):**
- **Scout — $49/mo:** daily digest, one profile, federal only.
- **Pro — $149/mo:** instant alerts, lineage tracking ("your Sources Sought
  became an RFP"), AI summaries + fit analysis, saved searches, dashboard.
- **Team — $399/mo:** 5 seats, shared pipeline view, competitor/awardee
  intel, state + local sources, API access.
- Annual pricing at 2 months free. Anchor against GovWin's ~$1K+/mo:
  "90% of the signal at 10% of the price, tuned for software firms."

**Additional revenue ideas:**
- **Teaming marketplace:** connect primes needing niche software subs with
  Fedintel members (fee per introduction or premium listing) — the mockups'
  "Teaming Network" panel is this.
- **Capture-ready briefs:** $99–299 one-off deep-dive reports on a specific
  opportunity (agency spend history, incumbent, likely competitors).
- **Data/API licensing:** the scored, categorized, lineage-linked dataset is
  itself a product for proposal-tool vendors and market researchers.
- **White-label digests** for PTACs/APEX Accelerators, incubators, and
  economic-development orgs that advise small government contractors.
- **Success-fee pilot (careful, later):** optional % fee on won work sourced
  through Pro alerts — high trust required, but aligns us with wins.

## Pricing philosophy

Charge for **judgment, not data**. The notices are free and public; what
customers pay for is (1) not missing the right ones, (2) not wasting time on
the wrong ones, and (3) hearing about stage changes first. Price against the
value of one won contract — a single $250K award pays for decades of Pro.

## Break-even

At Pro-heavy mix (~$120 ARPU): growth-tier costs (~$250/mo incl. modest
founder time valuation at ~$2K) break even around **20 subscribers**. At 100
subscribers: ~$12K MRR against <$300 infra — a real business run by one or
two people.

## Moat, honestly

Data is public, so the moat is: scoring tuned by real win/loss feedback,
lineage history accumulated over years (you can't backfill "we watched this
pursuit evolve"), the platform-adapter library for state/local coverage, and
a brand that means "software opportunities, filtered by people who build
software." Speed and taste, compounded.

## Risks

- SAM.gov API rate limits / terms changes → mitigate with registered
  higher-limit keys and respectful pull patterns.
- Enterprise players moving down-market → stay 10x cheaper, 10x more focused.
- State/local coverage is grindy → the per-platform adapter strategy is the
  only sane path; treat it as a multi-year accretion, not a launch feature.
