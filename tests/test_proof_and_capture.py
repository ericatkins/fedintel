"""Requirement-to-proof mapping, project library, and capture tasks —
including tenant isolation for the new private data."""
from datetime import date

import pytest
from fastapi.testclient import TestClient

from src.intel.proof import map_requirements_to_proof
from src.web.app import SESSION_COOKIE, app
from src.web.auth import hash_password, new_session_token
from src.web.store import MemoryStore

TODAY = date(2026, 8, 6)
OPP = {"naics": "541512", "agency": "DEPT OF THE ARMY"}


def _req(rtype="personnel", value="cloud migration engineers",
         quote="The contractor shall provide cloud migration engineers."):
    return {"requirement_type": rtype, "value": value, "evidence_quote": quote,
            "status": "advisory", "method": "rule", "confidence": 80,
            "page": 3}


def _project(**kw):
    p = {"id": 7, "title": "Army cloud migration", "customer_agency":
         "Dept of the Army", "naics": "541512", "period_end": "2025-01-01",
         "scope": "Migrated legacy systems to cloud with zero downtime",
         "technologies": "AWS, Terraform", "outcomes": ""}
    p.update(kw)
    return p


# ---- proof mapping ----

def test_profile_types_are_marked_profile_not_mapped():
    out = map_requirements_to_proof([_req("clearance", "TS/SCI")], [_project()],
                                    OPP, today=TODAY)
    assert out["rows"][0]["proof_status"] == "profile"
    assert out["summary"]["mappable_requirements"] == 0


def test_no_projects_means_missing_with_caveat():
    out = map_requirements_to_proof([_req()], [], OPP, today=TODAY)
    assert out["rows"][0]["proof_status"] == "missing"
    assert any("No past projects recorded" in c
               for c in out["summary"]["caveats"])


def test_recent_relevant_project_is_strong_proof():
    out = map_requirements_to_proof([_req()], [_project()], OPP, today=TODAY)
    row = out["rows"][0]
    assert row["proof_status"] == "strong"
    assert row["proof_project"] == "Army cloud migration"
    assert any("NAICS" in w for w in row["proof_why"])
    assert out["summary"]["coverage_pct"] == 100


def test_old_project_is_stale_never_silently_strong():
    old = _project(period_end="2019-06-30")
    out = map_requirements_to_proof([_req()], [old], OPP, today=TODAY)
    assert out["rows"][0]["proof_status"] == "stale"
    assert any("years ago" in w for w in out["rows"][0]["proof_why"])


def test_partial_overlap_is_weak_with_warning():
    weak_p = _project(naics="236220", customer_agency="GSA",
                      scope="general cloud consulting")
    out = map_requirements_to_proof([_req()], [weak_p], OPP, today=TODAY)
    assert out["rows"][0]["proof_status"] == "weak"
    assert any("verify before claiming" in w for w in out["rows"][0]["proof_why"])


def test_unrelated_project_is_missing():
    unrelated = _project(title="Roof repair", scope="Roofing repairs at depot",
                         technologies="")
    out = map_requirements_to_proof([_req()], [unrelated], OPP, today=TODAY)
    assert out["rows"][0]["proof_status"] == "missing"


# ---- store + web: tenant isolation ----

PASSWORD = "a long enough password"


@pytest.fixture
def env():
    store = MemoryStore()
    app.state.store = store
    users = {}
    for name in ("alpha", "beta"):
        uid, oid = store.create_user_with_org(f"{name}@example.com",
                                              hash_password(PASSWORD),
                                              f"{name} org")
        token, token_hash, exp = new_session_token()
        store.create_session(uid, token_hash, exp)
        users[name] = {"user_id": uid, "org_id": oid, "token": token}
    store.opportunities[1] = {"id": 1, "title": "Shared Opportunity",
                              "agency": "Army", "score": 90,
                              "source_notice_id": "abc"}
    client = TestClient(app, follow_redirects=False)
    yield client, store, users
    app.state.store = None


def _as(client, users, name):
    client.cookies.set(SESSION_COOKIE, users[name]["token"])
    return client


def _csrf(users, name):
    from src.web.app import csrf_for
    return csrf_for(users[name]["token"])


def test_projects_are_tenant_isolated(env):
    client, store, users = env
    a, b = users["alpha"]["org_id"], users["beta"]["org_id"]
    pid = store.add_project(a, {"title": "Alpha secret project"})
    assert store.list_projects(b) == []
    store.delete_project(b, pid)                      # cross-tenant delete no-ops
    assert len(store.list_projects(a)) == 1


def test_capture_tasks_are_tenant_isolated(env):
    client, store, users = env
    a, b = users["alpha"]["org_id"], users["beta"]["org_id"]
    tid = store.add_capture_task(a, "Call the KO", opportunity_id=1)
    assert store.list_capture_tasks(b) == []
    store.set_capture_task_status(b, tid, "done")     # cross-tenant no-op
    assert store.list_capture_tasks(a)[0]["status"] == "open"


def test_add_project_via_web_and_render(env):
    client, store, users = env
    _as(client, users, "alpha")
    r = client.post("/app/profile/projects",
                    data={"csrf_token": _csrf(users, "alpha"),
                          "title": "NASA data pipeline", "naics": "541511",
                          "value_total": "$1,200,000",
                          "period_end": "2025-03-31"})
    assert r.status_code == 303
    rows = store.list_projects(users["alpha"]["org_id"])
    assert rows[0]["title"] == "NASA data pipeline"
    assert rows[0]["value_total"] == 1200000.0
    page = client.get("/app/profile")
    assert "NASA data pipeline" in page.text


def test_add_project_requires_csrf(env):
    client, store, users = env
    _as(client, users, "alpha")
    r = client.post("/app/profile/projects", data={"title": "X"})
    assert r.status_code == 403
    assert store.list_projects(users["alpha"]["org_id"]) == []


def test_capture_task_web_flow(env):
    client, store, users = env
    _as(client, users, "alpha")
    r = client.post("/app/opportunities/1/tasks",
                    data={"csrf_token": _csrf(users, "alpha"),
                          "title": "Draft sources sought response",
                          "due_date": "2026-08-20", "source": "generated"})
    assert r.status_code == 303
    tasks = store.list_capture_tasks(users["alpha"]["org_id"])
    assert tasks[0]["source"] == "generated"
    r = client.post(f"/app/tasks/{tasks[0]['id']}/status",
                    data={"csrf_token": _csrf(users, "alpha"),
                          "status": "done"})
    assert r.status_code == 303
    assert store.list_capture_tasks(users["alpha"]["org_id"]) == []


def test_task_status_redirect_never_leaves_app(env):
    client, store, users = env
    _as(client, users, "alpha")
    tid = store.add_capture_task(users["alpha"]["org_id"], "T")
    r = client.post(f"/app/tasks/{tid}/status",
                    data={"csrf_token": _csrf(users, "alpha"), "status": "done"},
                    headers={"referer": "https://evil.example/phish"})
    assert r.status_code == 303
    assert r.headers["location"].startswith("/app")
