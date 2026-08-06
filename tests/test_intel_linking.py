"""Opportunity-to-award linking, last-10 selection, incumbent + work origin."""
from datetime import date

from src.intel.incumbent import analyze_incumbent, assess_work_origin
from src.intel.linking import last_10_relevant, link_awards
from tests.conftest import make_award

TODAY = date(2026, 7, 7)


def links_for(opp, identity, awards):
    return link_awards(opp, identity, awards, today=TODAY)


def test_linking_scores_same_office_same_naics_high(opp_norm, opp_identity):
    award = make_award(awarding_office="AMC", awarding_subtier="DEPT OF THE ARMY",
                       solicitation_number="TOTALLY-DIFFERENT-99")
    (ln,) = links_for(opp_norm, opp_identity, [award])
    assert ln["similarity_score"] >= 50
    assert ln["link_type"] == "same_office_same_naics"
    assert "same buying office" in ln["evidence"]


def test_linking_same_solicitation_family(opp_norm, opp_identity):
    award = make_award(solicitation_number="W58RGZ-26-R-0042-0001")
    (ln,) = links_for(opp_norm, opp_identity, [award])
    assert ln["link_type"] == "same_solicitation"


def test_old_awards_penalized(opp_norm, opp_identity):
    recent = make_award(award_date="2024-01-01")
    ancient = make_award(source_award_id="AW-OLD", award_date="2009-01-01",
                         period_end="2011-01-01")
    lns = links_for(opp_norm, opp_identity, [recent, ancient])
    assert lns[0]["award"]["source_award_id"] == "AW-1"
    assert lns[0]["similarity_score"] > lns[1]["similarity_score"]


def test_last_10_relevant_prefers_relevance_over_recency(opp_norm, opp_identity):
    relevant_old = make_award(source_award_id="REL", award_date="2022-01-01")
    irrelevant_new = make_award(
        source_award_id="IRR", award_date="2026-01-01",
        awarding_office="SOMEWHERE ELSE", awarding_subtier="DEPT OF THE NAVY",
        naics="561720", psc="S201",
        award_title="Janitorial and custodial services",
        award_description="cleaning services for facilities",
        solicitation_number="N00019-26-R-9999",
        place_of_performance_json={"city": "Norfolk", "state": "VA"})
    lns = links_for(opp_norm, opp_identity, [relevant_old, irrelevant_new])
    top = last_10_relevant(lns)
    assert top[0]["award"]["source_award_id"] == "REL"


# ---- incumbent fixtures per spec: exact / likely / false / none ----

def test_exact_incumbent_match(opp_norm, opp_identity):
    award = make_award(solicitation_number="W58RGZ-26-R-0042")
    res = analyze_incumbent(opp_norm, links_for(opp_norm, opp_identity, [award]), today=TODAY)
    assert res["incumbent_status"] == "confirmed_incumbent"
    assert res["likely_incumbent_name"] == "ABC Systems, Inc."
    assert res["incumbent_confidence"] >= 85


def test_likely_incumbent_match(opp_norm, opp_identity):
    award = make_award(solicitation_number="OLD-SOL-123", period_end="2026-09-30")
    res = analyze_incumbent(opp_norm, links_for(opp_norm, opp_identity, [award]), today=TODAY)
    assert res["incumbent_status"] == "likely_incumbent"
    assert 50 <= res["incumbent_confidence"] <= 89
    assert any("ends within 12 months" in e for e in res["supporting_evidence"])


def test_false_incumbent_same_office_different_work(opp_norm, opp_identity):
    award = make_award(
        solicitation_number="OLD-SOL-777", naics="561720", psc="S201",
        award_title="Grounds maintenance services",
        award_description="lawn mowing and landscaping",
        period_end="2020-01-01", award_date="2018-01-01")
    res = analyze_incumbent(opp_norm, links_for(opp_norm, opp_identity, [award]), today=TODAY)
    assert res["incumbent_status"] in ("no_known_incumbent", "possible_incumbent")
    assert res["incumbent_status"] != "likely_incumbent"


def test_no_history_found(opp_norm):
    res = analyze_incumbent(opp_norm, [], today=TODAY)
    assert res["incumbent_status"] == "insufficient_data"
    assert any("not evidence of absence" in c for c in res["caveats"])


def test_no_known_incumbent_caveat_wording(opp_norm, opp_identity):
    weak = make_award(awarding_office="OTHER OFFICE", awarding_subtier="DEPT OF THE NAVY",
                      naics="541512", award_title="database work", recipient_name=None,
                      solicitation_number="X-1")
    res = analyze_incumbent(opp_norm, links_for(opp_norm, opp_identity, [weak]), today=TODAY)
    if res["incumbent_status"] == "no_known_incumbent":
        assert any("not the same as" in c for c in res["caveats"])


# ---- work origin ----

def test_work_origin_modernization(opp_norm, opp_identity):
    links = links_for(opp_norm, opp_identity, [make_award()])
    res = assess_work_origin(opp_norm, links)
    assert res["work_origin_assessment"] == "modernization_of_existing_system"
    assert "modernization" in res["evidence_from_posting"]["existing_system_signals"] or \
           "legacy system" in res["evidence_from_posting"]["existing_system_signals"]


def test_work_origin_new_start(sam_record):
    from src.normalize import normalize_sam
    sam_record["title"] = "Prototype Autonomous Scheduling Pilot"
    sam_record["description"] = "proof of concept for a new requirement; market research"
    opp = normalize_sam(sam_record)
    res = assess_work_origin(opp, [])
    assert res["work_origin_assessment"] in ("new_start", "research_prototype")
    assert res["caveats"]  # no prior-award evidence loaded
