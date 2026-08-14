"""Requirement deltas across lineage stages and forecast-aware incumbent
evidence in the decision stack."""
from src.intel.decision import build_decision_stack
from src.intel.requirement_delta import diff_requirements, lineage_requirement_delta


def _req(rtype, value):
    return {"requirement_type": rtype, "value": value}


def test_diff_added_removed_unchanged():
    older = [_req("clearance", "Secret"), _req("submission", "20 pages")]
    newer = [_req("clearance", "TS/SCI"), _req("submission", "20 pages"),
             _req("certification", "CMMC Level 2")]
    d = diff_requirements(older, newer)
    assert [r["value"] for r in d["added"]] == ["CMMC Level 2", "TS/SCI"]
    assert [r["value"] for r in d["removed"]] == ["Secret"]
    assert d["unchanged_count"] == 1
    assert d["comparable"]


def test_diff_is_case_insensitive_on_values():
    d = diff_requirements([_req("clearance", "SECRET")],
                          [_req("clearance", "Secret")])
    assert d["added"] == [] and d["removed"] == []


def test_lineage_delta_picks_nearest_earlier_stage_with_extractions():
    lineage = [{"opportunity_id": 1, "stage": "Sources Sought"},
               {"opportunity_id": 2, "stage": "Presolicitation"},
               {"opportunity_id": 3, "stage": "Solicitation"}]
    by_opp = {1: [_req("clearance", "Secret")],
              2: [],                                   # no extraction → skipped
              3: [_req("clearance", "TS/SCI")]}
    d = lineage_requirement_delta(3, lineage, by_opp)
    assert d["compared_against_opportunity_id"] == 1
    assert [r["value"] for r in d["added"]] == ["TS/SCI"]


def test_lineage_delta_none_without_comparison_basis():
    lineage = [{"opportunity_id": 1, "stage": "Sources Sought"},
               {"opportunity_id": 3, "stage": "Solicitation"}]
    assert lineage_requirement_delta(3, lineage, {3: [_req("a", "b")]}) is None
    assert lineage_requirement_delta(3, lineage, {1: [_req("a", "b")]}) is None


OPP = {"title": "T", "agency": "A", "notice_type": "Solicitation",
       "naics": "541512"}


def _stack(forecasts=None, incumbent=None):
    dossier = {"similar_work": [], "incumbent_analysis": incumbent or {},
               "competition_landscape": {}, "market_size": {},
               "funding_context": {}}
    return build_decision_stack(
        opp=OPP, match={"score": 80, "reasons": []}, dossier=dossier,
        qualification=None, value_est=None, documents=None, days_left=30,
        forecasts=forecasts)


def test_forecast_stated_incumbent_fills_unknown_incumbent_dimension():
    s = _stack(forecasts=[{"incumbent_name": "Northstar Data LLC"}])
    inc = next(d for d in s["dimensions"] if d["key"] == "incumbent_position")
    assert inc["rating"] == "weak"
    assert any("procurement forecast names Northstar Data LLC" in e
               for e in inc["evidence"])
    assert any("only source" in e for e in inc["evidence"])


def test_forecast_incumbent_conflict_is_surfaced_not_hidden():
    incumbent = {"incumbent_status": "likely_incumbent",
                 "likely_incumbent_name": "ACME CORP",
                 "incumbent_confidence": 70, "supporting_evidence": []}
    s = _stack(forecasts=[{"incumbent_name": "Northstar Data LLC"}],
               incumbent=incumbent)
    inc = next(d for d in s["dimensions"] if d["key"] == "incumbent_position")
    assert any("CONFLICTS" in e for e in inc["evidence"])


def test_forecast_incumbent_corroboration_raises_confidence():
    incumbent = {"incumbent_status": "likely_incumbent",
                 "likely_incumbent_name": "Northstar Data LLC",
                 "incumbent_confidence": 70, "supporting_evidence": []}
    s_with = _stack(forecasts=[{"incumbent_name": "Northstar Data LLC"}],
                    incumbent=incumbent)
    s_without = _stack(forecasts=None, incumbent=incumbent)
    inc_with = next(d for d in s_with["dimensions"]
                    if d["key"] == "incumbent_position")
    inc_without = next(d for d in s_without["dimensions"]
                       if d["key"] == "incumbent_position")
    assert inc_with["confidence"] > inc_without["confidence"]
    assert any("corroborates" in e for e in inc_with["evidence"])
