"""Forecast normalization, CSV provenance rule, forecast-opportunity linking,
competitive/teaming intelligence, and the demand radar page."""
import pytest
from fastapi.testclient import TestClient

from src.adapters.forecasts import ForecastError, _dollar_range, normalize_apfs, parse_forecast_csv
from src.intel.competitors import build_competitive_teaming
from src.intel.forecast_link import link_forecasts, score_forecast_link
from src.web.app import SESSION_COOKIE, app
from src.web.auth import hash_password, new_session_token
from src.web.store import MemoryStore

APFS_RECORD = {
    "apfs_number": "12345", "component": "CISA",
    "title": "Zero Trust Engineering Support",
    "description": "Network security engineering and continuous monitoring.",
    "naics": "541512", "dollar_range": "$1,000,000 to $5,000,000",
    "action_type": "Recompete", "incumbent_contractor": "Legacy Cyber Inc",
    "small_business_program": "8(a) Set-Aside",
    "estimated_solicitation_release_date": "2027-01-15",
    "fiscal_year": "2027", "place_of_performance": "Arlington, VA",
}


def test_normalize_apfs_maps_fields_and_keeps_raw():
    rec = normalize_apfs(APFS_RECORD)
    assert rec["source"] == "dhs_apfs" and rec["source_record_id"] == "12345"
    assert rec["estimated_value_low"] == 1_000_000
    assert rec["estimated_value_high"] == 5_000_000
    assert rec["action_type"] == "recompete"
    assert rec["incumbent_name"] == "Legacy Cyber Inc"
    assert rec["anticipated_solicitation"] == "2027-01-15"
    assert rec["fiscal_year"] == 2027
    assert rec["raw_json"] == APFS_RECORD and rec["content_hash"]


def test_dollar_range_variants():
    assert _dollar_range("$250,000 to $500,000") == (250_000, 500_000)
    assert _dollar_range("$1M - $5M") == (1e6, 5e6)
    assert _dollar_range("garbage") == (None, None)
    assert _dollar_range(None) == (None, None)


def test_csv_import_rejects_rows_without_provenance(tmp_path):
    path = tmp_path / "f.csv"
    path.write_text("source_record_id,agency,title,source_url\n"
                    "A1,USDA,Forest inventory system,\n")
    with pytest.raises(ForecastError, match="provenance"):
        list(parse_forecast_csv(str(path)))


def test_csv_import_normalizes_valid_rows(tmp_path):
    path = tmp_path / "f.csv"
    path.write_text(
        "source_record_id,agency,title,source_url,naics,action_type,"
        "anticipated_solicitation,estimated_value_low\n"
        "A1,USDA,Forest inventory system,https://usda.gov/forecast,541512,"
        "recompete,2026-11-01,750000\n")
    rows = list(parse_forecast_csv(str(path)))
    assert rows[0]["source"] == "csv_import"
    assert rows[0]["action_type"] == "recompete"
    assert rows[0]["estimated_value_low"] == 750_000
    assert rows[0]["anticipated_solicitation"] == "2026-11-01"


OPP = {"title": "Enterprise inventory management modernization",
       "description_text": "web modernization, dashboards, data migration",
       "agency": "DEPT OF THE ARMY", "office": "ARMY CONTRACTING COMMAND",
       "naics": "541512", "posted_date": "2026-08-01"}


def _forecast(**kw):
    fc = {"id": 1, "agency": "DEPT OF THE ARMY",
          "office": "ARMY CONTRACTING COMMAND",
          "title": "Inventory management system modernization recompete",
          "description": "dashboards, workflow automation, data migration",
          "naics": "541512", "anticipated_solicitation": "2026-06-15"}
    fc.update(kw)
    return fc


def test_forecast_link_scores_with_evidence():
    ln = score_forecast_link(OPP, _forecast())
    assert ln and ln["similarity_score"] >= 45
    joined = " ".join(ln["evidence"])
    assert "same agency" in joined and "NAICS" in joined


