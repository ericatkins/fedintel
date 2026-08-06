"""Fedintel daily pipeline.

Run:  python -m src.main
Cron: Railway cron (railway.json), 11:30 UTC = 6:30 AM Central (CDT).

Flow: SAM.gov adapter -> normalize+validate -> upsert (dedup + change events)
      -> deterministic classify/score (profile-aware) -> briefing email.

Reliability rules:
- One malformed record never kills the run (skip + sanitized warning).
- Commits happen in batches so a late failure loses at most one batch.
- A digest is only marked sent when the provider confirms; failures are
  stored with error state and retried on the next run.
"""
import os
from datetime import datetime
from zoneinfo import ZoneInfo

from . import db
from .adapters import sam_gov
from .classify import classify
from .config import INGEST_BATCH_SIZE, MIN_DIGEST_SCORE, TZ
from .digest import render
from .log import log
from .normalize import InvalidRecord, normalize_sam
from .profile import load_profile
from .send_email import send


def ingest(conn, profile: dict) -> dict:
    stats = {"new": 0, "amended": 0, "unchanged": 0, "skipped": 0, "errors": 0, "batches": 0}
    batch = 0
    cur = conn.cursor()
    try:
        for raw in sam_gov.fetch_all():
            try:
                opp = normalize_sam(raw)
            except InvalidRecord as exc:
                stats["skipped"] += 1
                log("record_skipped", reason=str(exc))
                continue
            try:
                opp_id, status, _events = db.upsert_opportunity(cur, opp)
                stats[status] += 1
                if status in ("new", "amended"):
                    db.save_classification(cur, opp_id, classify(opp, profile))
                batch += 1
                if batch >= INGEST_BATCH_SIZE:
                    conn.commit()
                    stats["batches"] += 1
                    batch = 0
            except Exception as exc:  # noqa: BLE001 — one bad record must not kill the run
                conn.rollback()
                batch = 0
                stats["errors"] += 1
                log("record_error", error=f"{type(exc).__name__}: {exc}")
        conn.commit()
        if batch:
            stats["batches"] += 1
    finally:
        cur.close()
    log("ingest_complete", **stats)
    return stats


def load_subscriptions(cur) -> list[dict]:
    cur.execute(
        """select s.id, s.organization_id, s.user_id, s.email, s.timezone,
                  s.min_score, s.delivery_hour_local, s.delivery_minute_local
           from digest_subscriptions s
           where s.active and s.daily_digest""")
    cols = ("id", "org_id", "user_id", "email", "timezone", "min_score",
            "delivery_hour", "delivery_minute")
    return [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]


def _delivery_due(sub: dict, now_local) -> bool:
    """True once the subscriber's local clock reaches their delivery time.
    The hourly worker + the unique (subscription, day) delivery row together
    give exactly one send per day, in the subscriber's own morning."""
    hour = sub.get("delivery_hour") if sub.get("delivery_hour") is not None else 6
    minute = sub.get("delivery_minute") or 0
    return (now_local.hour, now_local.minute) >= (hour, minute)


def send_subscription_digests(conn) -> int:
    """Per-subscription digest delivery: each active subscription gets a digest
    scored with ITS organization's profile matches, sent to ITS email, with
    signed unsubscribe/manage links, recorded per subscription (unique per
    subscription per day; failures retried on the next run)."""
    from .digest import footer_links
    sent = 0
    with conn.cursor() as cur:
        subs = load_subscriptions(cur)
    for sub in subs:
        try:
            tz = ZoneInfo(sub.get("timezone") or "America/Chicago")
        except (KeyError, ValueError):
            tz = TZ
        now_local = datetime.now(tz)
        today = now_local.date()
        if not _delivery_due(sub, now_local):
            continue                       # their morning hasn't arrived yet
        with conn.cursor() as cur:
            cur.execute(
                """select 1 from digest_deliveries
                   where subscription_id=%s and digest_date=%s and send_status='sent'""",
                (sub["id"], today))
            if cur.fetchone():
                continue
            rows = db.fetch_digest_rows_for_org(
                cur, sub["org_id"], str(tz), today,
                int(sub.get("min_score") or MIN_DIGEST_SCORE))
            _attach_intel(rows)
            _attach_actions(rows, sub)
            html = render(rows, today, links=footer_links(sub["id"]))
            cur.execute(
                """insert into digest_deliveries
                     (subscription_id, organization_id, user_id, digest_date,
                      opportunity_count, html_body, send_status)
                   values (%s,%s,%s,%s,%s,%s,'generated')
                   on conflict (subscription_id, digest_date) do update
                     set html_body=excluded.html_body,
                         opportunity_count=excluded.opportunity_count,
                         generated_at=now()
                   returning id""",
                (sub["id"], sub["org_id"], sub["user_id"], today, len(rows), html))
            delivery_id = cur.fetchone()[0]
            conn.commit()
            subject = (f"Fedintel briefing — {len(rows)} matches — "
                       f"{today.strftime('%b %d, %Y')}")
            ok, message_id, error = send(
                subject, html, to_override=[sub["email"]],
                idempotency_key=f"fedintel-digest:{sub['id']}:{today.isoformat()}")
            cur.execute(
                """update digest_deliveries set send_attempted_at=now(),
                     sent_at=case when %s then now() end,
                     send_status=case when %s then 'sent' else 'failed' end,
                     send_error=%s, provider_message_id=%s
                   where id=%s""",
                (ok, ok, error, message_id, delivery_id))
            conn.commit()
            sent += 1 if ok else 0
            log("subscription_digest", subscription_id=sub["id"], org_id=sub["org_id"],
                rows=len(rows), sent=ok)
    return sent


