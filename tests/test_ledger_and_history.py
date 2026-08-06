"""Evidence ledger assembly and amendment-history rendering."""
import pytest
from fastapi.testclient import TestClient

from src.intel.ledger import build_evidence_ledger
from src.web.app import SESSION_COOKIE, app
from src.web.auth import hash_password, new_session_token
from src.web.store import MemoryStore

OPP = {"source_notice_id": "N123", "url": "https://sam.gov/opp/N123/view",
       "last_seen_at": "2026-08-05T10:00:00Z"}


def test_ledger_always_includes_the_notice():
    rows = build_evidence_ledger(OPP, None, None, None)
    assert rows[0]["source_title"] == "Opportunity notice"
    assert rows[0]["identifier"] == "N123"
    assert rows[0]["limitations"]


def test_ledger_flags_unextracted_documents():
    docs = [{"filename": "pws.pdf", "fetch_status": "extracted",
             "source_url": "https://sam.gov/x", "sha256": "ab" * 32,
             "fetched_at": "2026-08-01"},
            {"filename": "scan.pdf", "fetch_status": "failed",
             "source_url": "https://sam.gov/y"}]
    rows = build_evidence_ledger(OPP, None, docs, None)
    extracted = next(r for r in rows if r["source_title"] == "pws.pdf")
    failed = next(r for r in rows if r["source_title"] == "scan.pdf")
    assert "compliance matrix" in extracted["used_by"]
    assert failed["limitations"] and "not extracted" in failed["limitations"]


def test_ledger_funding_row_only_with_defensible_link():
    d_none = {"similar_work": [], "funding_context": {"label_key": "none"},
              "generated_at": "2026-08-05"}
    rows = build_evidence_ledger(OPP, d_none, None, None)
    assert not any("Federal account" in r["source_title"] for r in rows)
    d_ok = {"similar_work": [1, 2], "funding_context":
            {"label_key": "likely", "label": "Likely related funding account"},
            "generated_at": "2026-08-05"}
    rows = build_evidence_ledger(OPP, d_ok, None, None)
    fund = next(r for r in rows if "Federal account" in r["source_title"])
    assert "not evidence" in fund["limitations"]


PASSWORD = "a long enough password"


@pytest.fixture
def client_env():
    store = MemoryStore()
    app.state.store = store
    uid, oid = store.create_user_with_org("u@example.com",
                                          hash_password(PASSWORD), "Org")
    token, token_hash, exp = new_session_token()
    store.create_session(uid, token_hash, exp)
    store.opportunities[1] = {"id": 1, "title": "Opp", "agency": "Army",
                              "score": 80, "source_notice_id": "abc",
                              "url": "https://sam.gov/opp/abc/view"}
    store.opp_change_events = [
        {"opportunity_id": 1, "event_type": "deadline_change",
         "detail": {"field": "response_deadline", "old": "2026-08-01",
                    "new": "2026-08-15"}, "created_at": "2026-07-20"},
        {"opportunity_id": 1, "event_type": "stage_transition",
         "detail": {"from": "Sources Sought", "to": "Solicitation"},
         "created_at": "2026-07-01"},
    ]
    client = TestClient(app, follow_redirects=False)
    client.cookies.set(SESSION_COOKIE, token)
    yield client
    app.state.store = None


def test_opportunity_page_renders_history_and_ledger(client_env):
    page = client_env.get("/app/opportunities/1")
    assert page.status_code == 200
    assert "Amendment &amp; change history" in page.text
    assert "response deadline" in page.text
    assert "2026-08-15" in page.text
    assert "Stage change:" in page.text
    assert "Evidence &amp; source ledger" in page.text
    assert "Opportunity notice" in page.text
