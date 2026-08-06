"""Instant alerts: 'an opportunity you saw early just became real.'

Deterministic and idempotent: stage_transition change_events from the last
lookback window, joined to each organization's TRACKED opportunities, delivered
once per (subscription, event) to subscriptions that opted into instant alerts.
Plain-text email; works with AI disabled; never blocks the digest pipeline.
"""
from .log import log
from .send_email import send_plain

LOOKBACK_HOURS = 26   # daily cron + slack; uniqueness makes reruns safe

_PENDING_ALERTS_SQL = """
    select s.id, s.organization_id, s.email, e.id, o.id, o.title,
           e.detail->>'from', e.detail->>'to', e.detail->>'solicitation_number'
    from digest_subscriptions s
    join tracked_opportunities t on t.organization_id = s.organization_id
    join change_events e on e.opportunity_id = t.opportunity_id
    join opportunities o on o.id = e.opportunity_id
    join organizations org on org.id = s.organization_id
    where s.active and s.instant_alerts
      and e.event_type = 'stage_transition'
      and e.created_at > now() - make_interval(hours => %s)
      and t.status not in ('ignored', 'lost')
      and not exists (select 1 from instant_alert_deliveries d
                      where d.subscription_id = s.id and d.change_event_id = e.id)
    order by s.id, e.created_at"""

_COLS = ("subscription_id", "org_id", "email", "event_id", "opportunity_id",
         "title", "stage_from", "stage_to", "solicitation_number")


def send_instant_alerts(conn, base_url: str = "") -> int:
    """Returns the number of alert emails sent. Safe to rerun."""
    from .web.entitlements import allows
    with conn.cursor() as cur:
        cur.execute(_PENDING_ALERTS_SQL, (LOOKBACK_HOURS,))
        rows = [dict(zip(_COLS, r, strict=True)) for r in cur.fetchall()]
        plans = _org_plans(cur, {r["org_id"] for r in rows})
    by_sub: dict[int, list[dict]] = {}
    for r in rows:
        if allows(plans.get(r["org_id"], "early_access"), "instant_alerts"):
            by_sub.setdefault(r["subscription_id"], []).append(r)
    sent = 0
    for sub_id, events in by_sub.items():
        body = _render_body(events, base_url)
        subject = (f"Fedintel alert — {events[0]['title'][:60]} advanced to "
                   f"{events[0]['stage_to']}" if len(events) == 1 else
                   f"Fedintel alert — {len(events)} tracked opportunities advanced")
        ok, error = True, None
        try:
            key = "fedintel-alert:{}:{}".format(
                sub_id, "-".join(str(e["event_id"]) for e in events))
            send_plain(events[0]["email"], subject, body, idempotency_key=key)
        except Exception as exc:  # noqa: BLE001 — record failure, keep going
            ok, error = False, f"{type(exc).__name__}: {exc}"[:300]
        with conn.cursor() as cur:
            for e in events:
                cur.execute(
                    """insert into instant_alert_deliveries
                         (subscription_id, organization_id, change_event_id,
                          sent_at, send_status, send_error)
                       values (%s,%s,%s, case when %s then now() end,
                               case when %s then 'sent' else 'failed' end, %s)
                       on conflict (subscription_id, change_event_id) do nothing""",
                    (sub_id, e["org_id"], e["event_id"], ok, ok, error))
        conn.commit()
        sent += 1 if ok else 0
        log("instant_alert", subscription_id=sub_id, events=len(events), sent=ok)
    return sent


def _org_plans(cur, org_ids) -> dict[int, str]:
    if not org_ids:
        return {}
    cur.execute("select id, plan from organizations where id = any(%s)",
                (list(org_ids),))
    return dict(cur.fetchall())


def _render_body(events: list[dict], base_url: str) -> str:
    lines = ["A tracked opportunity just moved to a later stage:", ""]
    for e in events:
        lines.append(f"• {e['title']}")
        lines.append(f"  {e['stage_from']} → {e['stage_to']}"
                     + (f"  (sol. {e['solicitation_number']})"
                        if e["solicitation_number"] else ""))
        if base_url:
            lines.append(f"  {base_url.rstrip('/')}/app/opportunities/{e['opportunity_id']}")
        lines.append("")
    lines.append("Stage advances are the highest-signal moment to engage the "
                  "buying office — before the RFP drops, not after.")
    lines.append("Manage alerts: " + (f"{base_url.rstrip('/')}/app/alerts"
                                      if base_url else "Alerts page"))
    return "\n".join(lines)
