# Contract Lineage, Recompete Clock, and Incumbent Vulnerability

`src/intel/contract_family.py` — reconstructs the contract history behind an
opportunity from linked public award records and renders it as a visual
timeline plus a recompete estimate.

## Family construction

- Links come from `intel/linking.py` (identifier, office, NAICS/PSC, scope,
  timing evidence per link).
- **Confirmed** members: shared solicitation/contract identifiers
  (`same_solicitation`, `same_contract`).
- **Inferred** members: similarity ≥ 55 links. When no confirmed member
  exists, the best inferred member is *presumed* predecessor — and labeled as
  inferred everywhere it appears.
- **Bridges**: awards ≤ 12 months to the same vendor starting within ~90 days
  of another family award's period end.

## Timeline

Merges notice-stage lineage rows (Sources Sought → RFP → …), family awards,
bridges, the current notice, and the estimated expiration marker. Confirmed
entries render solid; inferred entries render dashed with an explicit
`· inferred` suffix.

## Recompete clock

- Estimated expiration = the (confirmed, else presumed-predecessor) award's
  recorded period end.
- Window: engagement from expiration − 12 months; solicitation historically
  expected by expiration − 4 months.
- Assumptions are always stated: recorded period ends ignore unexercised
  options; USAspending lags actions by weeks to months.
- A passed expiration lowers confidence and adds a caveat (bridge/option/
  already-recompeted possibilities).

## Incumbent vulnerability — public signals only

Signals (each with named evidence): bridge extension · requirement-change
language in the notice · a set-aside on the new notice · low obligation rate
near end of period. Assessments use the fixed vocabulary:

`entrenched incumbent · incumbent favored but requirement changing ·
incumbent position uncertain · credible displacement opportunity ·
no defensible assessment`

Hard rules: the assessment never uses CPARS (not public) and says so; absence
of signals is never presented as incumbent strength; no members → "no
defensible assessment".
