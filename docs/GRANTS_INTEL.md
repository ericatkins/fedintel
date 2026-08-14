# Grants Intelligence (Foundation)

Grants are a related but analytically distinct vertical. They share agencies,
programs, and (eventually) the demand graph with contracts — but the decision
model is different: applicant-type eligibility, mission alignment, cost
sharing, review criteria, and organizational readiness, not incumbents,
set-asides, or price-to-win. **Contract scoring logic is never applied to
grant rows**, and the grants page says so.

## What ships in the foundation

- `grant_opportunities` table (migration 013): canonical grant records with
  assistance listings, eligibility, award floor/ceiling, expected awards,
  cost sharing, instrument, status (forecasted/posted/closed/archived), raw
  JSON retained, revision-detecting content hash.
- `adapters/grants_gov.py`: Grants.gov public JSON API — `search2` paging for
  discovery plus `fetchOpportunity` synopsis merge (award amounts, applicant
  types, cost sharing). Fixture-verified; the API host is blocked in
  restricted networks, so verify field names on the first production run
  (see docs/DATA_SOURCES.md). Refresh: `python -m src.enrich --refresh-grants`
  (failure-isolated job).
- `/app/grants`: a separate page listing posted + forecasted grants ordered
  by close date, with eligibility and assistance-listing detail drawers.
- **Honest relevance labeling**: the page shows which of your profile terms
  appear in the grant text, explicitly labeled as keyword matching and *not*
  an eligibility or readiness assessment.
- Entitlement flag `grants_intel` (off for Scout).

## Deliberately NOT built yet (see KNOWN_LIMITATIONS)

Grant readiness scoring (applicant type vs org profile, match/cost-share
feasibility, evidence readiness) · grantmaker profiles (award-size
distributions, repeat-recipient concentration, new-vs-continuation) ·
recipient intelligence from USAspending assistance awards · Single Audit
(Federal Audit Clearinghouse) integration · collaboration graph ·
post-award compliance calendar. Each requires its own source adapters and —
per the operating doctrine — will not be faked with contract logic in the
meantime.
