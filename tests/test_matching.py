"""Per-organization matching: same opportunity, different scores per profile."""
from src.matching import score_opportunity_for_profile


def _opp():
    return {"title": "Enterprise Inventory Management System Modernization",
            "agency": "DEPT OF THE ARMY", "notice_type": "Solicitation",
            "naics": "541512", "set_aside": "Total Small Business Set-Aside",
            "description_text": "modernize a legacy inventory application; web "
                                "dashboards, database migration",
            "response_deadline": None, "place_of_performance": "Huntsville, AL",
            "solicitation_number": "W1", "url": None, "source_notice_id": "n1"}


SOFTWARE_PROFILE = {"keywords_boost": ["inventory", "dashboard", "database"],
                    "naics_codes": ["541512"], "agencies_of_interest": ["ARMY"]}
FIBER_PROFILE = {"keywords_boost": ["fiber", "osp", "splicing"],
                 "keywords_suppress": ["software", "application"],
                 "naics_codes": ["237130"]}


def test_same_opportunity_scores_differently_per_profile():
    software = score_opportunity_for_profile(_opp(), SOFTWARE_PROFILE)
    fiber = score_opportunity_for_profile(_opp(), FIBER_PROFILE)
    assert software["score"] > fiber["score"]
    assert software["score"] - fiber["score"] >= 10


def test_empty_profile_falls_back_to_base_rules():
    result = score_opportunity_for_profile(_opp(), {})
    assert 0 <= result["score"] <= 100
    assert result["category"]
