"""Capture Decision Stack: every dimension present, unknown ≠ negative,
recommendation rules deterministic and honest."""
from src.intel.decision import RECOMMENDATIONS, build_decision_stack

OPP = {"title": "Enterprise software modernization", "agency": "DEPT OF THE ARMY",
       "office": "ACC-RSA", "notice_type": "Solicitation", "naics": "541512"}


def _qual(verdict="qualified", disqualifying=None, blocking=None, unknowns=None,
          gaps=None, rows=None):
    return {"verdict": verdict, "rows": rows or [], "gaps": gaps or [],
            "disqualifying": disqualifying or [], "blocking": blocking or [],
            "unknowns": unknowns or []}


def _dossier(inc_status="no_known_incumbent", inc_name=None, inc_conf=30,
             comp_label="fragmented market", trend="stable"):
    return {
        "similar_work": [{"vendor": "A"}] * 3,
        "incumbent_analysis": {
            "incumbent_status": inc_status, "likely_incumbent_name": inc_name,
            "incumbent_confidence": inc_conf,
            "supporting_evidence": (["prior award shares the solicitation number"]
                                    if inc_status == "confirmed_incumbent" else []),
        },
        "competition_landscape": {"label": comp_label, "top3_share_pct": 40,
                                  "unique_vendor_count": 9},
        "market_size": {"trend": trend},
        "funding_context": {"label_key": "agency"},
    }


def stack(**kw):
    args = {"opp": OPP, "match": {"score": 82, "reasons": ["keyword hit"]},
            "dossier": _dossier(), "qualification": _qual(),
            "value_est": {"low": 1e6, "high": 3e6, "median": 2e6, "basis": 4},
            "documents": [{"fetch_status": "extracted"}], "days_left": 21,
            "projects": None, "weights": None}
    args.update(kw)
    return build_decision_stack(**args)


def test_all_ten_dimensions_present_with_required_fields():
    s = stack()
    keys = [d["key"] for d in s["dimensions"]]
    assert keys == ["eligibility", "capability_fit", "past_performance",
                    "buyer_position", "incumbent_position", "competitive_position",
                    "economic_attractiveness", "strategic_value",
                    "execution_readiness", "intelligence_completeness"]
    for d in s["dimensions"]:
        assert d["rating"] in ("strong", "moderate", "weak", "blocked", "unknown")
        assert isinstance(d["evidence"], list) and d["evidence"]
        assert 0 <= d["confidence"] <= 100
        assert d["materiality"] in ("gate", "high", "medium", "low")


def test_strong_fit_clean_path_recommends_prime():
    s = stack()
    assert s["summary"]["recommendation_key"] == "pursue_prime"
    assert s["summary"]["recommendation"] == RECOMMENDATIONS["pursue_prime"]
    assert s["summary"]["rationale"]


def test_set_aside_bar_with_fit_recommends_subcontract():
    q = _qual(verdict="not eligible to prime",
              disqualifying=[{"requirement_type": "set_aside", "value": "8(a)"}])
    s = stack(qualification=q)
    assert s["summary"]["recommendation_key"] == "pursue_subcontract"
    elig = s["dimensions"][0]
    assert elig["rating"] == "blocked"
    assert "8(a)" in elig["evidence"][0]


def test_set_aside_bar_with_weak_fit_recommends_no_bid():
    q = _qual(verdict="not eligible to prime",
              disqualifying=[{"requirement_type": "set_aside", "value": "WOSB"}])
    s = stack(qualification=q, match={"score": 30, "reasons": []})
    assert s["summary"]["recommendation_key"] == "no_bid"


def test_vehicle_gate_recommends_prime_with_partner():
    q = _qual(verdict="blocked unless teaming",
              blocking=[{"requirement_type": "vehicle", "value": "GSA MAS"}])
    s = stack(qualification=q)
    assert s["summary"]["recommendation_key"] == "pursue_prime_with_partner"


def test_confirmed_incumbent_yields_conditional():
    d = _dossier(inc_status="confirmed_incumbent", inc_name="ACME CORP",
                 inc_conf=90)
    s = stack(dossier=d)
    assert s["summary"]["recommendation_key"] == "conditional"
    inc = next(x for x in s["dimensions"] if x["key"] == "incumbent_position")
    assert inc["rating"] == "weak" and "ACME CORP" in inc["evidence"][0]


def test_likely_incumbent_downgrades_prime_to_track():
    d = _dossier(inc_status="likely_incumbent", inc_name="NORTHSTAR", inc_conf=70)
    d["incumbent_analysis"]["supporting_evidence"] = ["same buying office; NAICS"]
    s = stack(dossier=d)
    assert s["summary"]["recommendation_key"] == "track"
    assert any("verify the incumbency" in r for r in s["summary"]["rationale"])


def test_early_stage_recommends_shape():
    s = stack(opp={**OPP, "notice_type": "Sources Sought"})
    assert s["summary"]["recommendation_key"] == "shape"


def test_no_data_at_all_is_insufficient_evidence_not_no_bid():
    s = stack(match={}, dossier=None, qualification=None, value_est=None,
              documents=None, days_left=None)
    assert s["summary"]["recommendation_key"] == "insufficient_evidence"
    # Unknowns must never be scored as negatives
    for d in s["dimensions"]:
        if d["key"] in ("capability_fit", "past_performance", "buyer_position",
                        "incumbent_position", "strategic_value"):
            assert d["rating"] == "unknown", d["key"]


def test_expired_deadline_is_no_bid():
    s = stack(days_left=-2)
    assert s["summary"]["recommendation_key"] == "no_bid"
    ex = next(x for x in s["dimensions"] if x["key"] == "execution_readiness")
    assert ex["rating"] == "blocked"


def test_projects_upgrade_past_performance_and_buyer_position():
    projects = [{"naics": "541512", "customer_agency": "Dept of the Army",
                 "customer_office": "ACC-RSA"}]
    s = stack(projects=projects)
    pp = next(x for x in s["dimensions"] if x["key"] == "past_performance")
    bp = next(x for x in s["dimensions"] if x["key"] == "buyer_position")
    assert pp["rating"] == "strong"
    assert bp["rating"] == "strong"


def test_projects_without_relevance_are_weak_not_unknown():
    projects = [{"naics": "236220", "customer_agency": "GSA"}]
    s = stack(projects=projects)
    pp = next(x for x in s["dimensions"] if x["key"] == "past_performance")
    assert pp["rating"] == "weak"
    assert pp["mitigation"]  # teaming suggestion present


def test_learned_weights_drive_strategic_value():
    s = stack(weights={"naics:541512": 5})
    sv = next(x for x in s["dimensions"] if x["key"] == "strategic_value")
    assert sv["rating"] == "strong"
    s2 = stack(weights={"naics:541512": -4})
    sv2 = next(x for x in s2["dimensions"] if x["key"] == "strategic_value")
    assert sv2["rating"] == "weak"


def test_advantages_and_risks_derived_from_dimensions():
    d = _dossier(inc_status="likely_incumbent", inc_name="BETA LLC", inc_conf=70)
    s = stack(dossier=d)
    assert s["top_risks"], "likely incumbent must surface as a risk"
    assert any("BETA LLC" in r for r in s["top_risks"])
    assert s["top_advantages"]


def test_completeness_pct_reflects_missing_intel():
    s_full = stack()
    s_empty = stack(dossier=None, documents=None, qualification=None,
                    value_est=None)
    assert s_full["completeness_pct"] > s_empty["completeness_pct"]
