# District Intelligence

Answers, feature by feature, with the honesty rules that make each one safe to
put in front of customers.

## "Track all federal money coming into the district" — YES, automated
`district_spending` aggregates USAspending obligations by PLACE OF PERFORMANCE
per congressional district, per fiscal year, per awarding agency (DoD, NASA,
DOJ, DHS, HHS, VA, DOE, GSA, DOT, Commerce, USDA, Interior + all-agency total).
Refresh: `python -m src.enrich --refresh-district-spending` (no key; 5-year
history by default). FBI note: the FBI is a DOJ subtier, so it rolls into the
DOJ row; subtier splits are a roadmap item.

## "Which reps bring in the most" — REFRAMED to stay truthful
Money flowing into a district is a fact about the place; appropriations are
institutional, so crediting general awards to a member is unsupportable. The
product therefore:
- RANKS districts by inflow (per agency, per FY) and shows who represents each
  one (/app/districts) — with the attribution note rendered on the page; and
- attributes ONLY congressionally directed spending (CPF/earmarks), which IS
  member-requested and published per member. Import committee disclosure
  tables with `--import-directed-spending cpf.csv`; items appear on the
  district page under "attributable".

## "Historically" — YES
Per-FY series (default 5 years) on every district page; the refresh job is
idempotent so re-runs update rather than duplicate. Redistricting caveat:
USAspending reports against the district boundaries in effect for the period.

## "How has the member fared in primaries / local races" — YES, via import
`election_results` stores general/primary/runoff rows with mandatory source
(MIT Election Lab exports map onto the CSV; state Secretary-of-State results
for primaries). The member's own primary history renders with vote share,
outcome, and source. `--import-election-results results.csv`.

## "Aggregate voter sentiment" — NO, and deliberately so
There is no reliable public machine-readable sentiment feed, and synthetic
sentiment would be fabrication. Shown instead, clearly labeled: partisan lean
COMPUTED from imported results (average winning margin, last 3 cycles, with
trend), the member's margin history, and FEC-observable campaign facts.

## "Do they have a shot next time" — CONTEXT, not a forecast
`seat_outlook()` is deterministic and fully reasoned: last margin + computed
lean + trend + incumbency + FEC cash-on-hand vs. best challenger receipts
(`--refresh-candidate-finance`). Output labels are deliberately hedged
(safe/likely/lean/competitive-CONTEXT) and every point carries its reason.
Use it for relationship planning: a competitive seat or open seat means
investing in committee and district-office staff relationships, not just the
member.

## What else (implemented)
Per-agency ranking tabs, district ↔ legislator cross-links, delegation panel
already on every opportunity, CPF as the attributable layer, statewide (Senate)
directed-spending items shown on district pages.

## What else (roadmap)
Subtier splits (FBI, NIH, FAA); recompete exposure by district (expiring
contracts → capture targets); district top-vendor tables; bill/report-language
tracking; House-disbursements staff ingestion; presidential-results overlay
for sharper lean; state-legislature layer via OpenStates.
