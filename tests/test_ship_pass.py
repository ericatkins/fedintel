"""Ship pass: account deletion, saved views (org-scoped + plan limits),
dashboard decision panels, entitlement flags."""
import pytest
from fastapi.testclient import TestClient

from src.web.app import SESSION_COOKIE, app, csrf_for
from src.web.auth import hash_password, new_session_token
from src.web.entitlements import allows, limit
from src.web.store import MemoryStore

PASSWORD = "a long enough password"


@pytest.fixture
def env():
    store = MemoryStore()
    app.state.store = store
    uid, oid = store.create_user_with_org("u@example.com", hash_password(PASSWORD), "org")
    token, token_hash, exp = new_session_token()
    store.create_session(uid, token_hash, exp)
    client = TestClient(app, follow_redirects=False)
    client.cookies.set(SESSION_COOKIE, token)
    yield client, store, {"user_id": uid, "org_id": oid, "token": token}
    app.state.store = None


def test_account_deletion_blocks_login_and_revokes_sessions(env):
    client, store, ctx = env
    r = client.post("/app/account/delete",
                    data={"confirm": "delete my account",
                          "csrf_token": csrf_for(ctx["token"])})
    assert r.status_code == 303
    assert store.users[ctx["user_id"]]["deleted_at"]
    assert all(s["revoked_at"] for s in store.sessions.values())
    assert client.get("/app").status_code == 303          # session dead
    client.cookies.clear()
    r = client.post("/login", data={"email": "u@example.com", "password": PASSWORD})
    assert "Invalid email or password" in r.text          # login blocked


def test_account_deletion_requires_exact_confirmation(env):
    client, store, ctx = env
    r = client.post("/app/account/delete",
                    data={"confirm": "yes", "csrf_token": csrf_for(ctx["token"])})
    assert "exactly to confirm" in r.text
    assert not store.users[ctx["user_id"]].get("deleted_at")


def test_saved_views_roundtrip_and_org_scoping(env):
    client, store, ctx = env
    r = client.post("/app/views", data={"name": "Army 80+", "q": "army",
                                        "min_score": "80", "notice_type": "",
                                        "csrf_token": csrf_for(ctx["token"])})
    assert r.status_code == 303
    views = store.list_views(ctx["org_id"])
    assert views[0]["name"] == "Army 80+" and views[0]["criteria"]["min_score"] == 80
    # applying the view filters the table
    store.opportunities[1] = {"id": 1, "title": "Army Software", "agency": "Army",
                              "score": 95, "source_notice_id": "a"}
    store.opportunities[2] = {"id": 2, "title": "Navy Ships", "agency": "Navy",
                              "score": 95, "source_notice_id": "b"}
    html = client.get(f"/app/opportunities?view={views[0]['id']}").text
    assert "Army Software" in html and "Navy Ships" not in html
    # another org cannot load or delete this view
    uid2, oid2 = store.create_user_with_org("o2@example.com",
                                            hash_password(PASSWORD), "org2")
    tok2, th2, exp2 = new_session_token()
    store.create_session(uid2, th2, exp2)
    c2 = TestClient(app, follow_redirects=False)
    c2.cookies.set(SESSION_COOKIE, tok2)
    html2 = c2.get(f"/app/opportunities?view={views[0]['id']}").text
    assert "Navy Ships" in html2                          # view ignored, unfiltered
    c2.post(f"/app/views/{views[0]['id']}/delete",
            data={"csrf_token": csrf_for(tok2)})
    assert store.list_views(ctx["org_id"])                 # still exists


def test_saved_view_plan_limit_enforced(env):
    client, store, ctx = env
    store.plans[ctx["org_id"]] = "scout"                   # limit: 3
    for i in range(3):
        store.save_view(ctx["org_id"], ctx["user_id"], f"v{i}", {})
    r = client.post("/app/views", data={"name": "v4", "q": "", "min_score": "40",
                                        "notice_type": "",
                                        "csrf_token": csrf_for(ctx["token"])})
    assert r.status_code == 403


def test_dashboard_renders_decision_panels(env):
    client, store, ctx = env
    store.org_transitions[ctx["org_id"]] = [
        {"detail": {"from": "Sources Sought", "to": "Solicitation"},
         "created_at": None, "opportunity_id": 3, "title": "Tracked Widget"}]
    store.deliveries[ctx["org_id"]] = {"digest_date": "2026-07-11", "status": "sent",
                                       "opportunities": 6}
    html = client.get("/app").text
    assert "Closing soon" in html
    assert "Tracked Widget" in html and "Sources Sought → Solicitation" in html
    assert "Pursuit pipeline" in html
    assert "Last digest: 2026-07-11" in html


def test_entitlement_flags():
    assert allows("early_access", "instant_alerts") is True
    assert allows("scout", "instant_alerts") is False
    assert allows("nonexistent_plan", "daily_digest") is True   # safe default
    assert limit("scout", "saved_views") == 3
    assert limit("team", "saved_views") == 100
    assert limit("pro", "instant_alerts") == 0                  # bool is not a limit
