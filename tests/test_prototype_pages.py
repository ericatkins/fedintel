"""Prototype surface: agencies/vendors/reports/admin pages, early-access gating,
lifecycle timeline, CSV export (incl. formula-injection defense), full smoke run."""
import pytest
from fastapi.testclient import TestClient

from src.web.app import SESSION_COOKIE, app
from src.web.auth import hash_password, new_session_token
from src.web.store import MemoryStore

PASSWORD = "a long enough password"
PAYLOAD = "<script>alert(1)</script>"


@pytest.fixture
def env():
    store = MemoryStore()
    app.state.store = store
    uid, oid = store.create_user_with_org("user@example.com", hash_password(PASSWORD), "org")
    token, token_hash, exp = new_session_token()
    store.create_session(uid, token_hash, exp)
    client = TestClient(app, follow_redirects=False)
    client.cookies.set(SESSION_COOKIE, token)
    yield client, store, {"user_id": uid, "org_id": oid, "token": token}
    app.state.store = None


def test_new_pages_require_auth(env):
    client, _, _ = env
    client.cookies.clear()
    for path in ("/app/agencies", "/app/vendors", "/app/reports", "/app/admin",
                 "/app/opportunities.csv"):
        r = client.get(path)
        assert r.status_code == 303 and r.headers["location"] == "/login", path


def test_agencies_and_vendors_pages_render_and_escape(env):
    client, store, _ = env
    store.agencies[1] = {"id": 1, "office": f"Evil {PAYLOAD} Office", "subtier": "Army",
                         "department": "DoD", "obligations": 5e6, "awards": 3,
                         "latest_fy": 2026, "confidence": 70, "org_code": None,
                         "path": None, "location": None, "stats": [], "recent_awards": []}
    store.vendors[1] = {"id": 1, "name": f"Evil {PAYLOAD} Corp", "uei": "U1",
                        "obligations": 9e6, "awards": 4, "first_award": "2021-01-01",
                        "last_award": "2026-01-01", "top_agencies": [], "top_naics": [],
                        "top_offices": []}
    for path in ("/app/agencies", "/app/agencies/1", "/app/vendors", "/app/vendors/1"):
        html = client.get(path).text
        assert "<script>" not in html and "&lt;script&gt;" in html, path


def test_vendor_search_filters(env):
    client, store, _ = env
    store.vendors[1] = {"id": 1, "name": "Acme Data", "uei": None, "obligations": 1,
                        "awards": 1, "first_award": None, "last_award": None,
                        "top_agencies": [], "top_naics": [], "top_offices": []}
    store.vendors[2] = {"id": 2, "name": "Zulu Systems", "uei": None, "obligations": 1,
                        "awards": 1, "first_award": None, "last_award": None,
                        "top_agencies": [], "top_naics": [], "top_offices": []}
    html = client.get("/app/vendors?q=acme").text
    assert "Acme Data" in html and "Zulu Systems" not in html


def test_reports_page_shows_pipeline(env):
    client, store, ctx = env
    store.opportunities[1] = {"id": 1, "title": "Tracked Opp", "agency": "Army", "score": 90,
                              "source_notice_id": "x"}
    store.set_tracked(ctx["org_id"], 1, "pursuing")
    html = client.get("/app/reports").text
    assert "Pursuit pipeline" in html and "Tracked Opp" in html and "pursuing" in html


def test_admin_page_gated_by_is_admin(env):
    client, store, ctx = env
    assert client.get("/app/admin").status_code == 403          # normal user
    store.admin_user_ids.add(ctx["user_id"])
    store.ops = {"failed_enrichments": [{"id": 9, "title": "Broken", "agency": "Army",
                                         "at": None}],
                 "failed_emails": [{"digest_date": "2026-07-06", "status": "failed",
                                    "error": "provider 500", "at": None}],
                 "enrichment_pending": 4}
    html = client.get("/app/admin").text
    assert "Broken" in html and "provider 500" in html and ">4<" in html


