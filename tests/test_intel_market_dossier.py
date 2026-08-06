"""Market stats, funding confidence, recommendation, dossier assembly + escaping."""
from datetime import date

from src.intel.confidence import band, claim
from src.intel.dossier import build_dossier, intel_line
from src.intel.funding import build_funding_context
from src.intel.market import competition_landscape, market_size
from src.intel.report import render_report
from tests.conftest import make_award

TODAY = date(2026, 7, 7)


def test_confidence_bands():
    assert band(95) == "confirmed or near-confirmed"
    assert band(80) == "strong signal"
    assert band(60) == "moderate signal"
    assert band(30) == "weak signal"
    assert band(5) == "insufficient support"
    c = claim("x", 130, "basis")
    assert c["confidence"] == 100


def test_market_stats_aggregation_and_trend_growing():
    awards = []
    for year, n, amt in ((2022, 2, 1e6), (2023, 3, 1.5e6), (2024, 4, 2e6), (2025, 5, 2.5e6)):
        for i in range(n):
            awards.append(make_award(source_award_id=f"A{year}-{i}",
                                     award_date=f"{year}-06-01", obligated_amount=amt))
    m = market_size(awards, today=TODAY)
    assert m["trend"] == "growing"
    assert m["windows"]["5y"]["award_count"] == 14
    assert m["windows"]["3y"]["award_count"] == 9
    assert m["windows"]["5y"]["median_award_size"] == 2e6


def test_market_insufficient_data():
    m = market_size([], today=TODAY, level="office")
    assert m["trend"] == "insufficient data"
    assert "thin" in m["note"]


def test_competition_concentration_labels():
    dominant = [make_award(source_award_id=f"D{i}", obligated_amount=10e6) for i in range(6)]
    frag = [make_award(source_award_id=f"F{i}", recipient_name=f"Vendor {i} Inc",
                       recipient_uei=f"UEI{i}", obligated_amount=1e6) for i in range(10)]
    assert "incumbent-dominated" in competition_landscape(dominant)["label"]
    assert "fragmented" in competition_landscape(frag)["label"]
    assert competition_landscape([])["label"] == "insufficient data"


def test_funding_confidence_labels(opp_norm):
    links = [{"award": make_award(), "similarity_score": 60, "link_type": "similar_scope",
              "evidence": []}]
    direct = build_funding_context(opp_norm, links,
                                   accounts=[{"federal_account_code": "097-0100",
                                              "federal_account_name": "O&M Army"}],
                                   budget_rows=[])
    assert direct["label"] == "Direct funding link found"
    assert direct["confidence"] >= 75

    likely = build_funding_context(opp_norm, links, accounts=[], budget_rows=[])
    assert likely["label"] == "Likely related funding account"
    assert 25 <= likely["confidence"] < 50  # inferred only

    agency = build_funding_context(opp_norm, [], accounts=[],
                                   budget_rows=[{"fiscal_year": 2026,
                                                 "budgetary_resources": 1e9, "source": "usaspending"}])
    assert agency["label"] == "Agency-level budget context"

    nothing = build_funding_context(opp_norm, [], accounts=[], budget_rows=[])
    assert nothing["label"] == "No public funding context found"
    # Truthfulness: budget context never claims funding
    assert any("does not prove funding" in c for c in agency["caveats"])


def _dossier(opp, classification=None, awards=None):
    return build_dossier(opp, classification or {"score": 85, "category": "Inventory / Asset / Logistics Tools"},
                         awards_office=awards if awards is not None else [make_award()],
                         awards_subtier=[], accounts=[], budget_rows=[], today=TODAY)


def test_dossier_assembles_all_sections(opp_norm):
    d = _dossier(opp_norm)
    for key in ("snapshot", "buyer_profile", "similar_work", "last_10_relevant_awards",
                "incumbent_analysis", "work_origin_assessment", "funding_context",
                "market_size", "competition_landscape", "acquisition_pattern",
                "pursuit_recommendation", "data_quality"):
        assert key in d
    assert d["snapshot"]["recommendation"] in (
        "Pursue now", "Track closely", "Investigate incumbent first", "Find teammate",
        "Watch only", "Ignore", "Insufficient data")
    assert any("solicitation-number" in q or "USAspending" in q for q in d["data_quality"])


def test_dossier_subtier_fallback_notes_quality(opp_norm):
    d = build_dossier(opp_norm, {"score": 85, "category": "x"},
                      awards_office=[], awards_subtier=[make_award()],
                      accounts=[], budget_rows=[], today=TODAY)
    assert any("subtier-level data used" in q for q in d["data_quality"])
    assert d["market_size"]["level"] == "subtier"


def test_recommendation_investigate_incumbent(opp_norm):
    d = _dossier(opp_norm, awards=[make_award(solicitation_number="W58RGZ-26-R-0042")])
    assert d["incumbent_analysis"]["incumbent_status"] == "confirmed_incumbent"
    assert d["pursuit_recommendation"]["recommendation"] == "Investigate incumbent first"


def test_recommendation_insufficient_data(opp_norm):
    d = _dossier(opp_norm, awards=[])
    assert d["pursuit_recommendation"]["recommendation"] == "Insufficient data"


def test_recommendation_ignore_on_low_fit(opp_norm):
    d = _dossier(opp_norm, classification={"score": 15, "category": "x"})
    assert d["pursuit_recommendation"]["recommendation"] == "Ignore"


def test_intel_line_wording(opp_norm):
    d = _dossier(opp_norm, awards=[make_award(solicitation_number="OLD-1", period_end="2026-09-30"),
                                   make_award(source_award_id="AW-2", obligated_amount=9e6)])
    line = intel_line(d)
    assert line.startswith("Intel: ")
    assert "likely incumbent ABC Systems, Inc." in line or "confirmed incumbent" in line
    assert "% confidence" in line
    assert intel_line({"similar_work": [], "incumbent_analysis": {}}) == \
        "Intel: no comparable award history found in public data yet."


# ---- security: malicious award/vendor/budget data must render inert ----

PAYLOAD = "<script>alert(1)</script><img src=x onerror=alert(2)>"


def test_report_escapes_malicious_award_and_vendor_data(opp_norm):
    hostile = make_award(
        recipient_name=f"Evil {PAYLOAD} Corp",
        award_title=f"Totally normal {PAYLOAD} award",
        award_description=PAYLOAD)
    d = _dossier(opp_norm, awards=[hostile])
    html = render_report(d, opp_url="javascript:alert(1)", notice_id="abc123")
    assert "<script>" not in html
    assert "<img" not in html
    assert "&lt;script&gt;" in html
    assert "javascript:" not in html
    assert 'href="https://sam.gov/opp/abc123/view"' in html


def test_digest_escapes_intel_line_payload():
    from datetime import datetime, timezone

    from src.digest import render
    now = datetime(2026, 7, 8, 12, 0, tzinfo=timezone.utc)
    row = {
        "id": 1, "title": "T", "agency": "Army", "notice_type": "RFP", "naics": "541512",
        "set_aside": None, "response_deadline": None, "url": None, "source_notice_id": "abc",
        "place_of_performance": None, "category": "x", "score": 90, "reasons": [],
        "components": {}, "recommended_action": None, "first_seen_at": now,
        "intel_line": f"Intel: likely incumbent {PAYLOAD}", "top_risk": PAYLOAD,
    }
    html = render([row], now.date(), now=now)
    assert "<script>" not in html and "<img" not in html
    assert "&lt;script&gt;" in html
