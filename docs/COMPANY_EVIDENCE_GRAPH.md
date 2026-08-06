# Company Evidence Library and Requirement-to-Proof Mapping

## The evidence library (`company_projects`, migration 011)

Per-organization past-project records: customer agency/office, contract
identifier, prime/sub role, NAICS/PSC, period, value, scope, technologies,
outcomes, partners, and a **source note** (where the evidence is documented).
Managed on the profile page; strictly tenant-private (enforced in the store
layer and covered by unit + Postgres integration tests).

Projects power three surfaces:

1. **Past performance** and **buyer position** dimensions of the decision
   stack (NAICS-family and agency/office matches).
2. The **requirement-to-proof** column of the compliance matrix.
3. Future teaming/no-bid recommendations (gap severity → partner suggestion).

## Requirement-to-proof (`src/intel/proof.py`)

For each extracted document requirement:

- `profile` — vehicles/clearances/certs/set-asides are judged against profile
  fields by the qualification engine, not project evidence.
- `strong` — relevant project, recent (ended ≤ 3 years), category/agency match.
- `weak` — partial overlap; row says *"verify before claiming as past
  performance"*.
- `stale` — relevant project ended > 5 years ago; age is shown.
- `missing` — nothing recorded touches the requirement.

Honesty rules: token overlap is a **candidate**, never a certified proof; the
summary line reports coverage (`X/Y mappable requirements have candidate
evidence, N strong, M stale`) and its caveats; with no projects recorded,
every mappable row is `missing` and the UI says why.

## Privacy boundary

Public award history (global facts) and private company evidence never mix:
projects are keyed by `organization_id`, deleted with the org, and are never
readable cross-tenant. Decision stacks and proof mappings are computed at
read time per organization and never cached globally.
