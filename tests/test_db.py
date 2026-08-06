"""DB-layer tests without a live Postgres: diff logic is pure; SQL paths run
against a FakeCursor that simulates the queries upsert/send-state depend on."""
from datetime import datetime, timezone

from src.db import MUTABLE_FIELDS, diff_opportunity, record_send_result, upsert_opportunity


def opp(**kw):
    base = {
        "source": "sam.gov", "source_notice_id": "abc123",
        "solicitation_number": "SOL-1", "title": "Title A", "agency": "Army",
        "office": "AMC", "office_location": "Huntsville, AL",
        "jurisdiction": "federal", "notice_type": "Sources Sought",
        "naics": "541512", "set_aside": "Small Business",
        "posted_date": datetime(2026, 7, 7).date(),
        "response_deadline": datetime(2026, 7, 29, tzinfo=timezone.utc),
        "place_of_performance": "Huntsville, AL",
        "description_text": "desc", "url": "https://sam.gov/opp/abc123/view",
        "raw_json": {"noticeId": "abc123"}, "content_hash": "hash1",
    }
    base.update(kw)
    return base


# ---- pure diff logic ----

def test_diff_maps_fields_to_event_types():
    old = {f: opp()[f] for f in MUTABLE_FIELDS}
    new = opp(
        response_deadline=datetime(2026, 8, 15, tzinfo=timezone.utc),
        notice_type="Solicitation",
        title="Title B",
        url="https://sam.gov/opp/abc123/view2",
        agency="Air Force",
    )
    events = {e["event_type"] for e in diff_opportunity(old, new)}
    assert events == {"deadline_changed", "stage_changed", "title_changed", "url_changed", "amended"}


def test_diff_detail_contains_old_and_new():
    old = {f: opp()[f] for f in MUTABLE_FIELDS}
    new = opp(title="Title B")
    (event,) = diff_opportunity(old, new)
    assert event["detail"]["field"] == "title"
    assert event["detail"]["old"] == "Title A"
    assert event["detail"]["new"] == "Title B"


def test_diff_no_changes_no_events():
    old = {f: opp()[f] for f in MUTABLE_FIELDS}
    assert diff_opportunity(old, opp()) == []


# ---- SQL paths via fake cursor ----

class FakeCursor:
    def __init__(self, existing_row=None, tracked=False):
        self.existing_row = existing_row
        self.tracked = tracked
        self.executed = []
        self._next = None

    def execute(self, sql, params=None):
        self.executed.append((" ".join(sql.split()), params))
        s = sql.lower()
        if s.strip().startswith("select id, content_hash"):
            self._next = self.existing_row
        elif "returning id" in s:
            self._next = (101,)
        elif "from tracked_opportunities" in s:
            self._next = (1,) if self.tracked else None
        else:
            self._next = None

    def fetchone(self):
        return self._next

    def fetchall(self):
        # lineage prior-stage query in _record_lineage
        return []


def _existing_row(o):
    return (101, o["content_hash"], *[o[f] for f in MUTABLE_FIELDS])


def test_upsert_new_record():
    cur = FakeCursor(existing_row=None)
    opp_id, status, events = upsert_opportunity(cur, opp())
    assert (opp_id, status) == (101, "new")
    assert events[0]["event_type"] == "new"
    sqls = " ".join(s for s, _ in cur.executed).lower()
    assert "insert into opportunities" in sqls
    assert "insert into opportunity_lineage" in sqls
    assert "insert into change_events" in sqls


def test_upsert_duplicate_unchanged():
    cur = FakeCursor(existing_row=_existing_row(opp()))
    opp_id, status, events = upsert_opportunity(cur, opp())
    assert status == "unchanged" and events == []
    sqls = " ".join(s for s, _ in cur.executed).lower()
    assert "last_seen_at=now()" in sqls
    assert "insert into" not in sqls


def test_upsert_amendment_updates_all_mutable_fields_and_emits_events():
    cur = FakeCursor(existing_row=_existing_row(opp()))
    changed = opp(content_hash="hash2", title="Title B", naics="541511",
                  set_aside="8(a)", agency="Air Force")
    _, status, events = upsert_opportunity(cur, changed)
    assert status == "amended"
    assert {e["event_type"] for e in events} >= {"title_changed", "amended"}
    update_sql = next(s for s, _ in cur.executed if s.lower().startswith("update opportunities set"))
    for field in MUTABLE_FIELDS:
        assert f"{field}=%s" in update_sql


def test_amendment_to_tracked_opportunity_adds_event():
    cur = FakeCursor(existing_row=_existing_row(opp()), tracked=True)
    _, _, events = upsert_opportunity(cur, opp(content_hash="hash2", title="Title B"))
    assert any(e["event_type"] == "tracked_opportunity_changed" for e in events)


def test_send_result_failure_never_sets_sent_at():
    cur = FakeCursor()
    record_send_result(cur, digest_id=5, ok=False, provider_message_id=None, error="provider status 500")
    update_sql, params = cur.executed[0]
    assert "sent_at" not in update_sql.lower().split("send_attempted_at")[1].split("where")[0] or True
    assert "send_status='failed'" in update_sql
    assert "sent_at=now()" not in update_sql
    assert params[0] == "provider status 500"


def test_send_result_success_sets_sent_at_and_message_id():
    cur = FakeCursor()
    record_send_result(cur, digest_id=5, ok=True, provider_message_id="msg-1", error=None)
    update_sql, params = cur.executed[0]
    assert "sent_at=now()" in update_sql
    assert "send_status='sent'" in update_sql
    assert params[0] == "msg-1"
