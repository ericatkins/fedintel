# Intelligence Evaluation

How Fedintel's conclusions are tested, and what blocks a release.

## The golden evaluation set

`src/tools/eval_cases.py` holds hand-authored scenarios with the conclusions
a careful analyst would accept; `python -m src.tools.run_eval` rebuilds every
dossier and decision stack from scratch and prints a scorecard, exiting
nonzero on any broken expectation. `tests/test_golden_eval.py` runs the same
gate in CI — the whole-pipeline regression test on every commit.

Current coverage (9 contract cases + 3 grant cases, 26 checks):

| Case | What it protects |
|---|---|
| confirmed_recompete | identifier-match → confirmed incumbent, recompete origin, conditional verdict |
| likely_incumbent_downgrades_to_track | inferred incumbency must never yield pursue-as-prime |
| sources_sought_new_start | early-stage new starts route to shape-the-requirement |
| set_aside_bar_routes_to_subcontract | eligibility gate → subcontract, never a silent no-bid |
| vehicle_gate_prime_with_partner | teamable gates recommend a partner, not surrender |
| sparse_data_is_insufficient_evidence | missing data is never scored as a negative |
| bridge_plus_protest_is_displacement_opportunity | multi-signal vulnerability vocabulary |
| conflicting_incumbent_evidence_is_surfaced | forecast-vs-history conflicts shown, never silently resolved |
| expired_deadline_is_no_bid | execution readiness blocks regardless of fit |
| grant_* (3) | applicant-type verdicts: eligible / not-listed-as-caution / unknown |

## What the scorecard checks per case

Incumbent tier and name · work-origin label · funding label key · confirmed
family-member count · vulnerability vocabulary · decision-stack verdict ·
per-dimension ratings (eligibility, execution) · conflict surfacing · grant
eligibility verdicts.

## Case-authoring rules

- Cases mirror **real record shapes**: opportunities carry
  `fullParentPathName` (office identity depends on it), award descriptions
  are as rich as USAspending's. Two early drafts of the set failed for
  exactly this reason — thin synthetic records under-score links that real
  records would make; the fix is realistic cases, never loosened thresholds.
- Expected values use the pipeline's honest vocabulary (`insufficient_data`,
  `no defensible assessment`) — a case must never expect confidence the
  evidence can't carry.
- When a golden check fails, the default assumption is a pipeline regression;
  weakening an expectation requires the same scrutiny as changing a
  truthfulness rule.

## Known gaps (deliberate)

- Cases are offline fixtures. The mission's full golden set — live SAM.gov
  records across DoD/NASA/DOJ/USDA/NPS/HUD with hand-verified expectations,
  measuring document-extraction precision/recall and office-resolution
  accuracy against real attachments — requires a `SAM_API_KEY` and network
  access to federal APIs. The case shape is designed so live captures drop
  in unchanged.
- No win-probability calibration measurements exist because no win
  probability ships (deliberately, until outcomes accumulate).