def _attach_actions(rows, sub):
    """Action links in per-subscription digests bind org + subscription in the
    signed token, so a forwarded email can never act on another tenant."""
    from . import actions
    for o in rows:
        links = []
        if actions.enabled():
            for action, label in (("track", "Track"), ("ignore", "Ignore"),
                                  ("good_match", "Good match"),
                                  ("bad_match", "Bad match")):
                href = actions.url(o["id"], action, sub=sub["id"], org=sub["org_id"])
                if href:
                    links.append({"href": href, "label": label})
        o["action_links"] = links


def send_digest(conn):
    now_local = datetime.now(TZ)
    today = now_local.date()
    with conn.cursor() as cur:
        if db.digest_already_sent(cur, today):
            log("digest_skipped", reason="already sent", date=str(today))
            return
        rows = db.fetch_digest_rows(cur, today, MIN_DIGEST_SCORE, TZ)
        try:
            tracked = db.fetch_tracked_amendments(cur, today, TZ)
        except Exception as exc:  # noqa: BLE001 — tracked section is optional
            conn.rollback()
            tracked = []
            log("tracked_fetch_error", error=type(exc).__name__)
            rows = db.fetch_digest_rows(cur, today, MIN_DIGEST_SCORE, TZ)
        _attach_intel(rows)
        _attach_intel(tracked)
        html = render(rows, today, tracked_amendments=tracked)
        top = rows[0]["score"] if rows else None
        digest_id = db.record_digest_generated(cur, today, len(rows), top, html)
        conn.commit()

        subject = f"Fedintel briefing — {len(rows)} matches — {today.strftime('%b %d, %Y')}"
        ok, message_id, error = send(subject, html)
        db.record_send_result(cur, digest_id, ok, message_id, error)
        conn.commit()
        log("digest_complete", date=str(today), rows=len(rows),
            tracked=len(tracked), sent=ok)


def _attach_intel(rows):
    """Compact dossier intel line + top risk per card (stored dossiers only —
    the digest never waits on external APIs)."""
    from .intel.dossier import intel_line
    for o in rows:
        similar = o.get("similar_work") or []
        inc = o.get("incumbent_analysis") or {}
        rec = o.get("recommendation") or {}
        if similar or inc:
            o["intel_line"] = intel_line({
                "similar_work": similar, "incumbent_analysis": inc,
                "similar_award_range": None,
            })
        risks = rec.get("top_risks") or []
        if risks:
            o["top_risk"] = risks[0]


def run():
    profile = load_profile()
    conn = db.get_conn()
    conn.autocommit = False
    try:
        from .jobs import record_job
        with record_job(conn, "daily_pipeline"):
            ingest(conn, profile)
            try:
                from .matching import refresh_profile_matches_for_recent_opportunities
                refresh_profile_matches_for_recent_opportunities(conn)
            except Exception as exc:  # noqa: BLE001 — matching must not block digests
                conn.rollback()
                log("match_refresh_error", error=type(exc).__name__)
            with conn.cursor() as cur:
                has_subs = bool(load_subscriptions(cur))
            if has_subs:
                # Delivery belongs to the HOURLY worker (src.run_digests) so
                # each subscriber gets their own local morning. Running it here
                # too is harmless (idempotent) and covers due subscriptions
                # whose time has already passed.
                send_subscription_digests(conn)
                try:
                    from .alerts import send_instant_alerts
                    send_instant_alerts(conn, base_url=os.getenv("ACTION_BASE_URL", ""))
                except Exception as exc:  # noqa: BLE001 — alerts never block digests
                    conn.rollback()
                    log("instant_alerts_error", error=type(exc).__name__)
            else:
                # Dogfood mode: single global digest to DIGEST_TO
                send_digest(conn)
    finally:
        conn.close()


if __name__ == "__main__":
    run()
