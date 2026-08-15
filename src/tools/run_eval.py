"""Golden evaluation runner: rebuilds every golden case's dossier and decision
stack from scratch and scores the pipeline against hand-set expectations.

Usage:  python -m src.tools.run_eval        (exit 1 on any failure)

This is the release gate the red-team process runs: a change that flips a
golden conclusion fails loudly here before it can ship a wrong verdict.
"""
import sys

from ..documents.qualification import assess
from ..intel.decision import build_decision_stack
from ..intel.dossier import build_dossier
from ..intel.grant_readiness import assess_grant_eligibility
from .eval_cases import GOLDEN_CASES, GRANT_CASES, TODAY


def _check(results, case, key, expected, actual):
    ok = expected == actual
    results.append({"case": case, "check": key, "expected": expected,
                    "actual": actual, "ok": ok})
    return ok


def _contains(results, case, key, needle, haystack):
    ok = needle in haystack
    results.append({"case": case, "check": key, "expected": f"…{needle}…",
                    "actual": haystack[:120] if not ok else "(found)",
                    "ok": ok})
    return ok


def run_case(case, results):
    opp = case["opp"]
    dossier = build_dossier(
        opp, {"score": case.get("score") or 0},
        case.get("awards_office") or [], case.get("awards_subtier") or [],
        [], case.get("budget_rows") or [], today=TODAY,
        protests=case.get("protests"), oversight=case.get("oversight"))
    qualification = None
    if case.get("requirements"):
        qualification = assess(case["requirements"], case.get("profile") or {})
    decision = build_decision_stack(
        opp=opp, match={"score": case.get("score"), "reasons": []},
        dossier=dossier, qualification=qualification, value_est=None,
        documents=None, days_left=case.get("days_left"),
        projects=case.get("projects"), weights=None,
        forecasts=case.get("forecasts"))
    exp = case["expected"]
    name = case["name"]
    inc = dossier["incumbent_analysis"]
    if "incumbent_status" in exp:
        _check(results, name, "incumbent_status", exp["incumbent_status"],
               inc["incumbent_status"])
    if "incumbent_name" in exp:
        _check(results, name, "incumbent_name", exp["incumbent_name"],
               inc.get("likely_incumbent_name"))
    if "work_origin" in exp:
        _check(results, name, "work_origin", exp["work_origin"],
               dossier["work_origin_assessment"]["work_origin_assessment"])
    if "funding_label_key" in exp:
        _check(results, name, "funding_label_key", exp["funding_label_key"],
               dossier["funding_context"]["label_key"])
    if "family_confirmed_count" in exp:
        _check(results, name, "family_confirmed_count",
               exp["family_confirmed_count"],
               dossier["contract_family"]["confirmed_count"])
    if "vulnerability" in exp:
        _check(results, name, "vulnerability", exp["vulnerability"],
               dossier["contract_family"]["vulnerability"]["assessment"])
    if "decision_key" in exp:
        _check(results, name, "decision_key", exp["decision_key"],
               decision["summary"]["recommendation_key"])
    dims = {d["key"]: d for d in decision["dimensions"]}
    if "eligibility_rating" in exp:
        _check(results, name, "eligibility_rating", exp["eligibility_rating"],
               dims["eligibility"]["rating"])
    if "execution_rating" in exp:
        _check(results, name, "execution_rating", exp["execution_rating"],
               dims["execution_readiness"]["rating"])
    if "incumbent_evidence_contains" in exp:
        _contains(results, name, "incumbent_evidence",
                  exp["incumbent_evidence_contains"],
                  " ".join(dims["incumbent_position"]["evidence"]))


def run() -> int:
    results: list[dict] = []
    for case in GOLDEN_CASES:
        run_case(case, results)
    for gc in GRANT_CASES:
        verdict = assess_grant_eligibility(gc["grant"],
                                           gc["applicant_type"])["verdict"]
        _check(results, gc["name"], "grant_verdict", gc["expected_verdict"],
               verdict)

    failures = [r for r in results if not r["ok"]]
    print(f"Golden evaluation scorecard — {len(GOLDEN_CASES)} contract cases, "
          f"{len(GRANT_CASES)} grant cases, {len(results)} checks")
    print("-" * 72)
    current = None
    for r in results:
        if r["case"] != current:
            current = r["case"]
            print(f"\n{current}")
        mark = "PASS" if r["ok"] else "FAIL"
        line = f"  [{mark}] {r['check']}"
        if not r["ok"]:
            line += f"  expected={r['expected']!r} actual={r['actual']!r}"
        print(line)
    print("-" * 72)
    print(f"{len(results) - len(failures)}/{len(results)} checks passed")
    if failures:
        print(f"RELEASE BLOCKED: {len(failures)} golden expectation(s) broken.")
        return 1
    print("All golden expectations hold.")
    return 0


if __name__ == "__main__":
    sys.exit(run())
