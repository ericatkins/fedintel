"""Delegation intelligence: place parsing, committee relevance, truthful
funding labels, confidence tiers, entitlement gating, XSS safety."""
import pytest
from fastapi.testclient import TestClient

from src.intel.delegation import (
    COMPLIANCE_NOTE,
    STAFF_ROLE_PLAYBOOK,
    committee_relevance,
    engagement_windows,
    format_funding_label,
    parse_place,
    resolve_confidence,
)
from src.web.app import SESSION_COOKIE, app
from src.web.auth import hash_password, new_session_token
from src.web.store import MemoryStore

PASSWORD = "a long enough password"
PAYLOAD = "<script>alert(1)</script>"


def test_parse_place_variants():
    assert parse_place("Huntsville, AL") == {
        "city": "Huntsville", "state": "AL", "zip": None,
        "place_key": "huntsville|AL|"}
    p = parse_place("Huntsville, AL 35808")
    assert p["zip"] == "35808" and p["state"] == "AL" and p["city"] == "Huntsville"
    assert parse_place("AL")["state"] == "AL"
    assert parse_place("AL")["city"] is None
    assert parse_place("Nowhere Special")["state"] is None
    assert parse_place(None)["place_key"] is None
    # a city containing a comma keeps its text
    assert parse_place("Fort Worth, TX")["city"] == "Fort Worth"


def test_committee_relevance_maps_agency_to_seats():
    member = [{"code": "SSAS", "name": "Senate Committee on Armed Services",
               "title": None, "rank": 5},
              {"code": "SSAF", "name": "Senate Committee on Agriculture",
               "title": None, "rank": 2}]
    hits = committee_relevance("DEPT OF THE ARMY", member)
    assert len(hits) == 1 and hits[0]["code"] == "SSAS"
    assert "NDAA" in hits[0]["why"]
    # subcommittee codes roll up to the parent committee
    sub = [{"code": "HSAP07", "name": "House Appropriations (subcommittee 07)",
            "title": None, "rank": 1}]
    hits = committee_relevance("DEFENSE LOGISTICS AGENCY", sub)
    assert hits and hits[0]["code"] == "HSAP07"
    # small business committees are always relevant
    sb = [{"code": "HSSM", "name": "House Committee on Small Business",
           "title": "Chair", "rank": 1}]
    assert committee_relevance("NATIONAL PARK SERVICE", sb)
    # no seats → no hits, never invented
    assert committee_relevance("DEPT OF THE ARMY", []) == []


def test_funding_labels_never_say_company_donated():
    label = format_funding_label("employer_aggregate")
    assert "individual contributions" in label and "employer" in label
    assert "donated" not in label.lower()
    assert "PAC" in format_funding_label("pac")
    assert "cannot contribute" in COMPLIANCE_NOTE
    assert "FAR 3.104" in COMPLIANCE_NOTE          # procurement integrity named


def test_confidence_tiers():
    assert resolve_confidence("address_geocode") == 90
    assert resolve_confidence("city_geocode") == 60
    assert resolve_confidence("state_only") == 0
    assert resolve_confidence("made_up") == 0


def test_engagement_windows_cover_appropriations_and_ndaa():
    import datetime
    windows = engagement_windows(datetime.date(2026, 7, 15))
    names = " ".join(w["window"] for w in windows)
    assert "appropriations" in names and "NDAA" in names and "Q4" in names
    winter = engagement_windows(datetime.date(2026, 11, 15))
    assert any("Continuing-resolution" in w["window"] for w in winter)


def test_staff_playbook_is_roles_not_names():
    joined = " ".join(r["ask_for"] for r in STAFF_ROLE_PLAYBOOK)
    assert "Military Legislative Assistant" in joined
    assert "District/State Director" in joined


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


def _member(name=f"Evil {PAYLOAD} Member"):
    return {"id": 1, "bioguide_id": "X000001", "full_name": name, "chamber": "sen",
            "state": "AL", "district": None, "party": "R", "phone": "202-224-0000",
            "office": "1 Senate Bldg", "website": "https://example.senate.gov",
            "contact_form": None, "state_rank": "senior", "updated_at": None,
            "committees": [{"code": "SSAS",
                            "name": f"Armed {PAYLOAD} Services",
                            "title": None, "rank": 1}],
            "staff": [{"name": f"Chief {PAYLOAD}", "title": "Chief of Staff",
                       "role_tag": None, "email": None,
                       "source": "operator import", "source_date": None}],
            "funding": [{"cycle": 2026, "kind": "employer_aggregate",
                         "contributor_name": f"MegaCorp {PAYLOAD}",
                         "total": 50000.0, "contribution_count": 40}]}


def test_legislator_page_escapes_hostile_data(env):
    client, store, _ = env
    store.legislators["X000001"] = _member()
    html = client.get("/app/legislators/X000001").text
    assert "<script>" not in html and "&lt;script&gt;" in html
    assert "individual contributions" in html      # truthful basis rendered
    assert "cannot contribute" in html             # compliance note rendered
    assert "Military Legislative Assistant" in html


def test_delegation_panel_on_detail_with_confidence_badge(env):
    client, store, _ = env
    store.opportunities[1] = {"id": 1, "title": "Opp", "agency": "DEPT OF THE ARMY",
                              "score": 90, "source_notice_id": "x"}
    store.delegations[1] = [
        {"bioguide_id": "X000001", "full_name": "Jane Senator", "chamber": "sen",
         "state": "AL", "district": None, "party": "R", "phone": None,
         "website": None, "state_rank": "senior", "match_method": "state",
         "match_confidence": 95,
         "committee_relevance": [{"code": "SSAS",
                                  "name": "Senate Committee on Armed Services",
                                  "why": "authorizes DoD programs (NDAA)"}]},
        {"bioguide_id": "X000002", "full_name": "Joe Rep", "chamber": "rep",
         "state": "AL", "district": 5, "party": "R", "phone": None,
         "website": None, "state_rank": None, "match_method": "city_geocode",
         "match_confidence": 60, "committee_relevance": []},
    ]
    html = client.get("/app/opportunities/1").text
    assert "Congressional delegation" in html
    assert "Jane Senator" in html and "Armed Services" in html
    assert "district estimated" in html            # 60-confidence honesty badge


def test_delegation_gated_by_plan(env):
    client, store, ctx = env
    store.plans[ctx["org_id"]] = "scout"
    store.legislators["X000001"] = _member("Plain Name")
    assert client.get("/app/legislators/X000001").status_code == 403
    store.opportunities[1] = {"id": 1, "title": "Opp", "agency": "Army",
                              "score": 90, "source_notice_id": "x"}
    store.delegations[1] = [dict(_member("Plain Name"), match_method="state",
                                 match_confidence=95, committee_relevance=[])]
    html = client.get("/app/opportunities/1").text
    assert "Congressional delegation" not in html  # panel absent on scout
