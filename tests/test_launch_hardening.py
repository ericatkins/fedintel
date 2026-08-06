"""Launch hardening: verification enforcement, feedback learning loop,
entitlement gates, value estimates, idempotency keys, delivery-due logic."""
import pytest
from fastapi.testclient import TestClient

from src.intel.value_estimate import estimate
from src.learning import FEEDBACK_DELTAS, adjustment_for, apply_learning
from src.main import _delivery_due
from src.web.app import SESSION_COOKIE, app, csrf_for
from src.web.auth import hash_password, new_session_token
from src.web.store import MemoryStore

PASSWORD = "a long enough password"


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("REQUIRE_EMAIL_VERIFICATION", "1")
    store = MemoryStore()
    app.state.store = store
    uid, oid = store.create_user_with_org("u@example.com", hash_password(PASSWORD), "org")
    token, token_hash, exp = new_session_token()
    store.create_session(uid, token_hash, exp)
    client = TestClient(app, follow_redirects=False)
    client.cookies.set(SESSION_COOKIE, token)
    yield client, store, {"user_id": uid, "org_id": oid, "token": token}
    app.state.store = None


def test_login_blocked_until_verified(env):
    client, store, ctx = env
    client.cookies.clear()
    r = client.post("/login", data={"email": "u@example.com", "password": PASSWORD})
    assert "Verify your email" in r.text and SESSION_COOKIE not in r.cookies
    store.mark_email_verified(ctx["user_id"])
    r = client.post("/login", data={"email": "u@example.com", "password": PASSWORD})
    assert r.status_code == 303 and r.headers["location"] == "/app"


def test_verification_not_enforced_when_disabled(env, monkeypatch):
    client, _, _ = env
    monkeypatch.setenv("REQUIRE_EMAIL_VERIFICATION", "0")
    client.cookies.clear()
    r = client.post("/login", data={"email": "u@example.com", "password": PASSWORD})
    assert r.status_code == 303


def test_feedback_adjusts_future_scores(env):
    """The copy 'this improves your future matches' must be TRUE."""
    client, store, ctx = env
    store.opportunities[1] = {"id": 1, "title": "Army Inventory", "agency": "ARMY",
                              "naics": "541512", "category": "Software",
                              "score": 70, "source_notice_id": "x"}
    for _ in range(3):
        store.record_feedback(ctx["org_id"], 1, "good_match")
    weights = store.preference_weights(ctx["org_id"])
    assert weights["naics:541512"] == 6 and weights["agency:ARMY"] == 6
    result = apply_learning({"score": 70, "reasons": []},
                            store.opportunities[1], weights)
    assert result["score"] == 70 + 15                 # capped at +15, not +18
    assert any("learned preference" in r for r in result["reasons"])
    # negative signal drives similar work DOWN
    for _ in range(3):
        store.record_feedback(ctx["org_id"], 1, "hide_similar")
    weights = store.preference_weights(ctx["org_id"])
    assert weights["naics:541512"] == -10             # per-feature floor
    down = apply_learning({"score": 70, "reasons": []},
                          store.opportunities[1], weights)
    assert down["score"] == 70 - 15


def test_feature_weights_capped_and_resettable(env):
    client, store, ctx = env
    store.opportunities[1] = {"id": 1, "title": "T", "agency": "ARMY",
                              "naics": "541512", "score": 70, "source_notice_id": "x"}
    for _ in range(20):
        store.record_feedback(ctx["org_id"], 1, "pursuing")
    assert store.preference_weights(ctx["org_id"])["naics:541512"] == 10
    r = client.post("/app/profile/reset-preferences",
                    data={"csrf_token": csrf_for(ctx["token"])})
    assert r.status_code == 303
    assert store.preference_weights(ctx["org_id"]) == {}


def test_learned_preferences_visible_on_profile(env):
    client, store, ctx = env
    store.opportunities[1] = {"id": 1, "title": "T", "agency": "ARMY",
                              "naics": "541512", "score": 70, "source_notice_id": "x"}
    store.record_feedback(ctx["org_id"], 1, "good_match")
    html = client.get("/app/profile").text
    assert "Learned preferences" in html and "naics: 541512" in html


def test_entitlements_enforced_server_side(env):
    client, store, ctx = env
    store.plans[ctx["org_id"]] = "scout"              # no vendor_intel
    assert client.get("/app/vendors").status_code == 403
    assert client.get("/app/vendors/1").status_code == 403
    assert client.get("/app/agencies").status_code == 200   # scout HAS agency_intel
    store.plans[ctx["org_id"]] = "pro"
    assert client.get("/app/vendors").status_code == 200


def test_value_estimate_median_iqr_outlier_exclusion():
    awards = [{"obligated_amount": a} for a in
              (2_000_000, 4_000_000, 5_000_000, 6_000_000, 7_000_000, 42_000_000)]
    est = estimate(awards)
    assert est["outliers_excluded"] == 1              # the $42M vehicle
    assert est["median"] == 5_000_000
    assert est["low"] >= 2_000_000 and est["high"] <= 7_000_000
    assert estimate([{"obligated_amount": 1}]) is None          # no basis
    assert estimate([]) is None


def test_delivery_due_respects_local_time():
    from datetime import datetime
    sub = {"delivery_hour": 6, "delivery_minute": 30}
    assert not _delivery_due(sub, datetime(2026, 7, 12, 5, 59))
    assert not _delivery_due(sub, datetime(2026, 7, 12, 6, 29))
    assert _delivery_due(sub, datetime(2026, 7, 12, 6, 30))
    assert _delivery_due(sub, datetime(2026, 7, 12, 23, 0))
    assert _delivery_due({}, datetime(2026, 7, 12, 6, 0))       # defaults 6:00


def test_resend_idempotency_key_sent(monkeypatch):
    captured = {}

    class FakeResp:
        status_code = 200
        def json(self):
            return {"id": "msg_1"}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["headers"] = headers
        return FakeResp()

    import src.send_email as se
    monkeypatch.setattr(se, "RESEND_API_KEY", "key")
    monkeypatch.setattr(se.requests, "post", fake_post)
    se.send("s", "<p>x</p>", to_override=["a@b.com"],
            idempotency_key="fedintel-digest:7:2026-07-12")
    assert captured["headers"]["Idempotency-Key"] == "fedintel-digest:7:2026-07-12"
    se.send_plain("a@b.com", "s", "b", idempotency_key="fedintel-alert:7:9")
    assert captured["headers"]["Idempotency-Key"] == "fedintel-alert:7:9"


def test_all_feedback_actions_have_defined_deltas():
    from src.web.store import TRACK_STATUSES
    for status in TRACK_STATUSES:
        assert status in FEEDBACK_DELTAS
    total, reasons = adjustment_for(["naics:541512"], {"naics:541512": 3})
    assert total == 3 and "boosted" in reasons[0]
