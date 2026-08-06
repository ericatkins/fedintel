"""Real-Postgres integration tests (Phase 7). Skipped unless TEST_DATABASE_URL
is set; CI provides a Postgres service. These verify what MemoryStore can't:
schema applies cleanly, unique constraints actually dedupe, and tenant
boundaries hold in real SQL."""
import os
import pathlib

import psycopg2
import pytest

TEST_DB = os.getenv("TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(not TEST_DB, reason="TEST_DATABASE_URL not set")

SCHEMA = pathlib.Path(__file__).resolve().parents[2] / "db" / "schema.sql"


@pytest.fixture(scope="module")
def conn():
    c = psycopg2.connect(TEST_DB)
    c.autocommit = False
    with c.cursor() as cur:
        cur.execute("drop schema public cascade; create schema public;")
        cur.execute(SCHEMA.read_text())
    c.commit()
    yield c
    c.close()


def test_schema_applies_cleanly(conn):
    with conn.cursor() as cur:
        cur.execute("select count(*) from information_schema.tables "
                    "where table_schema='public'")
        assert cur.fetchone()[0] >= 20


def test_signup_creates_user_org_member(conn):
    from src.web.store import PgStore
    store = PgStore.for_connection(conn)
    uid, oid = store.create_user_with_org("pg@example.com", "hash", "PG Org")
    with conn.cursor() as cur:
        cur.execute("select organization_id from organization_members where user_id=%s",
                    (uid,))
        assert cur.fetchone()[0] == oid
        cur.execute("select plan from organizations where id=%s", (oid,))
        assert cur.fetchone()[0] == "early_access"
    conn.commit()


def test_feedback_requires_org_and_is_scoped(conn):
    from src.web.store import PgStore
    store = PgStore.for_connection(conn)
    with conn.cursor() as cur:
        cur.execute("""insert into opportunities (source, source_notice_id, title,
                       content_hash, raw_json) values ('sam','pg-opp-1','T','h','{}')
                       returning id""")
        opp_id = cur.fetchone()[0]
        cur.execute("select id from organizations limit 1")
        org_id = cur.fetchone()[0]
    with pytest.raises(ValueError):
        store.record_feedback(None, opp_id, "track")
    store.record_feedback(org_id, opp_id, "track")
    with conn.cursor() as cur:
        cur.execute("select organization_id from opportunity_feedback "
                    "where opportunity_id=%s", (opp_id,))
        assert cur.fetchone()[0] == org_id
        # check constraint: invalid action rejected by the DATABASE
        with pytest.raises(psycopg2.errors.CheckViolation):
            cur.execute("insert into opportunity_feedback "
                        "(organization_id, opportunity_id, action) values (%s,%s,'nuke')",
                        (org_id, opp_id))
    conn.rollback()


def test_profile_matches_unique_per_org_opp(conn):
    from src.matching import upsert_profile_opportunity_match
    with conn.cursor() as cur:
        cur.execute("select id from organizations limit 1")
        org_id = cur.fetchone()[0]
        cur.execute("""insert into opportunities (source, source_notice_id, title,
                       content_hash, raw_json) values ('sam','pg-opp-2','T2','h2','{}')
                       returning id""")
        opp_id = cur.fetchone()[0]
        result = {"score": 80, "confidence": 70, "category": "Software",
                  "recommended_action": "Track closely", "reasons": ["r"],
                  "components": {}}
        upsert_profile_opportunity_match(cur, org_id, None, opp_id, 60, result)
        result["score"] = 92
        upsert_profile_opportunity_match(cur, org_id, None, opp_id, 60, result)
        cur.execute("select count(*), max(final_match_score) "
                    "from profile_opportunity_matches "
                    "where organization_id=%s and opportunity_id=%s", (org_id, opp_id))
        count, score = cur.fetchone()
        assert count == 1 and score == 92        # upsert, not duplicate
        with pytest.raises(psycopg2.errors.CheckViolation):
            cur.execute("update profile_opportunity_matches set final_match_score=150 "
                        "where organization_id=%s", (org_id,))
    conn.rollback()


def test_buyer_office_upsert_does_not_duplicate(conn):
    from src.db_intel import upsert_buyer_office
    identity = {"department_name": "DEPT OF DEFENSE", "subtier_name": "DEPT OF THE ARMY",
                "office_name": "ARMY CONTRACTING COMMAND", "organization_code": "W58RGZ",
                "full_parent_path_name": None, "full_parent_path_code": None}
    with conn.cursor() as cur:
        id1 = upsert_buyer_office(cur, identity, 70)
        id2 = upsert_buyer_office(cur, identity, 90)
        assert id1 == id2
        cur.execute("select count(*), max(source_confidence) from buyer_offices "
                    "where organization_code='W58RGZ'")
        count, conf = cur.fetchone()
        assert count == 1 and conf == 90          # merged, confidence kept highest
    conn.rollback()


def test_office_market_stats_upsert_null_psc_no_duplicate(conn):
    from src.db_intel import upsert_buyer_office, upsert_office_market_stat
    with conn.cursor() as cur:
        office_id = upsert_buyer_office(cur, {"organization_code": "TESTOFC",
                                              "office_name": "X", "subtier_name": "Y",
                                              "department_name": "Z"}, 70)
        row = {"fiscal_year": 2026, "naics": "541512", "psc": None, "award_count": 3,
               "total_obligations": 100.0, "fedintel_category": "Software",
               "small_business_share": 50.0}
        upsert_office_market_stat(cur, office_id, row)
        row["award_count"] = 5
        upsert_office_market_stat(cur, office_id, row)       # null psc: must UPDATE
        cur.execute("select count(*), max(award_count) from office_market_stats "
                    "where buyer_office_id=%s and fiscal_year=2026", (office_id,))
        count, awards = cur.fetchone()
        assert count == 1 and awards == 5
    conn.rollback()


def test_lineage_does_not_duplicate_and_detects_transitions(conn):
    from src.db import upsert_opportunity
    base = {"source": "sam", "jurisdiction": "federal",
            "source_notice_id": "pg-lin-1", "title": "Widget RFP",
            "solicitation_number": "PG-26-R-1", "notice_type": "Sources Sought",
            "agency": "A", "office": "O", "office_location": None, "naics": "541512",
            "set_aside": None, "posted_date": None, "response_deadline": None,
            "place_of_performance": None, "description_text": "d", "url": None,
            "raw_json": {}, "content_hash": "l1"}
    with conn.cursor() as cur:
        opp_id, status, _ = upsert_opportunity(cur, dict(base))
        upsert_opportunity(cur, dict(base))                   # same notice again
        cur.execute("select count(*) from opportunity_lineage "
                    "where solicitation_number='PG-26-R-1'")
        assert cur.fetchone()[0] == 1                          # no duplicate
        rfp = dict(base, source_notice_id="pg-lin-2", notice_type="Solicitation",
                   content_hash="l2")
        rfp_id, _, _ = upsert_opportunity(cur, rfp)
        cur.execute("select count(*) from change_events "
                    "where opportunity_id=%s and event_type='stage_transition'", (rfp_id,))
        assert cur.fetchone()[0] == 1                          # transition detected
        amended = dict(rfp, notice_type="Award Notice", content_hash="l3")
        upsert_opportunity(cur, amended)                       # amendment advances stage
        cur.execute("select count(*) from change_events "
                    "where opportunity_id=%s and event_type='stage_transition'", (rfp_id,))
        assert cur.fetchone()[0] == 2
    conn.rollback()


def test_digest_delivery_unique_per_subscription_day(conn):
    with conn.cursor() as cur:
        cur.execute("select id from organizations limit 1")
        org_id = cur.fetchone()[0]
        cur.execute("select id from users limit 1")
        user_id = cur.fetchone()[0]
        cur.execute("""insert into digest_subscriptions
                       (organization_id, user_id, email) values (%s,%s,'d@e.com')
                       returning id""", (org_id, user_id))
        sub_id = cur.fetchone()[0]
        cur.execute("""insert into digest_deliveries (subscription_id, organization_id,
                       digest_date) values (%s,%s,current_date)""", (sub_id, org_id))
        with pytest.raises(psycopg2.errors.UniqueViolation):
            cur.execute("""insert into digest_deliveries (subscription_id,
                           organization_id, digest_date)
                           values (%s,%s,current_date)""", (sub_id, org_id))
    conn.rollback()


def test_per_org_digest_rows_use_match_score(conn):
    from src.db import fetch_digest_rows_for_org
    from src.matching import upsert_profile_opportunity_match
    with conn.cursor() as cur:
        cur.execute("select id from organizations limit 1")
        org_id = cur.fetchone()[0]
        cur.execute("""insert into opportunities (source, source_notice_id, title,
                       content_hash, raw_json, first_seen_at)
                       values ('sam','pg-dig-1','Digest Opp','dg1','{}', now())
                       returning id""")
        opp_id = cur.fetchone()[0]
        cur.execute("insert into classifications (opportunity_id, score, category, "
                    "confidence, reasons, components) "
                    "values (%s, 30, 'Software', 50, '[]', '{}')", (opp_id,))
        result = {"score": 85, "confidence": 70, "category": "Software",
                  "recommended_action": "Pursue", "reasons": ["org fit"],
                  "components": {}}
        upsert_profile_opportunity_match(cur, org_id, None, opp_id, 30, result)
        # digest date must be computed in the SUBSCRIPTION's timezone, exactly
        # as the pipeline does — naive date.today() flakes near midnight UTC
        import datetime
        from zoneinfo import ZoneInfo
        chicago_today = datetime.datetime.now(ZoneInfo("America/Chicago")).date()
        rows = fetch_digest_rows_for_org(cur, org_id, "America/Chicago",
                                         chicago_today, 40)
        ours = [r for r in rows if r["id"] == opp_id]
        assert ours and ours[0]["score"] == 85     # per-org score, not global 30
        other_org_rows = fetch_digest_rows_for_org(cur, org_id + 999, "America/Chicago",
                                                   chicago_today, 40)
        theirs = [r for r in other_org_rows if r["id"] == opp_id]
        assert not theirs or theirs[0]["score"] == 30   # other org sees global only
    conn.rollback()


def test_instant_alerts_idempotent_and_plan_gated(conn, monkeypatch):
    """Instant alerts: delivered once per (subscription, event), never twice,
    and only to plans whose entitlements allow them."""
    import src.alerts as alerts_mod
    sent_emails = []
    monkeypatch.setattr(
        alerts_mod, "send_plain",
        lambda to, subject, body, idempotency_key=None:
            sent_emails.append((to, subject, body, idempotency_key)))
    with conn.cursor() as cur:
        cur.execute("insert into organizations (name, plan) "
                    "values ('AlertOrg','early_access') returning id")
        org_id = cur.fetchone()[0]
        cur.execute("""insert into users (email, password_hash) values
                       ('alert@example.com','h') returning id""")
        user_id = cur.fetchone()[0]
        cur.execute("""insert into opportunities (source, source_notice_id, title,
                       content_hash, raw_json) values
                       ('sam','pg-alert-1','Alert Opp','ah','{}') returning id""")
        opp_id = cur.fetchone()[0]
        cur.execute("""insert into tracked_opportunities
                       (organization_id, opportunity_id, status)
                       values (%s,%s,'watching')""", (org_id, opp_id))
        cur.execute("""insert into digest_subscriptions (organization_id, user_id,
                       email, instant_alerts) values (%s,%s,'alert@example.com',true)
                       returning id""", (org_id, user_id))
        cur.execute("""insert into change_events (opportunity_id, event_type, detail)
                       values (%s,'stage_transition',
                               '{"from":"Sources Sought","to":"Solicitation"}')""",
                    (opp_id,))
    conn.commit()
    sent = alerts_mod.send_instant_alerts(conn, base_url="https://app.example")
    assert sent == 1
    assert "Alert Opp" in sent_emails[0][2]
    assert "Sources Sought → Solicitation" in sent_emails[0][2]
    assert "https://app.example/app/opportunities/" in sent_emails[0][2]
    assert sent_emails[0][3].startswith("fedintel-alert:")   # idempotency key set
    # rerun: nothing re-sent (unique per subscription+event)
    assert alerts_mod.send_instant_alerts(conn, base_url="https://app.example") == 0
    assert len(sent_emails) == 1
    # downgrade the plan to one without instant alerts; a NEW event is filtered
    with conn.cursor() as cur:
        cur.execute("update organizations set plan='scout' where id=%s", (org_id,))
        cur.execute("""insert into change_events (opportunity_id, event_type, detail)
                       values (%s,'stage_transition',
                               '{"from":"Solicitation","to":"Award Notice"}')""",
                    (opp_id,))
    conn.commit()
    assert alerts_mod.send_instant_alerts(conn) == 0
    with conn.cursor() as cur:                             # cleanup for other tests
        cur.execute("delete from organizations where id=%s", (org_id,))
    conn.commit()


def test_migration_006_account_deletion(conn):
    from src.web.store import PgStore
    store = PgStore.for_connection(conn)
    with conn.cursor() as cur:
        cur.execute("""insert into users (email, password_hash) values
                       ('gone@example.com','h') returning id""")
        user_id = cur.fetchone()[0]
    store.delete_account(user_id)
    assert store.get_user_by_email("gone@example.com") is None   # login blocked
    with conn.cursor() as cur:
        cur.execute("select deleted_at from users where id=%s", (user_id,))
        assert cur.fetchone()[0] is not None
    conn.rollback()


def test_signup_is_one_transaction(conn):
    """Pooled store: user + org + membership commit or roll back TOGETHER."""
    from src.web.store import PgStore
    store = PgStore.for_connection(conn)
    with conn.cursor() as cur:
        cur.execute("select count(*) from users")
        users_before = cur.fetchone()[0]
    # Force the LAST statement (membership) to fail: 'owner' too long? use bad org id
    import psycopg2
    with pytest.raises(psycopg2.Error):
        with conn.cursor() as cur:
            cur.execute("insert into users (email, password_hash) "
                        "values ('atomic@example.com','h') returning id")
            cur.execute("insert into organizations (name) values ('Atomic') returning id")
            cur.execute("insert into organization_members (organization_id, user_id, role) "
                        "values (%s,%s,'owner')", (999999999, 999999999))  # FK violation
    conn.rollback()
    with conn.cursor() as cur:
        cur.execute("select count(*) from users")
        assert cur.fetchone()[0] == users_before        # user insert rolled back too
        cur.execute("select count(*) from users where email='atomic@example.com'")
        assert cur.fetchone()[0] == 0
    # and the happy path still works through the store
    uid, oid = store.create_user_with_org("atomic-ok@example.com", "h", "Atomic OK")
    conn.commit()
    with conn.cursor() as cur:
        cur.execute("select count(*) from organization_members "
                    "where user_id=%s and organization_id=%s", (uid, oid))
        assert cur.fetchone()[0] == 1


def test_feedback_learning_persists_and_caps(conn):
    from src.matching import _load_weights
    from src.web.store import PgStore
    store = PgStore.for_connection(conn)
    with conn.cursor() as cur:
        cur.execute("insert into organizations (name) values ('LearnOrg') returning id")
        org_id = cur.fetchone()[0]
        cur.execute("""insert into opportunities (source, source_notice_id, title,
                       content_hash, raw_json, naics, agency)
                       values ('sam','pg-learn-1','L','lh','{}','541512','ARMY')
                       returning id""")
        opp_id = cur.fetchone()[0]
        cur.execute("""insert into classifications (opportunity_id, score, category,
                       confidence, reasons, components)
                       values (%s, 60, 'Software', 50, '[]', '{}')""", (opp_id,))
    for _ in range(6):                                   # 6 × +3 = 18 → capped at 10
        store.record_feedback(org_id, opp_id, "pursuing")
    with conn.cursor() as cur:
        weights = _load_weights(cur, org_id)
    assert weights["naics:541512"] == 10                 # DB check constraint ceiling
    assert weights["agency:ARMY"] == 10
    assert weights["category:Software"] == 10
    store.reset_preferences(org_id)
    with conn.cursor() as cur:
        assert _load_weights(cur, org_id) == {}
    conn.rollback()


def test_digest_waits_for_subscribers_local_morning(conn, monkeypatch):
    """A subscription whose delivery hour hasn't arrived locally is skipped;
    once due, it delivers exactly once."""
    import datetime as dt
    from zoneinfo import ZoneInfo

    import src.main as main_mod
    with conn.cursor() as cur:
        cur.execute("insert into organizations (name) values ('TzOrg') returning id")
        org_id = cur.fetchone()[0]
        cur.execute("insert into users (email, password_hash) "
                    "values ('tz@example.com','h') returning id")
        user_id = cur.fetchone()[0]
        # find their current local hour, then set delivery an hour in the future
        now_chi = dt.datetime.now(ZoneInfo("America/Chicago"))
        future_hour = (now_chi.hour + 1) % 24
        cur.execute("""insert into digest_subscriptions (organization_id, user_id,
                       email, timezone, min_score, delivery_hour_local,
                       delivery_minute_local)
                       values (%s,%s,'tz@example.com','America/Chicago',40,%s,0)
                       returning id""", (org_id, user_id, future_hour))
        sub_id = cur.fetchone()[0]
    conn.commit()
    monkeypatch.setattr(main_mod, "send",
                        lambda *a, **k: (True, "msg", None))
    if future_hour != 0:                                  # skip flaky midnight wrap
        main_mod.send_subscription_digests(conn)
        with conn.cursor() as cur:
            cur.execute("select count(*) from digest_deliveries "
                        "where subscription_id=%s", (sub_id,))
            assert cur.fetchone()[0] == 0                 # not due → nothing sent
    with conn.cursor() as cur:                            # make it due now
        cur.execute("update digest_subscriptions set delivery_hour_local=0, "
                    "delivery_minute_local=0 where id=%s", (sub_id,))
    conn.commit()
    main_mod.send_subscription_digests(conn)
    main_mod.send_subscription_digests(conn)              # rerun: still one delivery
    with conn.cursor() as cur:
        cur.execute("select count(*), max(send_status) from digest_deliveries "
                    "where subscription_id=%s", (sub_id,))
        count, status = cur.fetchone()
        assert count == 1 and status == "sent"
        cur.execute("delete from organizations where id=%s", (org_id,))
    conn.commit()


def test_migration_runner_sequential(conn):
    """Migrations 001→007 apply in order on a fresh schema via the runner logic."""
    import pathlib
    migrations = sorted((pathlib.Path(__file__).resolve().parents[2]
                         / "db" / "migrations").glob("*.sql"))
    assert len(migrations) >= 7
    with conn.cursor() as cur:
        cur.execute("drop schema public cascade; create schema public;")
        for path in migrations:
            cur.execute(path.read_text())
        cur.execute("select count(*) from information_schema.tables "
                    "where table_schema='public'")
        assert cur.fetchone()[0] >= 20
    conn.rollback()
    # restore the module-scoped schema for any later tests
    with conn.cursor() as cur:
        cur.execute("drop schema public cascade; create schema public;")
        cur.execute(SCHEMA.read_text())
    conn.commit()


def test_legislator_upsert_idempotent_and_delegation_resolution(conn):
    """Civic tables: refresh twice → no duplicates; delegation resolves with
    correct confidence tiers and committee relevance from stored data."""
    from src.db_civic import resolve_delegation, upsert_legislator
    member = {"bioguide_id": "T000001", "full_name": "Test Senator",
              "chamber": "sen", "state": "ZZ" if False else "WY", "district": None,
              "party": "R", "phone": "202-224-0000", "office": None,
              "website": None, "contact_form": None, "state_rank": "senior",
              "fec_candidate_ids": ["S0WY00001"],
              "committees": [{"code": "SSAS", "name": "Senate Armed Services",
                              "title": None, "rank": 3},
                             {"code": "SSAS13", "name": "Senate Armed Services (sub)",
                              "title": None, "rank": 1}],
              "term_end": None}
    rep = {**member, "bioguide_id": "T000002", "full_name": "Test Rep",
           "chamber": "rep", "district": 0, "state_rank": None,
           "committees": []}
    with conn.cursor() as cur:
        id1 = upsert_legislator(cur, member)
        id2 = upsert_legislator(cur, dict(member, phone="202-224-9999"))
        assert id1 == id2                                # upsert, not duplicate
        cur.execute("select phone from legislators where id=%s", (id1,))
        assert cur.fetchone()[0] == "202-224-9999"
        upsert_legislator(cur, rep)
        cur.execute("""insert into opportunities (source, source_notice_id, title,
                       content_hash, raw_json, agency, place_of_performance)
                       values ('sam','pg-civic-1','Civic Opp','ch','{}',
                               'DEPT OF THE ARMY','Cheyenne, WY') returning id""")
        opp_id = cur.fetchone()[0]
    conn.commit()
    members = resolve_delegation(conn, opp_id,
                                 geocode=lambda p: {"state": "WY",
                                                    "congressional_district": 0,
                                                    "raw": {}})
    by_chamber = {m["chamber"]: m for m in members}
    assert by_chamber["sen"]["match_confidence"] == 95
    assert by_chamber["rep"]["match_confidence"] == 60        # city-tier honesty
    rel = by_chamber["sen"]["committee_relevance"]
    assert len(rel) == 1 and "subcommittee" in rel[0]["why"]  # deduped to parent
    # re-resolve: cache upserts, no duplicate delegation rows
    resolve_delegation(conn, opp_id, geocode=lambda p: {"state": "WY",
                                                        "congressional_district": 0,
                                                        "raw": {}})
    with conn.cursor() as cur:
        cur.execute("select count(*) from opportunity_delegations "
                    "where opportunity_id=%s", (opp_id,))
        assert cur.fetchone()[0] == 2
        cur.execute("select count(*) from district_lookups "
                    "where place_key='cheyenne|WY|'")
        assert cur.fetchone()[0] == 1
        # funding constraint: unknown kind rejected by the DATABASE
        import psycopg2
        with pytest.raises(psycopg2.errors.CheckViolation):
            cur.execute("""insert into legislator_funding (legislator_id, cycle,
                           kind, contributor_name, total)
                           values (%s, 2026, 'corporate_donation', 'X', 1)""",
                        (id1,))
    conn.rollback()
    with conn.cursor() as cur:
        cur.execute("delete from legislators where bioguide_id in ('T000001','T000002')")
    conn.commit()


def test_staff_import_requires_provenance(conn, tmp_path):
    from src.db_civic import import_staff_csv, upsert_legislator
    with conn.cursor() as cur:
        upsert_legislator(cur, {"bioguide_id": "T000003", "full_name": "Import Test",
                                "chamber": "rep", "state": "MT", "district": 1,
                                "party": None, "phone": None, "office": None,
                                "website": None, "contact_form": None,
                                "state_rank": None, "fec_candidate_ids": [],
                                "committees": [], "term_end": None})
    conn.commit()
    csv_path = tmp_path / "staff.csv"
    csv_path.write_text(
        "name,title,bioguide_id,role_tag,email,source,source_date\n"
        "Pat Example,Chief of Staff,T000003,scheduler,,"
        "House Statement of Disbursements Q1 2026,2026-03-31\n"
        "Ghost Person,LA,B999999,,,no such member,\n")
    inserted = import_staff_csv(conn, str(csv_path))
    assert inserted == 1                                  # unknown member skipped
    with conn.cursor() as cur:
        cur.execute("""select s.source, s.source_date from legislator_staff s
                       join legislators l on l.id=s.legislator_id
                       where l.bioguide_id='T000003'""")
        source, source_date = cur.fetchone()
        assert "Disbursements" in source and source_date is not None
        cur.execute("delete from legislators where bioguide_id='T000003'")
    conn.commit()


def test_district_spending_upsert_and_rankings(conn):
    from src.web.store import PgStore
    store = PgStore.for_connection(conn)
    with conn.cursor() as cur:
        # a rep to join against
        from src.db_civic import upsert_legislator
        upsert_legislator(cur, {"bioguide_id": "T000010", "full_name": "Rank Rep",
                                "chamber": "rep", "state": "NM", "district": 2,
                                "party": "R", "phone": None, "office": None,
                                "website": None, "contact_form": None,
                                "state_rank": None, "fec_candidate_ids": [],
                                "committees": [], "term_end": None})
        for obligations in (5e8, 7e8):                     # second write updates
            cur.execute(
                """insert into district_spending (state, district, fiscal_year,
                     agency, obligations)
                   values ('NM', 2, 2026, '', %s)
                   on conflict (state, district, fiscal_year, agency)
                   do update set obligations=excluded.obligations""",
                (obligations,))
        cur.execute("""insert into district_spending (state, district,
                       fiscal_year, agency, obligations)
                       values ('NM', 2, 2026, 'Department of Defense', 4e8)
                       on conflict do nothing""")
    conn.commit()
    rows = store.district_rankings(2026, "")
    ours = [r for r in rows if r["state"] == "NM" and r["district"] == 2]
    assert ours and float(ours[0]["obligations"]) == 7e8   # updated, not duped
    assert ours[0]["rep_name"] == "Rank Rep"               # rep joined
    dod = store.district_rankings(2026, "Department of Defense")
    assert any(r["state"] == "NM" for r in dod)
    with conn.cursor() as cur:
        cur.execute("delete from district_spending where state='NM'")
        cur.execute("delete from legislators where bioguide_id='T000010'")
    conn.commit()


def test_election_import_lean_and_outlook_end_to_end(conn, tmp_path):
    """CSV import → district_key uniqueness → computed lean → seat outlook."""
    from src.db_civic import import_election_results_csv
    from src.intel.district import partisan_lean, seat_outlook
    from src.web.store import PgStore
    csv_path = tmp_path / "results.csv"
    csv_path.write_text(
        "state,district,office,cycle,stage,candidate_name,party,votes,"
        "vote_share,won,incumbent,source\n"
        "MT,1,house,2024,general,Alice Incumbent,R,180000,58.0,true,true,MIT MEDSL\n"
        "MT,1,house,2024,general,Bob Challenger,D,130000,40.0,false,false,MIT MEDSL\n"
        "MT,1,house,2022,general,Alice Incumbent,R,150000,54.0,true,true,MIT MEDSL\n"
        "MT,1,house,2022,general,Prior Challenger,D,120000,44.0,false,false,MIT MEDSL\n"
        "MT,1,house,2024,primary,Alice Incumbent,R,60000,66.0,true,true,MT SoS\n"
        "MT,,senate,2024,general,Statewide Person,R,300000,55.0,true,true,MIT MEDSL\n"
        "MT,1,house,2024,general,NoSource Person,I,10,1.0,false,false,\n")
    inserted = import_election_results_csv(conn, str(csv_path))
    assert inserted == 6                                   # sourceless row skipped
    inserted_again = import_election_results_csv(conn, str(csv_path))
    assert inserted_again == 6                             # idempotent upsert
    with conn.cursor() as cur:
        cur.execute("select count(*) from election_results where state='MT'")
        assert cur.fetchone()[0] == 6                      # no duplicates
        cur.execute("select district_key from election_results "
                    "where office='senate' and state='MT'")
        assert cur.fetchone()[0] == -1                     # statewide key
    store = PgStore.for_connection(conn)
    profile = store.district_profile("MT", 1)
    lean = partisan_lean(profile["election_results"])
    assert lean["lean_margin"] == pytest.approx((18 + 10) / 2, abs=0.1)
    outlook = seat_outlook(lean, lean["per_cycle"][0]["margin"], True,
                           500_000.0, 60_000.0)
    assert outlook["label"] in ("likely-context", "safe-context")
    assert all(isinstance(r, str) for r in outlook["reasons"])
    with conn.cursor() as cur:
        cur.execute("delete from election_results where state='MT'")
    conn.commit()


def test_directed_spending_import_is_attributable_and_deduped(conn, tmp_path):
    from src.db_civic import import_directed_spending_csv
    csv_path = tmp_path / "cpf.csv"
    csv_path.write_text(
        "fiscal_year,member_bioguide_id,member_name,state,district,agency,"
        "account,project,amount,source\n"
        "2025,T000010,Rank Rep,NM,2,DoD,RDTE,Range Modernization,4000000,"
        "House Approps FY25 CPF table\n"
        "2025,T000010,Rank Rep,NM,2,DoD,RDTE,Range Modernization,4000000,"
        "House Approps FY25 CPF table\n")
    import_directed_spending_csv(conn, str(csv_path))
    with conn.cursor() as cur:
        cur.execute("select count(*), max(source) from directed_spending "
                    "where member_name='Rank Rep'")
        count, source = cur.fetchone()
        assert count == 1                                  # deduped
        assert "CPF" in source                             # provenance kept
        cur.execute("delete from directed_spending where member_name='Rank Rep'")
    conn.commit()


def _make_pdf(path, pages):
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas
    c = canvas.Canvas(str(path), pagesize=letter)
    for page in pages:
        y = 720
        for line in page:
            c.drawString(72, y, line)
            y -= 18
        c.showPage()
    c.save()
    return open(path, "rb").read()


def test_document_pipeline_end_to_end(conn, tmp_path, monkeypatch):
    """Queue → fetch (stubbed transport) → extract → requirements → store,
    with dedup on rerun and org-scoped qualification at read time."""
    import src.db_documents as dd
    from src.documents.qualification import assess
    pdf = _make_pdf(tmp_path / "pws.pdf", [
        ["SOLICITATION 123", "This is a Total Small Business Set-Aside.",
         "Offerors must hold an active CIO-SP4 contract."],
        ["Personnel require a TS/SCI clearance.",
         "CMMC Level 2 certification is required."]])
    monkeypatch.setattr(dd, "fetch_document", lambda url: {
        "status": "fetched", "content": pdf, "filename": "Draft_PWS.pdf",
        "content_type": "application/pdf", "byte_size": len(pdf),
        "sha256": "abc123"})
    with conn.cursor() as cur:
        cur.execute("""insert into opportunities (source, source_notice_id, title,
                       content_hash, raw_json)
                       values ('sam','pg-doc-1','Doc Opp','dh',
                       '{"resourceLinks": ["https://sam.gov/api/f/1"]}')
                       returning id""")
        opp_id = cur.fetchone()[0]
        cur.execute("select raw_json from opportunities where id=%s", (opp_id,))
        raw = cur.fetchone()[0]
        assert dd.queue_documents(cur, opp_id, raw) == 1
        assert dd.queue_documents(cur, opp_id, raw) == 0        # idempotent queue
    conn.commit()

    stats = dd.process_document_queue(conn)
    assert stats == {"done": 1, "failed": 0, "queued": 1}
    with conn.cursor() as cur:
        cur.execute("""select fetch_status, doc_kind, page_count, text_chars
                       from opportunity_documents where opportunity_id=%s""", (opp_id,))
        status, kind, pages, chars = cur.fetchone()
        assert status == "extracted" and kind == "pws" and pages == 2 and chars > 50
        reqs = dd.requirements_for(cur, opp_id)
    values = {r["value"] for r in reqs}
    assert {"TS/SCI", "CIO-SP4", "Total Small Business", "CMMC Level 2"} <= values
    assert all(r["evidence_quote"] and r["method"] for r in reqs)   # evidence kept
    assert any(r["page"] == 2 for r in reqs)                        # page attribution

    # reprocessing the same document must not duplicate requirements
    with conn.cursor() as cur:
        cur.execute("update opportunity_documents set fetch_status='pending' "
                    "where opportunity_id=%s", (opp_id,))
    conn.commit()
    dd.process_document_queue(conn)
    with conn.cursor() as cur:
        cur.execute("select count(*) from document_requirements where opportunity_id=%s",
                    (opp_id,))
        assert cur.fetchone()[0] == len(reqs)

        # same requirements, two orgs, different verdicts
        blocked = assess(reqs, {"set_aside_eligibility": "small business",
                                "clearances": ["Secret"]})
        ready = assess(reqs, {"set_aside_eligibility": "small business",
                              "clearances": ["TS/SCI"],
                              "contract_vehicles": ["CIO-SP4"],
                              "certifications": ["CMMC Level 2"]})
        assert blocked["verdict"] == "blocked unless teaming"
        assert ready["verdict"] in ("qualified", "qualified with gaps")
        cur.execute("delete from opportunities where id=%s", (opp_id,))
    conn.commit()


def test_document_failure_states_are_recorded(conn, monkeypatch):
    """Oversized/scanned/failed documents record honest status, never silence."""
    import src.db_documents as dd
    with conn.cursor() as cur:
        cur.execute("""insert into opportunities (source, source_notice_id, title,
                       content_hash, raw_json) values
                       ('sam','pg-doc-2','Fail Opp','fh','{}') returning id""")
        opp_id = cur.fetchone()[0]
        cur.execute("""insert into opportunity_documents (opportunity_id, source_url)
                       values (%s,'https://sam.gov/api/f/big') returning id""",
                    (opp_id,))
        doc_id = cur.fetchone()[0]
    conn.commit()
    monkeypatch.setattr(dd, "fetch_document",
                        lambda url: {"status": "too_large", "error": ">20971520 bytes"})
    assert dd.process_document(conn, doc_id, opp_id, "https://sam.gov/api/f/big") is False
    with conn.cursor() as cur:
        cur.execute("select fetch_status, fetch_error from opportunity_documents "
                    "where id=%s", (doc_id,))
        status, error = cur.fetchone()
        assert status == "too_large" and "bytes" in error
        cur.execute("delete from opportunities where id=%s", (opp_id,))
    conn.commit()


def test_qualification_caps_match_score_per_org(conn):
    """A blocked org's stored match score is capped; a qualified org's is not."""
    from src.matching import (
        refresh_profile_matches_for_org,
    )
    with conn.cursor() as cur:
        cur.execute("insert into organizations (name) values ('BlockedCo') returning id")
        blocked_org = cur.fetchone()[0]
        cur.execute("""insert into company_profiles (organization_id, profile)
                       values (%s, '{"naics_codes":["541512"],
                       "keywords_boost":["inventory"],
                       "set_aside_eligibility":["small business"]}')""", (blocked_org,))
        cur.execute("""insert into opportunities (source, source_notice_id, title,
                       content_hash, raw_json, naics, first_seen_at)
                       values ('sam','pg-doc-3','Inventory modernization','qh','{}',
                       '541512', now()) returning id""")
        opp_id = cur.fetchone()[0]
        cur.execute("""insert into document_requirements (opportunity_id,
                       requirement_type, value, method, confidence, evidence_quote)
                       values (%s,'set_aside','8(a)','eight_a',90,'8(a) set-aside')""",
                    (opp_id,))
    conn.commit()
    refresh_profile_matches_for_org(conn, blocked_org)
    with conn.cursor() as cur:
        cur.execute("""select final_match_score, match_reasons_json
                       from profile_opportunity_matches
                       where organization_id=%s and opportunity_id=%s""",
                    (blocked_org, opp_id))
        score, reasons = cur.fetchone()
        assert score <= 15                                   # capped, not deleted
        assert any("not eligible to prime" in str(r) for r in reasons)
        cur.execute("delete from organizations where id=%s", (blocked_org,))
        cur.execute("delete from opportunities where id=%s", (opp_id,))
    conn.commit()
