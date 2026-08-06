# The Opportunity Dossier

The individual opportunity page is the product's primary value surface: it must
let a capture manager make a pursue / team / track / no-bid decision in
minutes, with every material claim traceable to a stored public record.

## Above the fold: decision strip

Seven cells, rendered before anything else:

verdict (from the decision stack) · deadline + days remaining · comparable
award estimate (median + IQR, outliers excluded) · likely incumbent ·
top risk · recommended next action · dossier completeness %.

## The Capture Decision Stack (`src/intel/decision.py`)

The single match score is **not** the decision. Ten dimensions are assessed
separately, each with rating (`strong / moderate / weak / blocked / unknown`),
evidence list, confidence, materiality (`gate / high / medium / low`),
unknowns, and a mitigation when the rating is a problem:

1. **Eligibility** — from the document-derived qualification verdict (gate)
2. **Capability fit** — the deterministic per-org match score and reasons
3. **Past performance** — from the org's recorded project library
4. **Buyer position** — recorded projects with this office/agency
5. **Incumbent position** — from the incumbent analysis tiers
6. **Competitive position** — vendor landscape shape at this buyer
7. **Economic attractiveness** — comparable-award range × market trend
8. **Strategic value** — learned org preference weights for this agency/NAICS
9. **Execution readiness** — days remaining, document volume, requirement load
10. **Intelligence completeness** — what enrichment has and hasn't loaded

Rules that keep it honest:

- `unknown` is never treated as a negative. An empty profile yields unknown
  dimensions and an *Insufficient evidence* verdict, not a no-bid.
- The summary recommendation comes from **ordered deterministic rules** over
  the ratings (never a blended score):
  `pursue as prime · prime with partner · subcontract · shape before pursuing ·
  track · pursue only if a named condition changes · no-bid · insufficient
  evidence`.
- A **likely** (inferred) incumbent downgrades a prime pursuit to
  track-and-verify; only evidence changes that.
- The stack is computed per organization at read time over the cached global
  dossier — tenant judgments are never cached across orgs.

## Section inventory

| Section | Module | Notes |
|---|---|---|
| Decision stack | `intel/decision.py` | per-org, read-time |
| Compliance matrix + proof | `documents/*`, `intel/proof.py` | page-level evidence per row |
| Contract family & recompete clock | `intel/contract_family.py` | confirmed vs inferred links |
| Incumbent vulnerability | `intel/contract_family.py` | public signals only, never CPARS |
| Buyer DNA | `intel/buyer_dna.py` | peer-normalized, labeled only on material deltas |
| Incumbent analysis | `intel/incumbent.py` | 3 evidence tiers |
| Funding context | `intel/funding.py` | four exclusive labels |
| Amendment & change history | `db.diff_opportunity` + store | field-level old → new |
| Evidence & source ledger | `intel/ledger.py` | source, retrieval, used-by, limitations |
| Capture plan | `capture_tasks` | recommended action → one-click task |

## Quality gates this page must pass

- Recommendation, deadline, incumbent, value range, top risk, and next action
  visible within 30 seconds of page load, without scrolling.
- Unknown is visually distinct from negative (`r-unknown` dashed chip).
- Inference is visually distinct from confirmed fact (timeline `inferred`
  markers, `confirmed/inferred` badges on family members).
- Every panel that lacks data says so and says what would fill it.
- The evidence ledger lets a user audit every section's sources.