def test_csv_export_neutralizes_formula_injection(env):
    client, store, _ = env
    store.opportunities[1] = {"id": 1, "title": "=HYPERLINK(\"http://evil\")",
                              "agency": "+cmd", "score": 90, "source_notice_id": "x"}
    r = client.get("/app/opportunities.csv")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    body = r.text
    assert "'=HYPERLINK" in body    # leading formula chars are quoted
    assert "'+cmd" in body
    assert "\n=" not in body and ",=" not in body


def test_early_access_gating(env, monkeypatch):
    client, _, _ = env
    client.cookies.clear()
    monkeypatch.setenv("EARLY_ACCESS_CODE", "hsv-2026")
    assert "invite code" in client.get("/signup").text
    r = client.post("/signup", data={"email": "new@example.com", "password": PASSWORD,
                                     "org_name": "New Org", "access_code": "wrong"})
    assert "invite code is required" in r.text
    r = client.post("/signup", data={"email": "new@example.com", "password": PASSWORD,
                                     "org_name": "New Org", "access_code": "hsv-2026"})
    assert r.status_code == 303 and r.headers["location"] == "/onboarding"


def test_lifecycle_timeline_renders(env):
    client, store, _ = env
    store.opportunities[2] = {"id": 2, "title": "RFP Stage", "agency": "Army", "score": 90,
                              "source_notice_id": "n2", "solicitation_number": "W1-26-R-1"}
    store.lineage["W1-26-R-1"] = [
        {"opportunity_id": 1, "stage": "Sources Sought", "linked_at": None,
         "title": "Early", "posted_date": "2026-05-01"},
        {"opportunity_id": 2, "stage": "Solicitation", "linked_at": None,
         "title": "RFP Stage", "posted_date": "2026-07-01"},
    ]
    html = client.get("/app/opportunities/2").text
    assert "Lifecycle" in html and "Sources Sought" in html and "Solicitation" in html


def test_full_prototype_smoke(env, monkeypatch):
    """End-to-end: signup → onboarding → profile save → dashboard → table →
    detail (dossier pending) → status → watchlist → reports → alerts → logout."""
    client, store, _ = env
    client.cookies.clear()
    monkeypatch.delenv("EARLY_ACCESS_CODE", raising=False)
    r = client.post("/signup", data={"email": "founder@example.com", "password": PASSWORD,
                                     "org_name": "Founder Org"})
    assert r.status_code == 303 and r.headers["location"] == "/onboarding"
    session_tok = r.cookies[SESSION_COOKIE]
    client.cookies.set(SESSION_COOKIE, session_tok)
    from src.web.app import csrf_for
    assert "company profile" in client.get("/onboarding").text.lower()
    r = client.post("/app/profile", data={"csrf_token": csrf_for(session_tok),
                                          "name": "Founder Org",
                                          "capabilities": "custom software, dashboards",
                                          "industries": "", "naics_codes": "541511, 541512",
                                          "agencies_of_interest": "Army",
                                          "locations": "Huntsville, AL",
                                          "set_aside_eligibility": "small business",
                                          "keywords_boost": "inventory",
                                          "keywords_suppress": "", "excluded_categories": ""})
    assert "Profile saved" in r.text
    store.opportunities[1] = {"id": 1, "title": "Inventory Modernization", "agency": "Army",
                              "score": 88, "source_notice_id": "abc"}
    assert "Inventory Modernization" in client.get("/app").text
    assert "Inventory Modernization" in client.get("/app/opportunities").text
    detail = client.get("/app/opportunities/1").text
    assert "generation pending" in detail       # dossier not built yet → honest state
    r = client.post("/app/opportunities/1/status",
                    data={"status": "pursuing", "csrf_token": csrf_for(session_tok)})
    assert r.status_code == 303
    assert "pursuing" in client.get("/app/watchlist").text
    assert "Pursuit pipeline" in client.get("/app/reports").text
    assert client.get("/app/alerts").status_code == 200
    r = client.get("/logout")
    assert r.status_code == 303
    client.cookies.clear()
    assert client.get("/app").status_code == 303  # session revoked
