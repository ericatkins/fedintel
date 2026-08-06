"""Public-beta security: CSRF, rate limiting, verification, reset, logout-all,
unsubscribe, per-org feedback contract, API lockdown."""

import pytest
from fastapi.testclient import TestClient

import src.actions as actions_mod
from src.web.app import SESSION_COOKIE, app, csrf_for
from src.web.auth import hash_password, new_session_token, verify_password
from src.web.store import MemoryStore

PASSWORD = "a long enough password"


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setattr(actions_mod, "ACTION_BASE_URL", "https://app.fedintel.example")
    monkeypatch.setattr(actions_mod, "ACTION_SECRET", "s3cr3t")
    monkeypatch.setenv("ACTION_BASE_URL", "https://app.fedintel.example")
    monkeypatch.setenv("ACTION_SECRET", "s3cr3t")
    store = MemoryStore()
    app.state.store = store
    uid, oid = store.create_user_with_org("u@example.com", hash_password(PASSWORD), "org")
    token, token_hash, exp = new_session_token()
    store.create_session(uid, token_hash, exp)
    store.opportunities[1] = {"id": 1, "title": "Opp", "agency": "Army", "score": 90,
                              "source_notice_id": "x"}
    client = TestClient(app, follow_redirects=False)
    client.cookies.set(SESSION_COOKIE, token)
    yield client, store, {"user_id": uid, "org_id": oid, "token": token}
    app.state.store = None


def test_csrf_required_on_authenticated_posts(env):
    client, store, ctx = env
    r = client.post("/app/opportunities/1/status", data={"status": "pursuing"})
    assert r.status_code == 403                       # no token
    r = client.post("/app/opportunities/1/status",
                    data={"status": "pursuing", "csrf_token": "forged"})
    assert r.status_code == 403                       # wrong token
    assert not store.tracked
    r = client.post("/app/opportunities/1/status",
                    data={"status": "pursuing", "csrf_token": csrf_for(ctx["token"])})
    assert r.status_code == 303
    assert store.tracked[(ctx["org_id"], 1)] == "pursuing"


def test_csrf_token_is_session_bound(env):
    client, store, ctx = env
    other_token, th, exp = new_session_token()
    store.create_session(ctx["user_id"], th, exp)
    r = client.post("/app/profile", data={"csrf_token": csrf_for(other_token),
                                          "name": "x"})
    assert r.status_code == 403                       # token from another session


def test_login_rate_limited(env):
    client, _, _ = env
    client.cookies.clear()
    for _ in range(8):
        r = client.post("/login", data={"email": "u@example.com", "password": "wrong"})
        assert r.status_code == 200
    r = client.post("/login", data={"email": "u@example.com", "password": "wrong"})
    assert r.status_code == 429


def test_password_reset_flow_revokes_sessions(env, monkeypatch):
    client, store, ctx = env
    from src import tokens
    token, exp = tokens.sign("reset_password", a=ctx["user_id"])
    r = client.get(f"/reset?u={ctx['user_id']}&e={exp}&t={token}")
    assert "new password" in r.text.lower()
    r = client.post("/reset", data={"u": ctx["user_id"], "e": exp, "t": token,
                                    "password": "brand new password!"})
    assert "Password updated" in r.text
    assert verify_password("brand new password!",
                           store.users[ctx["user_id"]]["password_hash"])
    assert client.get("/app").status_code == 303      # old session revoked


def test_reset_rejects_tampered_token(env):
    client, _, ctx = env
    from src import tokens
    token, exp = tokens.sign("reset_password", a=ctx["user_id"])
    r = client.post("/reset", data={"u": ctx["user_id"] + 1, "e": exp, "t": token,
                                    "password": "brand new password!"})
    assert "invalid or has expired" in r.text
    # a verify_email token must not work as a reset token (purpose-bound)
    vt, ve = tokens.sign("verify_email", a=ctx["user_id"])
    r = client.post("/reset", data={"u": ctx["user_id"], "e": ve, "t": vt,
                                    "password": "brand new password!"})
    assert "invalid or has expired" in r.text


def test_email_verification(env):
    client, store, ctx = env
    from src import tokens
    token, exp = tokens.sign("verify_email", a=ctx["user_id"])
    r = client.get(f"/verify?u={ctx['user_id']}&e={exp}&t={token}")
    assert "verified" in r.text.lower()
    assert store.users[ctx["user_id"]].get("email_verified_at")
    r = client.get(f"/verify?u={ctx['user_id'] + 1}&e={exp}&t={token}")
    assert "invalid or has expired" in r.text


def test_logout_all_sessions(env):
    client, store, ctx = env
    token2, th2, exp2 = new_session_token()
    store.create_session(ctx["user_id"], th2, exp2)
    r = client.post("/app/logout-all", data={"csrf_token": csrf_for(ctx["token"])})
    assert r.status_code == 303
    assert all(s["revoked_at"] for s in store.sessions.values())


def test_unsubscribe_link(env):
    client, store, ctx = env
    store.subs[ctx["org_id"]] = {"id": 42, "email": "u@example.com",
                                 "timezone": "America/Chicago", "min_score": 40,
                                 "active": True}
    from src import tokens
    token, exp = tokens.sign("unsub", a=42)
    r = client.get(f"/unsubscribe?s=42&e={exp}&t={token}")
    assert "unsubscribed" in r.text.lower()
    assert store.subs[ctx["org_id"]]["active"] is False
    token2, exp2 = tokens.sign("unsub", a=43)          # wrong subscription id
    assert "invalid or has expired" in client.get(f"/unsubscribe?s=42&e={exp2}&t={token2}").text


def test_feedback_requires_org(env):
    _, store, _ = env
    with pytest.raises(ValueError):
        store.record_feedback(None, 1, "track")


def test_intel_api_disabled_by_default(monkeypatch):
    monkeypatch.delenv("INTEL_API_ENABLED", raising=False)
    import importlib
    import sys
    sys.modules.pop("src.api", None)
    with pytest.raises(RuntimeError, match="admin-only"):
        importlib.import_module("src.api")


def test_audit_trail_written(env):
    client, store, ctx = env
    client.post("/app/opportunities/1/status",
                data={"status": "watching", "csrf_token": csrf_for(ctx["token"])})
    events = [a["event"] for a in store.audit_events]
    assert "status_update" in events
