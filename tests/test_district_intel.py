"""District intelligence: computed lean, seat outlook reasoning, attribution
honesty, ranking pages, geo-adapter parsing, entitlement + XSS safety."""
import pytest
from fastapi.testclient import TestClient

from src.adapters.usaspending_geo import parse_results
from src.intel.district import (
    ATTRIBUTION_NOTE,
    SENTIMENT_NOTE,
    partisan_lean,
    primary_history,
    rank_note,
    seat_outlook,
)
from src.web.app import SESSION_COOKIE, app
from src.web.auth import hash_password, new_session_token
from src.web.store import MemoryStore

PASSWORD = "a long enough password"
PAYLOAD = "<script>alert(1)</script>"


def _general(cycle, winner_share, runner_share, party="R"):
    return [
        {"cycle": cycle, "stage": "general", "candidate_name": "Winner Person",
         "party": party, "vote_share": winner_share, "won": True,
         "incumbent": True, "source": "test"},
        {"cycle": cycle, "stage": "general", "candidate_name": "Runner Up",
         "party": "D", "vote_share": runner_share, "won": False,
         "incumbent": False, "source": "test"},
    ]


def test_partisan_lean_from_results():
    results = _general(2024, 62.0, 36.0) + _general(2022, 58.0, 40.0) \
        + _general(2020, 55.0, 43.0)
    lean = partisan_lean(results)
    assert lean["lean_margin"] == pytest.approx((26 + 18 + 12) / 3, abs=0.1)
    assert lean["party"] == "R" and lean["trend"] == "widening"
    assert partisan_lean([]) is None                      # never invented


def test_primary_history_matches_member():
    results = [{"cycle": 2024, "stage": "primary", "candidate_name":
                "Winner Person", "party": "R", "vote_share": 71.0, "won": True,
                "incumbent": True, "source": "state SoS"}]
    hist = primary_history(results, "Winner Person")
    assert hist[0]["vote_share"] == 71.0 and hist[0]["won"]
    assert primary_history(results, "Somebody Else") == []


def test_seat_outlook_reasons_every_input():
    lean = {"lean_margin": 20.0, "party": "R", "cycles": [2024, 2022],
            "per_cycle": [], "trend": "stable", "basis": "x"}
    strong = seat_outlook(lean, 22.0, True, 900_000.0, 50_000.0)
    assert strong["label"] == "safe-context"
    assert any("won last general by 22" in r for r in strong["reasons"])
    assert strong["note"] == "context, not a forecast"
    # well-funded challenger + open seat drags it down
    weak = seat_outlook(None, 3.0, False, None, None)
    assert weak["label"] == "competitive-context"
    assert any("open seat" in r for r in weak["reasons"])
    outraised = seat_outlook(lean, 12.0, True, 100_000.0, 400_000.0)
    assert any("out-raised" in r for r in outraised["reasons"])
    # missing data never crashes and is visible
    empty = seat_outlook(None, None, None, None, None)
    assert empty["inputs_seen"]["fec_finance"] is False


def test_attribution_and_sentiment_notes_are_honest():
    assert "not who caused it" in ATTRIBUTION_NOTE
    assert "Community Project Funding" in ATTRIBUTION_NOTE
    assert "does not scrape or estimate voter sentiment" in SENTIMENT_NOTE
    assert "not an election forecast" in SENTIMENT_NOTE
    assert "fact about the" in rank_note("Department of Defense")


def test_geo_adapter_parses_shape_codes():
    data = {"results": [
        {"shape_code": "AL05", "aggregated_amount": 1234567.0},
        {"shape_code": "WY00", "aggregated_amount": 999.0},
        {"shape_code": "XX", "aggregated_amount": 5},          # malformed
        {"shape_code": "TX1A", "aggregated_amount": 5},        # malformed
        {"shape_code": "CA12", "aggregated_amount": 0},        # zero dropped
    ]}
    rows = parse_results(data)
    assert {(r["state"], r["district"]) for r in rows} == {("AL", 5), ("WY", 0)}
    assert parse_results({}) == []


@pytest.fixture
def env():
    store = MemoryStore()
    app.state.store = store
    uid, oid = store.create_user_with_org("u@example.com", hash_password(PASSWORD), "org")
    token, th, exp = new_session_token()
    store.create_session(uid, th, exp)
    client = TestClient(app, follow_redirects=False)
    client.cookies.set(SESSION_COOKIE, token)
    yield client, store, {"user_id": uid, "org_id": oid, "token": token}
    app.state.store = None


def test_district_rankings_page(env):
    client, store, _ = env
    store.district_rows = [
        {"state": "AL", "district": 5, "fiscal_year": 2026, "agency": "",
         "obligations": 9e9, "award_count": None, "bioguide_id": "S001220",
         "rep_name": f"Rep {PAYLOAD} Person", "party": "R"},
        {"state": "VA", "district": 11, "fiscal_year": 2026, "agency": "",
         "obligations": 8e9, "award_count": None, "bioguide_id": None,
         "rep_name": None, "party": None},
    ]
    html = client.get("/app/districts").text
    assert "AL-05" in html and "VA-11" in html
    assert "$9,000,000,000" in html
    assert "<script>" not in html and "&lt;script&gt;" in html
    assert "not who caused it" in html                     # attribution rendered


def test_district_profile_page_full_context(env):
    client, store, _ = env
    store.district_profiles[("AL", 5)] = {
        "state": "AL", "district": 5,
        "rep": {"bioguide_id": "S001220", "full_name": "Dale Strong",
                "party": "R", "committees": []},
        "spending": [
            {"fiscal_year": 2026, "agency": "", "obligations": 9e9},
            {"fiscal_year": 2025, "agency": "", "obligations": 8e9},
            {"fiscal_year": 2026, "agency": "Department of Defense",
             "obligations": 6e9},
            {"fiscal_year": 2026,
             "agency": "National Aeronautics and Space Administration",
             "obligations": 2e9}],
        "election_results": _general(2024, 60.0, 38.0)
            + _general(2022, 64.0, 34.0)
            + [{"cycle": 2024, "stage": "primary", "candidate_name":
                "Dale Strong", "party": "R", "vote_share": 68.0, "won": True,
                "incumbent": True, "source": "AL SoS"}],
        "directed": [{"fiscal_year": 2025, "member_name": "Dale Strong",
                      "project": f"Range modernization {PAYLOAD}",
                      "amount": 4_000_000.0, "agency": "DoD",
                      "source": "House Approps FY25 CPF table"}],
        "finance": [
            {"candidate_name": "Dale Strong", "is_incumbent": True,
             "receipts": 1_200_000.0, "cash_on_hand": 800_000.0, "cycle": 2026},
            {"candidate_name": "New Challenger", "is_incumbent": False,
             "receipts": 150_000.0, "cash_on_hand": 90_000.0, "cycle": 2026}],
    }
    html = client.get("/app/districts/AL/5").text
    assert "Computed partisan lean" in html
    assert "primary history" in html and "68.0%" in html
    assert "Seat outlook" in html and "context, not a forecast" in html
    assert "incumbent" in html and "$800,000" in html      # FEC cash shown
    assert "Congressionally directed spending" in html
    assert "does not scrape or estimate voter sentiment" in html
    assert "<script>" not in html and "&lt;script&gt;" in html


def test_districts_gated_by_plan(env):
    client, store, ctx = env
    store.plans[ctx["org_id"]] = "scout"
    assert client.get("/app/districts").status_code == 403
    assert client.get("/app/districts/AL/5").status_code == 403