def test_forecast_link_rejects_unrelated():
    unrelated = _forecast(agency="NASA", office=None, naics="236220",
                          title="Roof replacement",
                          description="roofing construction services")
    assert score_forecast_link(OPP, unrelated) is None
    assert link_forecasts(OPP, [unrelated]) == []


def test_forecast_link_needs_more_than_one_signal():
    # agency alone (one evidence item) must never produce a link
    weak = _forecast(naics=None, title="Completely different requirement",
                     description="janitorial services", office=None,
                     anticipated_solicitation=None)
    assert score_forecast_link(OPP, weak) is None


# ---- competitive / teaming ----

def _award(vendor, date="2025-06-01", amount=2_000_000, set_aside="SB"):
    return {"recipient_name": vendor, "award_date": date,
            "obligated_amount": amount, "set_aside": set_aside}


def test_competitors_ranked_with_incumbent_marked():
    awards = [_award("ACME", "2025-06-01"), _award("ACME", "2024-03-01"),
              _award("BETA", "2019-01-01")]
    ct = build_competitive_teaming({"set_aside": None}, awards,
                                   {"likely_incumbent_name": "ACME"})
    assert ct["status"] == "ok"
    top = ct["competitors"][0]
    assert top["vendor"] == "ACME" and top["is_incumbent"]
    beta = next(c for c in ct["competitors"] if c["vendor"] == "BETA")
    assert "historical performer" in beta["read"]


def test_set_aside_opportunity_flags_large_performer_as_partner():
    awards = [_award("BIGCO", set_aside=None), _award("BIGCO", set_aside=None),
              _award("SMALLCO", amount=300_000)]
    ct = build_competitive_teaming({"set_aside": "Total Small Business"},
                                   awards, {})
    partners = [p["vendor"] for p in ct["teaming_candidates"]]
    assert "BIGCO" in partners
    bigco = next(p for p in ct["teaming_candidates"] if p["vendor"] == "BIGCO")
    assert any("cannot prime this set-aside" in e for e in bigco["evidence"])


def test_competitors_empty_pool_is_insufficient_not_invented():
    ct = build_competitive_teaming({}, [], {})
    assert ct["status"] == "insufficient_data"
    assert ct["competitors"] == []
    assert any("public prime-award" in c.lower() or "candidates" in c
               for c in ct["caveats"])


def test_competitors_always_disclose_subaward_limitation():
    ct = build_competitive_teaming({}, [_award("X")], {})
    assert any("Subcontract relationships" in c for c in ct["caveats"])


# ---- demand radar page ----

PASSWORD = "a long enough password"


@pytest.fixture
def radar_env():
    store = MemoryStore()
    app.state.store = store
    uid, oid = store.create_user_with_org("r@example.com",
                                          hash_password(PASSWORD), "Org")
    token, token_hash, exp = new_session_token()
    store.create_session(uid, token_hash, exp)
    store.forecasts = [
        {"id": 1, "source": "csv_import", "source_record_id": "F1",
         "agency": "DEPT OF THE ARMY", "subtier": "DEPT OF THE ARMY",
         "office": None, "title": "Inventory system recompete",
         "description": "software modernization", "naics": "541512",
         "estimated_value_low": 1e6, "estimated_value_high": 2e6,
         "action_type": "recompete", "incumbent_name": "Northstar Data LLC",
         "anticipated_solicitation": "2026-10-01", "fiscal_year": 2026,
         "point_of_contact": None, "source_url": None, "last_seen_at": "now",
         "set_aside": None}]
    client = TestClient(app, follow_redirects=False)
    client.cookies.set(SESSION_COOKIE, token)
    yield client, store, oid
    app.state.store = None


def test_radar_page_lists_forecasts_with_fit_score(radar_env):
    client, store, oid = radar_env
    page = client.get("/app/radar")
    assert page.status_code == 200
    assert "Inventory system recompete" in page.text
    assert "Northstar Data LLC" in page.text
    assert "planning statements, not" in page.text     # honesty note


def test_radar_gated_for_scout_plan(radar_env):
    client, store, oid = radar_env
    store.plans[oid] = "scout"
    assert client.get("/app/radar").status_code == 403
