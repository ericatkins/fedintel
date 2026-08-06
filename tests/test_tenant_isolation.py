"""Tenant isolation: one organization can never read or write another
organization's profile, watchlist, subscription, or feedback — even with a
valid session and known resource IDs. Uses the same app + store interface
production uses (MemoryStore standing in for Postgres)."""
import pytest
from fastapi.testclient import TestClient

from src.web.app import SESSION_COOKIE, app
from src.web.auth import hash_password, new_session_token
from src.web.store import MemoryStore

PASSWORD = "a long enough password"


@pytest.fixture
def env(monkeypatch):
    store = MemoryStore()
    app.state.store = store
    # two orgs, one user each
    users = {}
    for name in ("alpha", "beta"):
        uid, oid = store.create_user_with_org(f"{name}@example.com",
                                              hash_password(PASSWORD), f"{name} org")
        token, token_hash, exp = new_session_token()
        store.create_session(uid, token_hash, exp)
        users[name] = {"user_id": uid, "org_id": oid, "token": token}
    # one globally-visible opportunity
    store.opportunities[1] = {"id": 1, "title": "Shared Opportunity", "agency": "Army",
                              "score": 90, "source_notice_id": "abc"}
    client = TestClient(app, follow_redirects=False)
    yield client, store, users
    app.state.store = None


def as_user(client, users, name):
    client.cookies.set(SESSION_COOKIE, users[name]["token"])
    return client


def csrf(users, name):
    from src.web.app import csrf_for
    return csrf_for(users[name]["token"])


def test_unauthenticated_requests_are_redirected(env):
    client, _, _ = env
    client.cookies.clear()
    for path in ("/app", "/app/opportunities", "/app/opportunities/1",
                 "/app/watchlist", "/app/alerts", "/app/profile"):
        r = client.get(path)
        assert r.status_code == 303 and r.headers["location"] == "/login", path


def test_profile_is_org_scoped(env):
    client, store, users = env
    as_user(client, users, "alpha").post("/app/profile", data={
        "csrf_token": csrf(users, "alpha"),
        "name": "Alpha Corp", "capabilities": "secret alpha capability",
        "industries": "", "naics_codes": "", "agencies_of_interest": "", "locations": "",
        "set_aside_eligibility": "", "keywords_boost": "", "keywords_suppress": "",
        "excluded_categories": ""})
    assert store.get_profile(users["alpha"]["org_id"])["name"] == "Alpha Corp"
    # beta sees an EMPTY profile page, not alpha's
    r = as_user(client, users, "beta").get("/app/profile")
    assert r.status_code == 200
    assert "Alpha Corp" not in r.text
    assert "secret alpha capability" not in r.text
    assert store.get_profile(users["beta"]["org_id"]) is None


def test_watchlist_is_org_scoped(env):
    client, store, users = env
    as_user(client, users, "alpha").post("/app/opportunities/1/status",
                                         data={"status": "pursuing",
                                               "csrf_token": csrf(users, "alpha")})
    assert store.tracked[(users["alpha"]["org_id"], 1)] == "pursuing"
    r = as_user(client, users, "beta").get("/app/watchlist")
    assert "Shared Opportunity" not in r.text          # beta's watchlist is empty
    assert (users["beta"]["org_id"], 1) not in store.tracked
    # and beta setting a status never touches alpha's row
    as_user(client, users, "beta").post("/app/opportunities/1/status",
                                        data={"status": "ignored",
                                              "csrf_token": csrf(users, "beta")})
    assert store.tracked[(users["alpha"]["org_id"], 1)] == "pursuing"
    assert store.tracked[(users["beta"]["org_id"], 1)] == "ignored"


def test_alert_subscription_is_org_scoped(env):
    client, store, users = env
    as_user(client, users, "alpha").post("/app/alerts", data={
        "email": "alpha-digest@example.com", "timezone_name": "America/Chicago",
        "min_score": "55", "active": "on", "csrf_token": csrf(users, "alpha")})
    r = as_user(client, users, "beta").get("/app/alerts")
    assert "alpha-digest@example.com" not in r.text
    assert store.get_subscription(users["beta"]["org_id"]) is None


def test_feedback_is_attributed_to_the_actors_org(env):
    client, store, users = env
    as_user(client, users, "alpha").post("/app/opportunities/1/status",
                                         data={"status": "watching",
                                               "csrf_token": csrf(users, "alpha")})
    orgs = {f["org_id"] for f in store.feedback}
    assert orgs == {users["alpha"]["org_id"]}


def test_org_id_never_accepted_from_client(env):
    client, store, users = env
    # attacker sends beta's org id in body/query — server must ignore it
    as_user(client, users, "alpha").post(
        "/app/opportunities/1/status?organization_id=" + str(users["beta"]["org_id"]),
        data={"status": "pursuing", "csrf_token": csrf(users, "alpha"),
              "organization_id": str(users["beta"]["org_id"])})
    assert (users["beta"]["org_id"], 1) not in store.tracked
    assert store.tracked[(users["alpha"]["org_id"], 1)] == "pursuing"


def test_invalid_status_rejected(env):
    client, _, users = env
    r = as_user(client, users, "alpha").post("/app/opportunities/1/status",
                                             data={"status": "definitely_not_valid",
                                                   "csrf_token": csrf(users, "alpha")})
    assert r.status_code == 400


def test_revoked_session_is_dead(env):
    client, store, users = env
    store.revoke_session(users["alpha"]["token"])
    r = as_user(client, users, "alpha").get("/app")
    assert r.status_code == 303 and r.headers["location"] == "/login"
