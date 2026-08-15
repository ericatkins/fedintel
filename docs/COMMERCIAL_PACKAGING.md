# Commercial Packaging Recommendation

How Fedintel's shipped capabilities map to plans people would rationally pay
for. Pricing figures are recommendations for validation, not commitments —
entitlement flags (`src/web/entitlements.py`) enforce boundaries server-side;
Stripe collection is the known missing piece.

## The value boundaries that matter

Customers pay along four real lines, and the packaging follows them rather
than arbitrary feature hiding:

1. **Discovery vs decision.** Seeing opportunities is table stakes; the
   decision stack, contract family, Buyer DNA, and proof mapping are what
   replace analyst hours.
2. **Before vs after SAM.gov.** The demand radar (forecasts, stated
   incumbents, anticipated dates) is worth a tier by itself to capture-led
   firms.
3. **Individual vs team.** Capture tasks, shared pipeline, and the private
   evidence library become multiplayer value.
4. **Contracts vs grants.** A distinct buyer (nonprofits, universities,
   EDOs) with distinct logic — never bundled as an afterthought.

## Recommended plans

| Plan | Anchor price (annual) | Who | What they get |
|---|---|---|---|
| **Scout** | $300–500 | solo consultant, first federal steps | discovery, saved views, daily digest, basic agency context, limited dossiers (no document intel, radar, or grants) |
| **Pro (Capture)** | $1,500–3,000 / seat | small-business capture lead | full dossiers: decision stack, executive brief, compliance matrix + proof mapping, contract family + recompete clock + vulnerability, Buyer DNA, competitive/teaming, funding ladder, demand radar, grants, capture tasks, printable reports |
| **Team** | $6,000–12,000 (5–10 seats) | mid-size BD team | everything in Pro plus multi-seat, shared watchlist/tasks, private evidence library at team scale, API access, audit history |
| **Grants** (add-on or standalone) | $500–1,500 | nonprofits, universities, EDOs | grants vertical: eligibility verdicts, forecasted NOFOs; grows into readiness + recipient intelligence as those ship |
| **Data/API** | $5,000+ | integrators, consultancies | API, bulk exports, webhooks (webhooks/bulk not yet built — do not sell before they exist) |

Current code maps Scout→`scout`, Pro→`pro`/`early_access`, Team→`team`.

## Why the entry plan is not crippled

Scout keeps real discovery (scored opportunities, digests, agency context) so
a user experiences the core loop; what it withholds is exactly the analyst
work (documents, history, radar) that justifies Pro. The upsell moment is
built into honest UI: a Scout user sees *that* a dossier exists, not a fake
degraded one.

## What must be true before charging

- Stripe (or invoicing) wired to `organizations.plan` — flags already
  enforce.
- Live adapters validated against SAM.gov/USAspending/Grants.gov/APFS from
  an unrestricted network, and the demo replaced by real coverage in the
  customer's NAICS.
- The `docs/KNOWN_LIMITATIONS.md` register shared with design partners —
  selling the honesty is the brand.

## Validation plan (next commercial step)

Five design partners (2 small software/cyber primes, 1 consultant, 1
nonprofit, 1 mid-size BD team) on free Pro/Team for 60 days; measure the
product-value metrics that matter: bid/no-bid decisions supported per month,
minutes-to-decision on the dossier (target < 15), % of pursued opportunities
where the family/incumbent read was verified correct, capture tasks created,
and renewal intent at anchor prices.
