"""Data access for the web app. TENANT ISOLATION LIVES HERE.

Every org-scoped method takes org_id as an explicit parameter, and the app
layer derives org_id ONLY from the authenticated session — never from the
client. Opportunity/dossier data is globally readable by authenticated users;
profiles, tracked items, saved searches, subscriptions, and feedback are
org-scoped in every query.

Two implementations:
  PgStore       — production (Postgres)
  MemoryStore   — tests (tests/test_tenant_isolation.py exercises the same
                  interface the app uses)
"""
import contextlib
import json
from datetime import datetime, timezone

from .. import db as core_db
from .auth import hash_token

TRACK_STATUSES = ("watching", "researching", "pursuing", "submitted", "won", "lost", "ignored")


class PgStore:
    """Postgres store with a thread-safe connection pool and a transaction per
    operation. Every `with self.cursor() as cur:` block is one transaction:
    commit on success, rollback on exception — so multi-statement writes such
    as signup (user + org + membership) and subscription replacement are
    atomic. Pool size: DB_POOL_MIN/DB_POOL_MAX (defaults 1/5 for web; workers
    should set 1/2)."""

    def __init__(self):
        self._pool = None
        self._external_conn = None      # tests inject one connection they manage

    @classmethod
    def for_connection(cls, conn):
        """Test/tooling constructor: run every operation on the given
        connection WITHOUT committing — the caller owns the transaction."""
        store = cls.__new__(cls)
        store._pool = None
        store._external_conn = conn
        return store

    def _get_pool(self):
        if self._pool is None:
            import os as _os

            from psycopg2 import pool as _pgpool
            self._pool = _pgpool.ThreadedConnectionPool(
                int(_os.getenv("DB_POOL_MIN", "1")),
                int(_os.getenv("DB_POOL_MAX", "5")),
                core_db.DATABASE_URL or core_db.require("DATABASE_URL"))
        return self._pool

    @staticmethod
    def _checkout(pool, timeout_seconds: float = 5.0):
        """psycopg2's ThreadedConnectionPool raises immediately when exhausted;
        a request burst should QUEUE briefly, not 500. Bounded wait, then fail."""
        import time as _time

        from psycopg2 import pool as _pgpool
        deadline = _time.monotonic() + timeout_seconds
        while True:
            try:
                return pool.getconn()
            except _pgpool.PoolError:
                if _time.monotonic() >= deadline:
                    raise
                _time.sleep(0.05)

    @contextlib.contextmanager
    def cursor(self):
        """One transaction: checkout → cursor → commit/rollback → return."""
        if self._external_conn is not None:
            with self._external_conn.cursor() as cur:
                yield cur               # caller commits/rolls back
            return
        pool = self._get_pool()
        conn = self._checkout(pool)
        try:
            with conn.cursor() as cur:
                yield cur
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            pool.putconn(conn)

    @contextlib.contextmanager
    def raw_conn(self):
        """A pooled connection for code that manages its own transactions
        (e.g. the matching refresh, which commits in batches)."""
        if self._external_conn is not None:
            yield self._external_conn
            return
        pool = self._get_pool()
        conn = self._checkout(pool)
        try:
            yield conn
        finally:
            pool.putconn(conn)

    # ---- users / orgs / sessions ----
    def create_user_with_org(self, email, password_hash, org_name):
        with self.cursor() as cur:
            cur.execute("insert into users (email, password_hash) values (%s,%s) returning id",
                        (email, password_hash))
            user_id = cur.fetchone()[0]
            cur.execute("insert into organizations (name) values (%s) returning id", (org_name,))
            org_id = cur.fetchone()[0]
            cur.execute("insert into organization_members (organization_id, user_id, role) "
                        "values (%s,%s,'owner')", (org_id, user_id))
            return user_id, org_id

    def get_user_by_email(self, email):
        with self.cursor() as cur:
            cur.execute("select id, email, password_hash, email_verified_at from users "
                        "where email=%s and deleted_at is null", (email,))
            row = cur.fetchone()
        return (dict(zip(("id", "email", "password_hash", "email_verified_at"),
                         row, strict=True)) if row else None)

    def create_session(self, user_id, token_hash, expires_at):
        with self.cursor() as cur:
            cur.execute("insert into user_sessions (user_id, token_hash, expires_at) "
                        "values (%s,%s,%s)", (user_id, token_hash, expires_at))

    def user_org_for_session(self, token):
        with self.cursor() as cur:
            cur.execute(
                """select u.id, u.email, m.organization_id, u.is_admin
                   from user_sessions s
                   join users u on u.id = s.user_id
                   join organization_members m on m.user_id = u.id
                   where s.token_hash=%s and s.expires_at > now() and s.revoked_at is null
                   limit 1""", (hash_token(token),))
            row = cur.fetchone()
        return (dict(zip(("user_id", "email", "org_id", "is_admin"), row, strict=True))
                if row else None)

    def revoke_session(self, token):
        with self.cursor() as cur:
            cur.execute("update user_sessions set revoked_at=now() where token_hash=%s",
                        (hash_token(token),))

    # ---- org-scoped: company profile ----
    def get_profile(self, org_id):
        with self.cursor() as cur:
            cur.execute("select profile from company_profiles where organization_id=%s "
                        "order by updated_at desc limit 1", (org_id,))
            row = cur.fetchone()
        return row[0] if row else None

    def upsert_profile(self, org_id, profile: dict):
        with self.cursor() as cur:
            cur.execute("select id from company_profiles where organization_id=%s", (org_id,))
            row = cur.fetchone()
            if row:
                cur.execute("update company_profiles set profile=%s, updated_at=now() where id=%s",
                            (json.dumps(profile), row[0]))
            else:
                cur.execute("insert into company_profiles (organization_id, profile) values (%s,%s)",
                            (org_id, json.dumps(profile)))

    # ---- org-scoped: company evidence graph (private tenant data) ----
    _PROJECT_COLS = ("id", "title", "customer_agency", "customer_office",
                     "contract_identifier", "role", "naics", "psc",
                     "period_start", "period_end", "value_total", "scope",
                     "technologies", "outcomes", "partners", "source_note")

    def list_projects(self, org_id):
        with self.cursor() as cur:
            cur.execute(
                """select id, title, customer_agency, customer_office,
                          contract_identifier, role, naics, psc, period_start,
                          period_end, value_total, scope, technologies,
                          outcomes, partners, source_note
                   from company_projects where organization_id=%s
                   order by coalesce(period_end, period_start) desc nulls last,
                            id desc
                   limit 200""", (org_id,))
            return [dict(zip(self._PROJECT_COLS, r, strict=True))
                    for r in cur.fetchall()]

    def add_project(self, org_id, fields: dict):
        with self.cursor() as cur:
            cur.execute(
                """insert into company_projects
                     (organization_id, title, customer_agency, customer_office,
                      contract_identifier, role, naics, psc, period_start,
                      period_end, value_total, scope, technologies, outcomes,
                      partners, source_note)
                   values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   returning id""",
                (org_id, fields.get("title"), fields.get("customer_agency"),
                 fields.get("customer_office"), fields.get("contract_identifier"),
                 fields.get("role"), fields.get("naics"), fields.get("psc"),
                 fields.get("period_start") or None,
                 fields.get("period_end") or None,
                 fields.get("value_total") or None, fields.get("scope"),
                 fields.get("technologies"), fields.get("outcomes"),
                 fields.get("partners"), fields.get("source_note")))
            return cur.fetchone()[0]

    def delete_project(self, org_id, project_id):
        with self.cursor() as cur:
            cur.execute("delete from company_projects "
                        "where organization_id=%s and id=%s",
                        (org_id, project_id))

    # ---- org-scoped: capture tasks ----
    def list_capture_tasks(self, org_id, opportunity_id=None, include_done=False):
        sql = """select t.id, t.opportunity_id, t.title, t.detail, t.owner,
                        t.due_date, t.status, t.source, o.title
                 from capture_tasks t
                 left join opportunities o on o.id = t.opportunity_id
                 where t.organization_id=%s"""
        params: list = [org_id]
        if opportunity_id is not None:
            sql += " and t.opportunity_id=%s"
            params.append(opportunity_id)
        if not include_done:
            sql += " and t.status='open'"
        sql += " order by t.due_date asc nulls last, t.id desc limit 300"
        with self.cursor() as cur:
            cur.execute(sql, params)
            cols = ("id", "opportunity_id", "title", "detail", "owner",
                    "due_date", "status", "source", "opportunity_title")
            return [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]

    def add_capture_task(self, org_id, title, detail=None, opportunity_id=None,
                         user_id=None, owner=None, due_date=None,
                         source="manual"):
        with self.cursor() as cur:
            cur.execute(
                """insert into capture_tasks
                     (organization_id, opportunity_id, user_id, title, detail,
                      owner, due_date, source)
                   values (%s,%s,%s,%s,%s,%s,%s,%s) returning id""",
                (org_id, opportunity_id, user_id, title, detail, owner,
                 due_date or None, source))
            return cur.fetchone()[0]

    def set_capture_task_status(self, org_id, task_id, status):
        if status not in ("open", "done", "dropped"):
            raise ValueError("invalid task status")
        with self.cursor() as cur:
            cur.execute("""update capture_tasks set status=%s, updated_at=now()
                           where organization_id=%s and id=%s""",
                        (status, org_id, task_id))

    # ---- org-scoped: tracking / feedback ----
    def set_tracked(self, org_id, opportunity_id, status, user_id=None):
        if status not in TRACK_STATUSES:
            raise ValueError("invalid status")
        with self.cursor() as cur:
            cur.execute(
                """insert into tracked_opportunities (organization_id, user_id, opportunity_id, status)
                   values (%s,%s,%s,%s)
                   on conflict (organization_id, opportunity_id)
                   do update set status=excluded.status""",
                (org_id, user_id, opportunity_id, status))

    def list_tracked(self, org_id):
        with self.cursor() as cur:
            cur.execute(
                """select t.opportunity_id, t.status, o.title, o.agency, o.response_deadline,
                          coalesce(c.score, 0), o.source_notice_id, o.url
                   from tracked_opportunities t
                   join opportunities o on o.id = t.opportunity_id
                   left join classifications c on c.opportunity_id = o.id
                   where t.organization_id=%s
                   order by t.created_at desc limit 200""", (org_id,))
            cols = ("opportunity_id", "status", "title", "agency", "response_deadline",
                    "score", "source_notice_id", "url")
            return [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]

    def record_feedback(self, org_id, opportunity_id, action, user_id=None,
                        user_email=None, notes=None):
        if org_id is None:
            raise ValueError("feedback requires an organization_id")
        with self.cursor() as cur:
            cur.execute(
                """insert into opportunity_feedback
                     (organization_id, opportunity_id, user_id, user_email, action, notes)
                   values (%s,%s,%s,%s,%s,%s)""",
                (org_id, opportunity_id, user_id, user_email, action, notes))
            self._learn(cur, org_id, opportunity_id, action)

    def _learn(self, cur, org_id, opportunity_id, action):
        """Feedback nudges org preference weights (same transaction)."""
        from ..learning import FEEDBACK_DELTAS, clamp_weight, features_for
        delta = FEEDBACK_DELTAS.get(action)
        if not delta:
            return
        cur.execute(
            """select o.naics, o.agency, c.category from opportunities o
               left join classifications c on c.opportunity_id=o.id
               where o.id=%s""", (opportunity_id,))
        row = cur.fetchone()
        if not row:
            return
        opp = dict(zip(("naics", "agency", "category"), row, strict=True))
        for feat in features_for(opp):
            cur.execute(
                """insert into org_preference_weights (organization_id, feature, weight)
                   values (%s,%s,%s)
                   on conflict (organization_id, feature)
                   do update set weight = greatest(-10, least(10,
                       org_preference_weights.weight + excluded.weight)),
                     updated_at=now()""",
                (org_id, feat, clamp_weight(delta)))

    def preference_weights(self, org_id):
        with self.cursor() as cur:
            cur.execute("select feature, weight from org_preference_weights "
                        "where organization_id=%s and weight <> 0 "
                        "order by abs(weight) desc, feature", (org_id,))
            return dict(cur.fetchall())

    def reset_preferences(self, org_id):
        with self.cursor() as cur:
            cur.execute("delete from org_preference_weights "
                        "where organization_id=%s", (org_id,))

    # ---- org-scoped: digest subscription ----
    def get_subscription(self, org_id):
        with self.cursor() as cur:
            cur.execute(
                """select email, timezone, min_score, active from digest_subscriptions
                   where organization_id=%s order by created_at desc limit 1""", (org_id,))
            row = cur.fetchone()
        return dict(zip(("email", "timezone", "min_score", "active"), row, strict=True)) if row else None

    def upsert_subscription(self, org_id, user_id, email, timezone_name, min_score,
                            active, delivery_hour=6, delivery_minute=30,
                            instant_alerts=False):
        # delete + insert inside ONE transaction (pooled cursor commits at exit)
        with self.cursor() as cur:
            cur.execute("delete from digest_subscriptions where organization_id=%s", (org_id,))
            cur.execute(
                """insert into digest_subscriptions
                     (organization_id, user_id, email, timezone, min_score, active,
                      delivery_hour_local, delivery_minute_local, instant_alerts)
                   values (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (org_id, user_id, email, timezone_name, int(min_score), bool(active),
                 max(0, min(23, int(delivery_hour))),
                 max(0, min(59, int(delivery_minute))), bool(instant_alerts)))

    # ---- global (authenticated) reads ----
    # Static SQL with optional parameters — no query text assembled from variables.
    _LIST_OPPS_SQL = """
        select o.id, coalesce(m.final_match_score, c.score, 0) as eff_score,
               o.title, o.agency, o.office, o.notice_type,
               o.set_aside, o.naics, o.response_deadline,
               d.pursuit_recommendation_json, d.incumbent_analysis_json,
               coalesce(t.status, m.status) as user_status
        from opportunities o
        left join classifications c on c.opportunity_id = o.id
        left join profile_opportunity_matches m
               on m.opportunity_id = o.id and m.organization_id = %s and not m.hidden
        left join opportunity_dossiers d on d.opportunity_id = o.id
        left join tracked_opportunities t
               on t.opportunity_id = o.id and t.organization_id = %s
        where coalesce(m.final_match_score, c.score, 0) >= %s
          and (%s::text is null or o.title ilike %s or o.agency ilike %s)
          and (%s::text is null or o.notice_type ilike %s)
        order by eff_score desc, o.first_seen_at desc limit %s"""

    def list_opportunities(self, org_id, q=None, min_score=0, notice_type=None, limit=100):
        q_like = f"%{q}%" if q else None
        nt_like = f"%{notice_type}%" if notice_type else None
        with self.cursor() as cur:
            cur.execute(
                self._LIST_OPPS_SQL,
                (org_id, org_id, min_score, q_like, q_like, q_like, nt_like, nt_like,
                 min(limit, 500)))
            cols = ("id", "score", "title", "agency", "office", "notice_type", "set_aside",
                    "naics", "response_deadline", "recommendation", "incumbent", "user_status")
            return [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]

    def get_opportunity(self, org_id, opp_id):
        with self.cursor() as cur:
            cur.execute(
                """select o.id, o.title, o.agency, o.office, o.office_location, o.notice_type,
                          o.naics, o.set_aside, o.posted_date, o.response_deadline,
                          o.place_of_performance, o.description_text, o.url, o.source_notice_id,
                          o.solicitation_number, o.enrichment_status, c.score, c.category,
                          c.reasons, c.components, c.recommended_action, t.status
                   from opportunities o
                   left join classifications c on c.opportunity_id = o.id
                   left join tracked_opportunities t
                          on t.opportunity_id = o.id and t.organization_id = %s
                   where o.id=%s""", (org_id, opp_id))
            row = cur.fetchone()
        if not row:
            return None
        cols = ("id", "title", "agency", "office", "office_location", "notice_type", "naics",
                "set_aside", "posted_date", "response_deadline", "place_of_performance",
                "description_text", "url", "source_notice_id", "solicitation_number",
                "enrichment_status", "score", "category", "reasons", "components",
                "recommended_action", "user_status")
        return dict(zip(cols, row, strict=True))

    def get_dossier(self, opp_id):
        from .. import db_intel
        with self.cursor() as cur:
            return db_intel.fetch_dossier(cur, opp_id)

    def mark_enrichment_pending(self, opp_id):
        with self.cursor() as cur:
            cur.execute("update opportunities set enrichment_status='pending' "
                        "where id=%s and enrichment_status not in ('running','done')", (opp_id,))

    def dashboard_counts(self, org_id, tz_name):
        with self.cursor() as cur:
            cur.execute(
                """select
                     count(*) filter (where (o.first_seen_at at time zone %s)::date = current_date),
                     count(*) filter (where c.score >= 80
                        and (o.first_seen_at at time zone %s)::date = current_date),
                     count(*) filter (where o.response_deadline between now() and now() + interval '7 days'),
                     (select count(*) from change_events e
                        join tracked_opportunities t on t.opportunity_id=e.opportunity_id
                        where t.organization_id=%s
                          and e.created_at > now() - interval '1 day'),
                     (select count(*) from change_events
                        where event_type='stage_transition'
                          and created_at > now() - interval '7 days'),
                     (select count(*) from opportunities where enrichment_status='pending')
                   from opportunities o
                   join classifications c on c.opportunity_id=o.id""",
                (tz_name, tz_name, org_id))
            row = cur.fetchone()
        keys = ("new_today", "high_match_today", "closing_7d", "tracked_changes_24h",
                "stage_transitions_7d", "dossier_queue")
        return dict(zip(keys, row, strict=True))

    def recent_events(self, limit=25):
        with self.cursor() as cur:
            cur.execute(
                """select e.event_type, e.detail, e.created_at, o.id, o.title
                   from change_events e join opportunities o on o.id=e.opportunity_id
                   order by e.created_at desc limit %s""", (min(limit, 100),))
            cols = ("event_type", "detail", "created_at", "opportunity_id", "title")
            return [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]


    # ---- security / accounts ----
    def rate_limit_allow(self, rate_key, limit, window_seconds):
        with self.cursor() as cur:
            cur.execute("insert into login_attempts (rate_key) values (%s)", (rate_key,))
            cur.execute(
                """select count(*) from login_attempts
                   where rate_key=%s
                     and created_at > now() - make_interval(secs => %s)""",
                (rate_key, window_seconds))
            return cur.fetchone()[0] <= limit

    def audit(self, event, org_id=None, user_id=None, ip=None, detail=None):
        with self.cursor() as cur:
            cur.execute(
                "insert into audit_log (organization_id, user_id, event, detail, ip) "
                "values (%s,%s,%s,%s,%s)",
                (org_id, user_id, event, json.dumps(detail or {}), ip))

    def mark_email_verified(self, user_id):
        with self.cursor() as cur:
            cur.execute("update users set email_verified_at=now() where id=%s", (user_id,))

    def set_password(self, user_id, password_hash):
        with self.cursor() as cur:
            cur.execute("update users set password_hash=%s where id=%s",
                        (password_hash, user_id))

    def revoke_all_sessions(self, user_id):
        with self.cursor() as cur:
            cur.execute("update user_sessions set revoked_at=now() "
                        "where user_id=%s and revoked_at is null", (user_id,))

    def deactivate_subscription(self, subscription_id):
        with self.cursor() as cur:
            cur.execute("update digest_subscriptions set active=false where id=%s",
                        (subscription_id,))

    # ---- per-org matching ----
    def set_match_status(self, org_id, opportunity_id, status):
        with self.cursor() as cur:
            cur.execute(
                """update profile_opportunity_matches set status=%s, updated_at=now()
                   where organization_id=%s and opportunity_id=%s""",
                (status, org_id, opportunity_id))

    def hide_match(self, org_id, opportunity_id):
        with self.cursor() as cur:
            cur.execute(
                """update profile_opportunity_matches set hidden=true, updated_at=now()
                   where organization_id=%s and opportunity_id=%s""",
                (org_id, opportunity_id))

    def request_match_refresh(self, org_id):
        """Rescore this org's recent opportunities after a profile edit."""
        try:
            from ..matching import refresh_profile_matches_for_org
            with self.raw_conn() as conn:
                refresh_profile_matches_for_org(conn, org_id)
        except Exception as exc:  # noqa: BLE001 — best-effort in the request path
            from ..log import log
            log("match_refresh_failed", org_id=org_id, error=type(exc).__name__)

    def delete_account(self, user_id):
        """Soft delete: blocks login, kills sessions, stops that user's digests.
        Org data is retained (other members may exist); hard purge is a manual
        admin operation documented in the runbook."""
        with self.cursor() as cur:
            cur.execute("update users set deleted_at=now() where id=%s", (user_id,))
            cur.execute("update user_sessions set revoked_at=now() "
                        "where user_id=%s and revoked_at is null", (user_id,))
            cur.execute("update digest_subscriptions set active=false "
                        "where user_id=%s", (user_id,))

    # ---- saved views (org-scoped) ----
    def save_view(self, org_id, user_id, name, criteria):
        with self.cursor() as cur:
            cur.execute(
                """insert into saved_searches (organization_id, user_id, name, criteria)
                   values (%s,%s,%s,%s)
                   on conflict (organization_id, name)
                   do update set criteria=excluded.criteria, user_id=excluded.user_id
                   returning id""",
                (org_id, user_id, name, json.dumps(criteria)))
            return cur.fetchone()[0]

    def list_views(self, org_id):
        with self.cursor() as cur:
            cur.execute("select id, name, criteria from saved_searches "
                        "where organization_id=%s order by name", (org_id,))
            return [dict(zip(("id", "name", "criteria"), r, strict=True))
                    for r in cur.fetchall()]

    def get_view(self, org_id, view_id):
        with self.cursor() as cur:
            cur.execute("select id, name, criteria from saved_searches "
                        "where organization_id=%s and id=%s", (org_id, view_id))
            row = cur.fetchone()
        return dict(zip(("id", "name", "criteria"), row, strict=True)) if row else None

    def delete_view(self, org_id, view_id):
        with self.cursor() as cur:
            cur.execute("delete from saved_searches "
                        "where organization_id=%s and id=%s", (org_id, view_id))

    # ---- dashboard decision panels ----
    def closing_soon(self, org_id, days=7, limit=8):
        with self.cursor() as cur:
            cur.execute(
                """select o.id, o.title, o.agency, o.response_deadline,
                          coalesce(m.final_match_score, c.score, 0) as score,
                          coalesce(t.status, m.status) as user_status
                   from opportunities o
                   left join classifications c on c.opportunity_id=o.id
                   left join profile_opportunity_matches m
                          on m.opportunity_id=o.id and m.organization_id=%s and not m.hidden
                   left join tracked_opportunities t
                          on t.opportunity_id=o.id and t.organization_id=%s
                   where o.response_deadline between now()
                         and now() + make_interval(days => %s)
                     and coalesce(m.final_match_score, c.score, 0) >= 40
                   order by o.response_deadline limit %s""",
                (org_id, org_id, days, min(limit, 25)))
            cols = ("id", "title", "agency", "response_deadline", "score", "user_status")
            return [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]

    def stage_transitions_for_org(self, org_id, limit=8):
        """Recent stage advances on opportunities this org tracks or matches."""
        with self.cursor() as cur:
            cur.execute(
                """select distinct on (e.id) e.detail, e.created_at, o.id, o.title
                   from change_events e
                   join opportunities o on o.id = e.opportunity_id
                   left join tracked_opportunities t
                          on t.opportunity_id = o.id and t.organization_id = %s
                   left join profile_opportunity_matches m
                          on m.opportunity_id = o.id and m.organization_id = %s
                   where e.event_type='stage_transition'
                     and e.created_at > now() - interval '14 days'
                     and (t.id is not null or coalesce(m.final_match_score, 0) >= 70)
                   order by e.id desc limit %s""",
                (org_id, org_id, min(limit, 25)))
            cols = ("detail", "created_at", "opportunity_id", "title")
            return [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]

    def latest_delivery(self, org_id):
        with self.cursor() as cur:
            cur.execute(
                """select digest_date, send_status, opportunity_count
                   from digest_deliveries where organization_id=%s
                   order by digest_date desc limit 1""", (org_id,))
            row = cur.fetchone()
        return (dict(zip(("digest_date", "status", "opportunities"), row, strict=True))
                if row else None)

    def org_plan(self, org_id):
        with self.cursor() as cur:
            cur.execute("select plan from organizations where id=%s", (org_id,))
            row = cur.fetchone()
        return row[0] if row else "early_access"

    # ---- delegation intelligence (global public-record reads) ----
    def delegation_for_opportunity(self, opportunity_id):
        """Cached delegation; resolves on first view (state-tier without a
        geocoder — the enrichment worker upgrades matches with Census lookups)."""
        with self.cursor() as cur:
            cur.execute(
                """select l.bioguide_id, l.full_name, l.chamber, l.state,
                          l.district, l.party, l.phone, l.website, l.state_rank,
                          d.match_method, d.match_confidence, d.committee_relevance
                   from opportunity_delegations d
                   join legislators l on l.id = d.legislator_id
                   where d.opportunity_id=%s
                   order by l.chamber desc, l.state_rank nulls last""",
                (opportunity_id,))
            cols = ("bioguide_id", "full_name", "chamber", "state", "district",
                    "party", "phone", "website", "state_rank", "match_method",
                    "match_confidence", "committee_relevance")
            rows = [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]
        if rows:
            return rows
        try:
            from ..db_civic import resolve_delegation
            with self.raw_conn() as conn:
                resolve_delegation(conn, opportunity_id)
        except Exception as exc:  # noqa: BLE001 — panel degrades to empty
            from ..log import log
            log("delegation_resolve_failed", opportunity_id=opportunity_id,
                error=type(exc).__name__)
            return []
        with self.cursor() as cur:
            cur.execute(
                """select l.bioguide_id, l.full_name, l.chamber, l.state,
                          l.district, l.party, l.phone, l.website, l.state_rank,
                          d.match_method, d.match_confidence, d.committee_relevance
                   from opportunity_delegations d
                   join legislators l on l.id = d.legislator_id
                   where d.opportunity_id=%s
                   order by l.chamber desc, l.state_rank nulls last""",
                (opportunity_id,))
            cols = ("bioguide_id", "full_name", "chamber", "state", "district",
                    "party", "phone", "website", "state_rank", "match_method",
                    "match_confidence", "committee_relevance")
            return [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]

    def get_legislator(self, bioguide_id):
        with self.cursor() as cur:
            cur.execute(
                """select id, bioguide_id, full_name, chamber, state, district,
                          party, phone, office, website, contact_form, state_rank,
                          committees, updated_at
                   from legislators where bioguide_id=%s""", (bioguide_id,))
            row = cur.fetchone()
            if not row:
                return None
            cols = ("id", "bioguide_id", "full_name", "chamber", "state",
                    "district", "party", "phone", "office", "website",
                    "contact_form", "state_rank", "committees", "updated_at")
            member = dict(zip(cols, row, strict=True))
            cur.execute(
                """select name, title, role_tag, email, source, source_date
                   from legislator_staff where legislator_id=%s
                   order by source_date desc nulls last, name""", (member["id"],))
            member["staff"] = [dict(zip(("name", "title", "role_tag", "email",
                                         "source", "source_date"), r, strict=True))
                               for r in cur.fetchall()]
            cur.execute(
                """select cycle, kind, contributor_name, total, contribution_count
                   from legislator_funding where legislator_id=%s
                   order by cycle desc, kind, total desc limit 40""",
                (member["id"],))
            member["funding"] = [dict(zip(("cycle", "kind", "contributor_name",
                                           "total", "contribution_count"),
                                          r, strict=True)) for r in cur.fetchall()]
        return member

    # ---- document intelligence (global facts about the notice) ----
    def documents_for_opportunity(self, opportunity_id):
        from ..db_documents import documents_for
        with self.cursor() as cur:
            return documents_for(cur, opportunity_id)

    def requirements_for_opportunity(self, opportunity_id):
        from ..db_documents import requirements_for
        with self.cursor() as cur:
            return requirements_for(cur, opportunity_id)

    # ---- district intelligence (global public-record reads) ----
    def district_rankings(self, fiscal_year, agency="", limit=50):
        """Districts ranked by obligations, joined to who represents them."""
        with self.cursor() as cur:
            cur.execute(
                """select s.state, s.district, s.obligations, s.award_count,
                          l.bioguide_id, l.full_name, l.party
                   from district_spending s
                   left join legislators l on l.state = s.state
                        and l.chamber = 'rep' and coalesce(l.district, 0) = s.district
                   where s.fiscal_year=%s and s.agency=%s
                   order by s.obligations desc limit %s""",
                (fiscal_year, agency or "", min(limit, 200)))
            cols = ("state", "district", "obligations", "award_count",
                    "bioguide_id", "rep_name", "party")
            return [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]

    def district_agency_years(self):
        with self.cursor() as cur:
            cur.execute("select distinct fiscal_year from district_spending "
                        "order by fiscal_year desc")
            years = [r[0] for r in cur.fetchall()]
            cur.execute("select distinct agency from district_spending "
                        "where agency <> '' order by agency")
            agencies = [r[0] for r in cur.fetchall()]
        return years, agencies

    def district_profile(self, state, district):
        """Money history + representation + electoral context for one seat."""
        with self.cursor() as cur:
            cur.execute(
                """select fiscal_year, agency, obligations from district_spending
                   where state=%s and district=%s
                   order by fiscal_year desc, obligations desc""",
                (state, district))
            spending = [dict(zip(("fiscal_year", "agency", "obligations"),
                                 r, strict=True)) for r in cur.fetchall()]
            cur.execute(
                """select bioguide_id, full_name, party, committees
                   from legislators where state=%s and chamber='rep'
                        and coalesce(district, 0)=%s""", (state, district))
            row = cur.fetchone()
            rep = (dict(zip(("bioguide_id", "full_name", "party", "committees"),
                            row, strict=True)) if row else None)
            cur.execute(
                """select cycle, stage, candidate_name, party, vote_share, won,
                          incumbent, source
                   from election_results
                   where state=%s and district_key=%s and office='house'
                   order by cycle desc, stage, vote_share desc nulls last""",
                (state, district if district else 0))
            results = [dict(zip(("cycle", "stage", "candidate_name", "party",
                                 "vote_share", "won", "incumbent", "source"),
                                r, strict=True)) for r in cur.fetchall()]
            cur.execute(
                """select fiscal_year, member_name, project, amount, agency, source
                   from directed_spending where state=%s
                        and coalesce(district, -1) in (%s, -1)
                   order by fiscal_year desc, amount desc limit 25""",
                (state, district))
            directed = [dict(zip(("fiscal_year", "member_name", "project",
                                  "amount", "agency", "source"), r, strict=True))
                        for r in cur.fetchall()]
            cur.execute(
                """select candidate_name, is_incumbent, receipts, cash_on_hand,
                          cycle
                   from candidate_finance
                   where state=%s and coalesce(district, 0)=%s and office='house'
                   order by cycle desc, receipts desc nulls last limit 12""",
                (state, district))
            finance = [dict(zip(("candidate_name", "is_incumbent", "receipts",
                                 "cash_on_hand", "cycle"), r, strict=True))
                       for r in cur.fetchall()]
        return {"state": state, "district": district, "rep": rep,
                "spending": spending, "election_results": results,
                "directed": directed, "finance": finance}

    # ---- intelligence pages (global, authenticated reads of stored data) ----
    def list_agencies(self, limit=100):
        """Buyer offices ranked by recent obligations (from materialized stats)."""
        with self.cursor() as cur:
            cur.execute(
                """select o.id, o.department_name, o.subtier_name, o.office_name,
                          o.organization_code, o.source_confidence,
                          coalesce(sum(s.total_obligations), 0) as obligations,
                          coalesce(sum(s.award_count), 0) as awards,
                          max(s.fiscal_year) as latest_fy
                   from buyer_offices o
                   left join office_market_stats s on s.buyer_office_id = o.id
                   group by o.id
                   order by obligations desc nulls last, o.office_name
                   limit %s""", (min(limit, 500),))
            cols = ("id", "department", "subtier", "office", "org_code", "confidence",
                    "obligations", "awards", "latest_fy")
            return [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]

    def get_agency(self, office_id):
        with self.cursor() as cur:
            cur.execute(
                """select id, department_name, subtier_name, office_name, organization_code,
                          full_parent_path_name, location_json, source_confidence
                   from buyer_offices where id=%s""", (office_id,))
            row = cur.fetchone()
            if not row:
                return None
            cols = ("id", "department", "subtier", "office", "org_code", "path",
                    "location", "confidence")
            office = dict(zip(cols, row, strict=True))
            cur.execute(
                """select fiscal_year, naics, award_count, total_obligations,
                          median_award_value, unique_vendor_count, top_vendor_share,
                          set_aside_share, competed_share
                   from office_market_stats where buyer_office_id=%s
                   order by fiscal_year desc, total_obligations desc limit 40""", (office_id,))
            stat_cols = ("fiscal_year", "naics", "award_count", "total_obligations",
                         "median_award_value", "unique_vendor_count", "top_vendor_share",
                         "set_aside_share", "competed_share")
            office["stats"] = [dict(zip(stat_cols, r, strict=True)) for r in cur.fetchall()]
            cur.execute(
                """select award_date, recipient_name, award_title, obligated_amount, naics
                   from contract_awards
                   where (%s::text is not null and awarding_office_code=%s)
                      or (%s::text is not null and upper(awarding_office)=upper(%s))
                   order by award_date desc nulls last limit 15""",
                (office["org_code"], office["org_code"], office["office"], office["office"]))
            aw_cols = ("award_date", "vendor", "title", "obligated_amount", "naics")
            office["recent_awards"] = [dict(zip(aw_cols, r, strict=True))
                                       for r in cur.fetchall()]
            return office

    def list_vendors(self, q=None, limit=100):
        with self.cursor() as cur:
            cur.execute(
                """select id, recipient_name, recipient_uei, total_obligations, award_count,
                          first_award_date, last_award_date
                   from vendor_profiles
                   where (%s::text is null or recipient_name ilike %s)
                   order by total_obligations desc limit %s""",
                (f"%{q}%" if q else None, f"%{q}%" if q else None, min(limit, 500)))
            cols = ("id", "name", "uei", "obligations", "awards", "first_award", "last_award")
            return [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]

    def get_vendor(self, vendor_id):
        with self.cursor() as cur:
            cur.execute(
                """select id, recipient_name, recipient_uei, total_obligations, award_count,
                          first_award_date, last_award_date, top_agencies_json,
                          top_naics_json, top_offices_json
                   from vendor_profiles where id=%s""", (vendor_id,))
            row = cur.fetchone()
        if not row:
            return None
        cols = ("id", "name", "uei", "obligations", "awards", "first_award", "last_award",
                "top_agencies", "top_naics", "top_offices")
        return dict(zip(cols, row, strict=True))

    def get_lineage(self, solicitation_number, exclude_opp_id=None):
        """Lifecycle timeline: every notice sharing this solicitation number."""
        if not solicitation_number:
            return []
        with self.cursor() as cur:
            cur.execute(
                """select l.opportunity_id, l.stage, l.linked_at, o.title, o.posted_date
                   from opportunity_lineage l
                   join opportunities o on o.id = l.opportunity_id
                   where l.solicitation_number=%s
                   order by o.posted_date nulls last, l.linked_at""",
                (solicitation_number,))
            cols = ("opportunity_id", "stage", "linked_at", "title", "posted_date")
            return [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]

    def pipeline_report(self, org_id):
        """Pursuit pipeline grouped by capture status (org-scoped)."""
        rows = self.list_tracked(org_id)
        grouped = {status: [] for status in TRACK_STATUSES}
        for r in rows:
            grouped.setdefault(r["status"], []).append(r)
        return grouped

    _MARKET_SQL = """
        select naics,
               count(*) filter (where award_date > current_date - interval '1 year'),
               count(*) filter (where award_date > current_date - interval '3 years'),
               count(*) filter (where award_date > current_date - interval '5 years'),
               coalesce(sum(obligated_amount) filter
                        (where award_date > current_date - interval '5 years'), 0),
               coalesce(avg(obligated_amount) filter
                        (where award_date > current_date - interval '5 years'), 0)
        from contract_awards
        where naics = any(%s)
        group by naics"""

    def market_intel(self, category_naics: dict[str, list[str]]) -> list[dict]:
        """Per-category rollups from stored awards (never live APIs)."""
        all_naics = sorted({n for codes in category_naics.values() for n in codes})
        by_naics = {}
        with self.cursor() as cur:
            cur.execute(self._MARKET_SQL, (all_naics,))
            for r in cur.fetchall():
                by_naics[r[0]] = r
            cur.execute(
                """select naics, count(*) from opportunities
                   where first_seen_at > now() - interval '30 days'
                     and naics = any(%s) group by naics""", (all_naics,))
            opp_counts = dict(cur.fetchall())
        rows = []
        for category, codes in category_naics.items():
            picked = [by_naics[c] for c in codes if c in by_naics]
            rows.append({
                "category": category,
                "naics": codes,
                "opps_30d": sum(opp_counts.get(c, 0) for c in codes),
                "awards_1y": sum(p[1] for p in picked),
                "awards_3y": sum(p[2] for p in picked),
                "awards_5y": sum(p[3] for p in picked),
                "obligations_5y": float(sum(p[4] for p in picked)),
                "avg_award": (float(sum(p[4] for p in picked))
                              / max(1, sum(p[3] for p in picked))),
            })
        rows.sort(key=lambda r: r["obligations_5y"], reverse=True)
        return rows

    def admin_ops(self):
        """Failed enrichments + failed/pending emails for the admin ops view."""
        with self.cursor() as cur:
            cur.execute(
                """select id, title, agency, enriched_at from opportunities
                   where enrichment_status='failed'
                   order by enriched_at desc nulls last limit 50""")
            failed_enrich = [dict(zip(("id", "title", "agency", "at"), r, strict=True))
                             for r in cur.fetchall()]
            cur.execute(
                """select digest_date, send_status, send_error, send_attempted_at
                   from email_digests
                   where send_status is distinct from 'sent'
                   order by digest_date desc limit 30""")
            failed_email = [dict(zip(("digest_date", "status", "error", "at"), r, strict=True))
                            for r in cur.fetchall()]
            cur.execute("select count(*) from opportunities where enrichment_status='pending'")
            pending = cur.fetchone()[0]
            cur.execute(
                """select job_name, status, started_at, finished_at, records_fetched,
                          records_failed, error_summary
                   from job_runs order by started_at desc limit 20""")
            jobs = [dict(zip(("job", "status", "started", "finished", "fetched",
                              "failed", "error"), r, strict=True)) for r in cur.fetchall()]
            cur.execute(
                """select u.email, o.name, u.created_at from users u
                   join organization_members m on m.user_id=u.id
                   join organizations o on o.id=m.organization_id
                   order by u.created_at desc limit 10""")
            signups = [dict(zip(("email", "org", "at"), r, strict=True))
                       for r in cur.fetchall()]
            cur.execute(
                """select action, count(*) from opportunity_feedback
                   where created_at > now() - interval '30 days'
                   group by action order by count(*) desc""")
            feedback = [dict(zip(("action", "count"), r, strict=True))
                        for r in cur.fetchall()]
            cur.execute(
                """select send_status, count(*) from digest_deliveries
                   where digest_date > current_date - 7 group by send_status""")
            deliveries = [dict(zip(("status", "count"), r, strict=True))
                          for r in cur.fetchall()]
        return {"failed_enrichments": failed_enrich, "failed_emails": failed_email,
                "enrichment_pending": pending, "job_runs": jobs,
                "recent_signups": signups, "feedback_stats": feedback,
                "delivery_stats": deliveries}


class MemoryStore:
    """In-memory implementation of the same interface, for tests."""

    def __init__(self):
        self.users, self.orgs, self.members = {}, {}, []
        self.sessions, self.profiles, self.tracked = {}, {}, {}
        self.subs, self.feedback = {}, []
        self.opportunities, self.dossiers = {}, {}
        self.agencies, self.vendors, self.lineage = {}, {}, {}
        self.matches, self.rate, self.audit_events, self.match_refreshes = {}, {}, [], []
        self.views, self.org_transitions, self.deliveries, self.plans = {}, {}, {}, {}
        self.pref_weights = {}
        self.delegations, self.legislators = {}, {}
        self.district_rows, self.district_profiles = [], {}
        self.documents, self.requirements = {}, {}
        self.ops = {"failed_enrichments": [], "failed_emails": [], "enrichment_pending": 0,
                    "job_runs": [], "recent_signups": [], "feedback_stats": [],
                    "delivery_stats": []}
        self.market_rows = []
        self.admin_user_ids = set()
        self.projects, self.capture_tasks = {}, {}
        self._id = 0

    def _next(self):
        self._id += 1
        return self._id

    def create_user_with_org(self, email, password_hash, org_name):
        uid, oid = self._next(), self._next()
        self.users[uid] = {"id": uid, "email": email, "password_hash": password_hash}
        self.orgs[oid] = {"id": oid, "name": org_name}
        self.members.append((oid, uid))
        return uid, oid

    def get_user_by_email(self, email):
        return next((u for u in self.users.values()
                     if u["email"] == email and not u.get("deleted_at")), None)

    def create_session(self, user_id, token_hash, expires_at):
        self.sessions[token_hash] = {"user_id": user_id, "expires_at": expires_at,
                                     "revoked_at": None}

    def user_org_for_session(self, token):
        s = self.sessions.get(hash_token(token))
        if not s or s["revoked_at"] or s["expires_at"] < datetime.now(timezone.utc):
            return None
        org_id = next((o for o, u in self.members if u == s["user_id"]), None)
        if org_id is None:
            return None
        return {"user_id": s["user_id"], "email": self.users[s["user_id"]]["email"],
                "org_id": org_id, "is_admin": s["user_id"] in self.admin_user_ids}

    def revoke_session(self, token):
        s = self.sessions.get(hash_token(token))
        if s:
            s["revoked_at"] = datetime.now(timezone.utc)

    def get_profile(self, org_id):
        return self.profiles.get(org_id)

    def upsert_profile(self, org_id, profile):
        self.profiles[org_id] = profile

    def list_projects(self, org_id):
        return [dict(p) for p in self.projects.values()
                if p["_org_id"] == org_id]

    def add_project(self, org_id, fields: dict):
        pid = self._next()
        row = {"id": pid, "_org_id": org_id}
        for k in ("title", "customer_agency", "customer_office",
                  "contract_identifier", "role", "naics", "psc", "period_start",
                  "period_end", "value_total", "scope", "technologies",
                  "outcomes", "partners", "source_note"):
            row[k] = fields.get(k) or None
        self.projects[pid] = row
        return pid

    def delete_project(self, org_id, project_id):
        p = self.projects.get(project_id)
        if p and p["_org_id"] == org_id:
            del self.projects[project_id]

    def list_capture_tasks(self, org_id, opportunity_id=None, include_done=False):
        out = []
        for t in self.capture_tasks.values():
            if t["_org_id"] != org_id:
                continue
            if opportunity_id is not None and t["opportunity_id"] != opportunity_id:
                continue
            if not include_done and t["status"] != "open":
                continue
            row = dict(t)
            row["opportunity_title"] = self.opportunities.get(
                t["opportunity_id"], {}).get("title")
            out.append(row)
        return out

    def add_capture_task(self, org_id, title, detail=None, opportunity_id=None,
                         user_id=None, owner=None, due_date=None,
                         source="manual"):
        tid = self._next()
        self.capture_tasks[tid] = {
            "id": tid, "_org_id": org_id, "opportunity_id": opportunity_id,
            "title": title, "detail": detail, "owner": owner,
            "due_date": due_date or None, "status": "open", "source": source}
        return tid

    def set_capture_task_status(self, org_id, task_id, status):
        if status not in ("open", "done", "dropped"):
            raise ValueError("invalid task status")
        t = self.capture_tasks.get(task_id)
        if t and t["_org_id"] == org_id:
            t["status"] = status

    def set_tracked(self, org_id, opportunity_id, status, user_id=None):
        if status not in TRACK_STATUSES:
            raise ValueError("invalid status")
        self.tracked[(org_id, opportunity_id)] = status

    def list_tracked(self, org_id):
        return [{"opportunity_id": oid, "status": st,
                 "title": self.opportunities.get(oid, {}).get("title", ""),
                 "agency": self.opportunities.get(oid, {}).get("agency", ""),
                 "response_deadline": None, "score": 0, "source_notice_id": None, "url": None}
                for (o, oid), st in self.tracked.items() if o == org_id]

    def record_feedback(self, org_id, opportunity_id, action, user_id=None,
                        user_email=None, notes=None):
        if org_id is None:
            raise ValueError("feedback requires an organization_id")
        self.feedback.append({"org_id": org_id, "opportunity_id": opportunity_id,
                              "action": action, "user_id": user_id, "notes": notes})
        from ..learning import FEEDBACK_DELTAS, clamp_weight, features_for
        delta = FEEDBACK_DELTAS.get(action)
        opp = self.opportunities.get(opportunity_id)
        if delta and opp:
            weights = self.pref_weights.setdefault(org_id, {})
            for feat in features_for(opp):
                weights[feat] = clamp_weight(weights.get(feat, 0) + delta)

    def preference_weights(self, org_id):
        return {f: w for f, w in self.pref_weights.get(org_id, {}).items() if w}

    def reset_preferences(self, org_id):
        self.pref_weights.pop(org_id, None)

    def get_subscription(self, org_id):
        return self.subs.get(org_id)

    def upsert_subscription(self, org_id, user_id, email, timezone_name, min_score,
                            active, delivery_hour=6, delivery_minute=30,
                            instant_alerts=False):
        self.subs[org_id] = {"email": email, "timezone": timezone_name,
                             "min_score": int(min_score), "active": bool(active),
                             "delivery_hour": int(delivery_hour),
                             "delivery_minute": int(delivery_minute),
                             "instant_alerts": bool(instant_alerts),
                             "user_id": user_id, "id": org_id * 1000}

    def list_opportunities(self, org_id, q=None, min_score=0, notice_type=None, limit=100):
        rows = []
        for o in self.opportunities.values():
            if o.get("score", 0) < min_score:
                continue
            if q and q.lower() not in (o.get("title", "") + o.get("agency", "")).lower():
                continue
            rows.append({**o, "user_status": self.tracked.get((org_id, o["id"])),
                         "recommendation": None, "incumbent": None})
        return rows[:limit]

    def get_opportunity(self, org_id, opp_id):
        o = self.opportunities.get(opp_id)
        if not o:
            return None
        return {**o, "user_status": self.tracked.get((org_id, opp_id)),
                "solicitation_number": o.get("solicitation_number"),
                "office_location": None, "posted_date": None, "place_of_performance": None,
                "description_text": o.get("description_text", ""), "url": None,
                "source_notice_id": o.get("source_notice_id"), "enrichment_status": "pending",
                "category": None, "reasons": [], "components": {},
                "recommended_action": None, "office": None, "notice_type": None,
                "naics": None, "set_aside": None, "response_deadline": None}

    def get_dossier(self, opp_id):
        return self.dossiers.get(opp_id)

    def mark_enrichment_pending(self, opp_id):
        pass

    def dashboard_counts(self, org_id, tz_name):
        return {"new_today": len(self.opportunities), "high_match_today": 0, "closing_7d": 0,
                "tracked_changes_24h": 0, "stage_transitions_7d": 0, "dossier_queue": 0}

    def recent_events(self, limit=25):
        return []

    def list_agencies(self, limit=100):
        return list(self.agencies.values())[:limit]

    def get_agency(self, office_id):
        return self.agencies.get(office_id)

    def list_vendors(self, q=None, limit=100):
        rows = [v for v in self.vendors.values()
                if not q or q.lower() in (v.get("name") or "").lower()]
        return rows[:limit]

    def get_vendor(self, vendor_id):
        return self.vendors.get(vendor_id)

    def get_lineage(self, solicitation_number, exclude_opp_id=None):
        return self.lineage.get(solicitation_number, [])

    def pipeline_report(self, org_id):
        grouped = {status: [] for status in TRACK_STATUSES}
        for r in self.list_tracked(org_id):
            grouped.setdefault(r["status"], []).append(r)
        return grouped

    def admin_ops(self):
        return self.ops

    def rate_limit_allow(self, rate_key, limit, window_seconds):
        import time as _t
        now = _t.time()
        bucket = self.rate.setdefault(rate_key, [])
        bucket.append(now)
        bucket[:] = [t for t in bucket if t > now - window_seconds]
        return len(bucket) <= limit

    def audit(self, event, org_id=None, user_id=None, ip=None, detail=None):
        self.audit_events.append({"event": event, "org_id": org_id,
                                  "user_id": user_id, "detail": detail or {}})

    def mark_email_verified(self, user_id):
        if user_id in self.users:
            self.users[user_id]["email_verified_at"] = True

    def set_password(self, user_id, password_hash):
        if user_id in self.users:
            self.users[user_id]["password_hash"] = password_hash

    def revoke_all_sessions(self, user_id):
        for sess in self.sessions.values():
            if sess["user_id"] == user_id:
                sess["revoked_at"] = True

    def deactivate_subscription(self, subscription_id):
        for _org_id, sub in self.subs.items():
            if sub.get("id") == subscription_id:
                sub["active"] = False

    def set_match_status(self, org_id, opportunity_id, status):
        self.matches[(org_id, opportunity_id)] = {
            **self.matches.get((org_id, opportunity_id), {}), "status": status}

    def hide_match(self, org_id, opportunity_id):
        self.matches[(org_id, opportunity_id)] = {
            **self.matches.get((org_id, opportunity_id), {}), "hidden": True}

    def request_match_refresh(self, org_id):
        self.match_refreshes.append(org_id)

    def market_intel(self, category_naics):
        return self.market_rows

    def delete_account(self, user_id):
        self.users[user_id]["deleted_at"] = True
        for sess in self.sessions.values():
            if sess["user_id"] == user_id:
                sess["revoked_at"] = True
        for sub in self.subs.values():
            if sub.get("user_id") == user_id:
                sub["active"] = False

    def save_view(self, org_id, user_id, name, criteria):
        for v in self.views.values():                      # upsert by (org, name)
            if v["org_id"] == org_id and v["name"] == name:
                v["criteria"] = criteria
                return v["id"]
        self._id += 1
        self.views[self._id] = {"id": self._id, "org_id": org_id, "name": name,
                                "criteria": criteria}
        return self._id

    def list_views(self, org_id):
        return [v for v in self.views.values() if v["org_id"] == org_id]

    def get_view(self, org_id, view_id):
        v = self.views.get(view_id)
        return v if v and v["org_id"] == org_id else None

    def delete_view(self, org_id, view_id):
        v = self.views.get(view_id)
        if v and v["org_id"] == org_id:
            del self.views[view_id]

    def closing_soon(self, org_id, days=7, limit=8):
        return []

    def stage_transitions_for_org(self, org_id, limit=8):
        return self.org_transitions.get(org_id, [])

    def latest_delivery(self, org_id):
        return self.deliveries.get(org_id)

    def org_plan(self, org_id):
        return self.plans.get(org_id, "early_access")

    def delegation_for_opportunity(self, opportunity_id):
        return self.delegations.get(opportunity_id, [])

    def get_legislator(self, bioguide_id):
        return self.legislators.get(bioguide_id)

    def district_rankings(self, fiscal_year, agency="", limit=50):
        rows = [r for r in self.district_rows
                if r["fiscal_year"] == fiscal_year and r["agency"] == (agency or "")]
        return sorted(rows, key=lambda r: -r["obligations"])[:limit]

    def district_agency_years(self):
        years = sorted({r["fiscal_year"] for r in self.district_rows}, reverse=True)
        agencies = sorted({r["agency"] for r in self.district_rows if r["agency"]})
        return years, agencies

    def documents_for_opportunity(self, opportunity_id):
        return self.documents.get(opportunity_id, [])

    def requirements_for_opportunity(self, opportunity_id):
        return self.requirements.get(opportunity_id, [])

    def district_profile(self, state, district):
        return self.district_profiles.get((state, district)) or {
            "state": state, "district": district, "rep": None, "spending": [],
            "election_results": [], "directed": [], "finance": []}
