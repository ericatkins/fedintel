"""Executive Intelligence Brief: grounded, referenced, honest about gaps."""
from src.intel.brief import build_executive_brief
from src.intel.decision import build_decision_stack

OPP = {"title": "Enterprise Inventory Modernization",
       "agency": "DEPT OF THE ARMY", "office": "ACC",
       "notice_type": "Solicitation", "naics": "541512"}


def _dossier():
    return {
        "work_origin_assessment": {"work_origin_assessment": "recompete",
                                   "confidence": 80},
        "incumbent_analysis": {"incumbent_status": "likely_incumbent",
                               "likely_incumbent_name": "NORTHSTAR LLC",
                               "incumbent_confidence": 70,
                               "supporting_evidence": ["same buying office"]},
        "contract_family": {"member_count": 4, "confirmed_count": 1,
                            "recompete": {"estimated_expiration": "2026-06-14"},
                            "vulnerability":
                                {"assessment": "credible displacement "
                                               "opportunity"}},
        "buyer_dna": {"status": "ok",
                      "labels": [{"label": "incumbent-favoring"},
                                 {"label": "Q4-driven"}]},
        "competition_landscape": {"label": "highly concentrated"},
        "market_size": {"trend": "stable"},
        "funding_context": {"label_key": "likely"},
        "similar_work": [1, 2],
    }


def _decision(dossier):
    return build_decision_stack(
        opp=OPP, match={"score": 82, "reasons": ["keyword hit"]},
        dossier=dossier, qualification=None, value_est=None, documents=None,
        days_left=20)


def test_brief_covers_the_required_narrative_arcs():
    d = _dossier()
    brief = build_executive_brief(OPP, d, _decision(d))
    joined = " ".join(p["text"] for p in brief)
    assert "recompete" in joined                       # what/origin
    assert "2026-06-14" in joined                      # why now (expiration)
    assert "NORTHSTAR LLC" in joined                   # history/incumbent
    assert "incumbent-favoring" in joined              # buyer behavior
    assert "Recommended approach:" in joined           # approach
    # every paragraph is referenced to a section
    assert all(p["refs"] for p in brief)


def test_brief_is_honest_when_nothing_is_loaded():
    dossier = {"work_origin_assessment": {"work_origin_assessment": "unclear",
                                          "confidence": 30},
               "incumbent_analysis": {"incumbent_status": "insufficient_data"},
               "contract_family": {}, "buyer_dna": {},
               "competition_landscape": {}, "market_size": {},
               "funding_context": {"label_key": "none"}, "similar_work": []}
    decision = build_decision_stack(
        opp=OPP, match={}, dossier=dossier, qualification=None,
        value_est=None, documents=None, days_left=None)
    brief = build_executive_brief(OPP, dossier, decision)
    joined = " ".join(p["text"] for p in brief)
    assert "not the same as absent" in joined or "not evidence of absence" \
        in joined
    assert "unknown" in joined.lower()
    assert "Critical unresolved questions:" in joined


def test_brief_without_dossier_says_pending():
    decision = build_decision_stack(
        opp=OPP, match={}, dossier=None, qualification=None, value_est=None,
        documents=None, days_left=None)
    brief = build_executive_brief(OPP, None, decision)
    assert len(brief) == 1 and "pending" in brief[0]["text"]


def test_brief_uses_forecast_and_oversight_when_linked():
    d = _dossier()
    brief = build_executive_brief(
        OPP, d, _decision(d),
        forecasts=[{"action_type": "recompete", "title": "F"}],
        oversight=[{"report_number": "GAO-25-1", "link_kind": "inferred"}])
    why = next(p for p in brief if p["text"].startswith("Why now:"))
    assert "forecast planned this as a recompete" in why["text"]
    assert "GAO-25-1" in why["text"]
    assert "inferred context" in why["text"]
