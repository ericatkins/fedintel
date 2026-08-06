"""Action-link handler security + web XSS escaping through real routes."""
import time

import pytest
from fastapi.testclient import TestClient

import src.actions as actions_mod
from src.actions import sign
from src.web.app import SESSION_COOKIE, app
from src.web.auth import hash_password, new_session_token
from src.web.store import MemoryStore

PAYLOAD = "<script>alert(1)</script><img src=x onerror=alert(2)>"


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setattr(actions_mod, "ACTION_BASE_URL", "https://app.fedintel.example")
    monkeypatch.setattr(actions_mod, "ACTION_SECRET", "s3cr3t")
    store = MemoryStore()
    app.state.store = store
    uid, oid = store.create_user_with_org("a@example.com", hash_password("long password ok"),
                                          "org")
    token, token_hash, exp = new_session_token()
    store.create_session(uid, token_hash, exp)
    store.opportunities[1] = {"id": 1, "title": "Opp", "agency": "Army", "score": 90,
                              "source_notice_id": "abc"}
    client = TestClient(app, follow_redirects=False)
    yield client, store, {"org_id": oid, "token": token}
    app.state.store = None


def test_action_get_confirms_without_state_change(env):
    """Email scanners prefetch GETs — a GET must NEVER change state."""
    client, store, ctx = env
    tok, exp = sign(1, "track", sub=5, org=ctx["org_id"])
    r = client.get(f"/a/1/track?t={tok}&e={exp}&s=5&o={ctx['org_id']}")
    assert r.status_code == 200
    assert "Confirm" in r.text and "Nothing has happened yet" in r.text
    assert not store.feedback and not store.tracked   # no side effects


def test_action_post_commits_with_org_from_token(env):
    client, store, ctx = env
    client.cookies.clear()                            # works logged-out
    tok, exp = sign(1, "track", sub=5, org=ctx["org_id"])
    r = client.post("/a/1/track", data={"t": tok, "e": exp, "s": 5, "o": ctx["org_id"]})
    assert r.status_code == 200 and "watchlist" in r.text.lower()
    assert store.feedback[0]["action"] == "track"
    assert store.feedback[0]["org_id"] == ctx["org_id"]   # org from signed token
    assert store.tracked[(ctx["org_id"], 1)] == "watching"
    assert store.matches[(ctx["org_id"], 1)]["status"] == "watching"


def test_tampered_and_expired_action_links_rejected(env):
    client, store, ctx = env
    org = ctx["org_id"]
    tok, exp = sign(1, "track", sub=0, org=org)
    for bad in (f"/a/1/ignore?t={tok}&e={exp}&s=0&o={org}",   # action swapped
                f"/a/2/track?t={tok}&e={exp}&s=0&o={org}",    # opp swapped
                f"/a/1/track?t={tok}&e={exp}&s=1&o={org}",    # sub swapped
                f"/a/1/track?t={tok}&e={exp}&s=0&o={org + 1}"):  # org swapped
        assert "invalid or has expired" in client.get(bad).text, bad
    old_exp = int(time.time()) - 10
    old_tok, _ = sign(1, "track", sub=0, org=org, exp=old_exp)
    assert "invalid or has expired" in client.post(
        "/a/1/track", data={"t": old_tok, "e": old_exp, "s": 0, "o": org}).text
    assert not store.feedback


def test_unknown_action_rejected(env):
    client, _, ctx = env
    tok, exp = sign(1, "delete_everything", sub=0, org=ctx["org_id"])
    assert "invalid or has expired" in client.get(
        f"/a/1/delete_everything?t={tok}&e={exp}&s=0&o={ctx['org_id']}").text


def test_opportunity_detail_escapes_hostile_opportunity_and_dossier(env):
    client, store, ctx = env
    client.cookies.set(SESSION_COOKIE, ctx["token"])
    store.opportunities[2] = {"id": 2, "title": f"Evil {PAYLOAD}", "agency": PAYLOAD,
                              "score": 90, "source_notice_id": "abc",
                              "description_text": PAYLOAD}
    store.dossiers[2] = {
        "snapshot": {"what_this_is": PAYLOAD},
        "buyer_profile": {"resolution": {"claim": PAYLOAD, "confidence": 50},
                          "labels": [PAYLOAD], "windows": {}},
        "similar_work": [],
        "last_10_relevant_awards": [{"award_date": "2024-01-01", "vendor": PAYLOAD,
                                     "title": PAYLOAD, "obligated_amount": 1.0,
                                     "similarity_score": 50, "reason_matched": [PAYLOAD]}],
        "incumbent_analysis": {"incumbent_status": "likely_incumbent",
                               "likely_incumbent_name": PAYLOAD, "incumbent_confidence": 60,
                               "confidence_band": "moderate signal",
                               "supporting_evidence": [PAYLOAD], "caveats": [PAYLOAD]},
        "work_origin_assessment": {"work_origin_assessment": "unclear", "confidence": 30},
        "funding_context": {"label": PAYLOAD, "confidence": 10, "caveats": [PAYLOAD]},
        "market_size": {"trend": PAYLOAD, "yoy_change_pct": None},
        "competition_landscape": {"label": PAYLOAD, "top3_share_pct": None,
                                  "vendors": [{"vendor_name": PAYLOAD, "obligations": 1.0,
                                               "award_count": 1, "last_award_date": None}]},
        "acquisition_pattern": {},
        "pursuit_recommendation": {"recommendation": PAYLOAD, "confidence": 50,
                                   "top_reasons": [PAYLOAD], "top_risks": [PAYLOAD],
                                   "next_actions": []},
        "data_quality": [PAYLOAD],
    }
    html = client.get("/app/opportunities/2").text
    assert "<script>" not in html
    assert "<img" not in html
    assert "&lt;script&gt;" in html


def test_opportunities_table_escapes_hostile_titles(env):
    client, store, ctx = env
    client.cookies.set(SESSION_COOKIE, ctx["token"])
    store.opportunities[3] = {"id": 3, "title": PAYLOAD, "agency": PAYLOAD, "score": 95,
                              "source_notice_id": "x"}
    html = client.get("/app/opportunities").text
    assert "<script>" not in html and "<img" not in html
    assert "&lt;script&gt;" in html


def test_security_headers_present(env):
    client, _, _ = env
    r = client.get("/login")
    assert "default-src 'self'" in r.headers["content-security-policy"]
    assert r.headers["x-frame-options"] == "DENY"


def test_static_route_rejects_traversal(env):
    client, _, _ = env
    assert client.get("/static/..%2Fapp.py").status_code in (404, 400)
    assert client.get("/static/app.css").status_code == 200
