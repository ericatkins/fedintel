"""Grants vertical foundation: normalization, detail merge, and the page's
honesty rules (keyword relevance is not a fit assessment)."""
import pytest
from fastapi.testclient import TestClient

from src.adapters.grants_gov import apply_detail, normalize_search_hit
from src.web.app import SESSION_COOKIE, app
from src.web.auth import hash_password, new_session_token
from src.web.store import MemoryStore

HIT = {"id": 358800, "number": "USDA-NIFA-2026-01",
       "title": "Rural Data Infrastructure Grants",
       "agencyCode": "USDA-NIFA", "agencyName": "National Institute of Food "
       "and Agriculture", "oppStatus": "posted", "openDate": "2026-07-01",
       "closeDate": "2026-10-15", "alist": ["10.310"]}

DETAIL = {"synopsis": {
    "awardFloor": "100000", "awardCeiling": "750,000",
    "expectedNumberOfAwards": "12", "estimatedFunding": "9000000",
    "costSharing": "Yes",
    "applicantTypes": [{"id": "06", "description":
                        "Public and State controlled institutions of higher "
                        "education"}],
    "fundingInstruments": [{"id": "G", "description": "Grant"}],
    "synopsisDesc": "Data infrastructure for rural research networks."}}


def test_normalize_search_hit_is_thin_but_sourced():
    rec = normalize_search_hit(HIT)
    assert rec["source"] == "grants_gov"
    assert rec["source_grant_id"] == "358800"
    assert rec["opportunity_number"] == "USDA-NIFA-2026-01"
    assert rec["opportunity_status"] == "posted"
    assert rec["assistance_listings"] == ["10.310"]
    assert rec["award_ceiling"] is None          # thin until detail merges
    assert rec["source_url"].endswith("/358800")
    assert rec["content_hash"]


def test_apply_detail_merges_synopsis():
    rec = apply_detail(normalize_search_hit(HIT), DETAIL)
    assert rec["award_floor"] == 100_000
    assert rec["award_ceiling"] == 750_000
    assert rec["expected_awards"] == 12
    assert rec["total_funding"] == 9_000_000
    assert rec["cost_sharing"] is True
    assert rec["funding_instrument"] == "grant"
    assert "higher education" in rec["eligible_applicants"][0]
    assert rec["raw_json"]["detail"] == DETAIL


PASSWORD = "a long enough password"


@pytest.fixture
def grants_env():
    store = MemoryStore()
    app.state.store = store
    uid, oid = store.create_user_with_org("g@example.com",
                                          hash_password(PASSWORD), "Org")
    token, token_hash, exp = new_session_token()
    store.create_session(uid, token_hash, exp)
    store.profiles[oid] = {"keywords_boost": ["data infrastructure"],
                           "capabilities": ["research networks"]}
    store.grants = [
        {"id": 1, "source": "grants_gov", "source_grant_id": "358800",
         "opportunity_number": "USDA-NIFA-2026-01",
         "title": "Rural Data Infrastructure Grants",
         "agency_code": "USDA-NIFA", "agency_name": "NIFA",
         "assistance_listings": ["10.310"], "opportunity_status": "posted",
         "posted_date": "2026-07-01", "close_date": "2026-10-15",
         "award_floor": 100_000, "award_ceiling": 750_000,
         "expected_awards": 12, "total_funding": 9_000_000,
         "funding_instrument": "grant",
         "eligible_applicants": ["institutions of higher education"],
         "cost_sharing": True,
         "description_text": "Data infrastructure for rural research networks.",
         "source_url": None, "last_seen_at": "now"}]
    client = TestClient(app, follow_redirects=False)
    client.cookies.set(SESSION_COOKIE, token)
    yield client, store, oid
    app.state.store = None


def test_grants_page_renders_with_honest_relevance_labeling(grants_env):
    client, store, oid = grants_env
    page = client.get("/app/grants")
    assert page.status_code == 200
    assert "Rural Data Infrastructure Grants" in page.text
    assert "up to $750,000" in page.text
    assert "data, infrastructure" in page.text or "data" in page.text
    # honesty: relevance is labeled as keyword matching, not fit
    assert "not" in page.text and "eligibility or readiness assessment" in page.text
    # vertical separation stated on the page
    assert "Contract scoring is never applied here" in page.text


def test_grants_gated_for_scout_plan(grants_env):
    client, store, oid = grants_env
    store.plans[oid] = "scout"
    assert client.get("/app/grants").status_code == 403
