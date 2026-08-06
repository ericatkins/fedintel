"""Hourly worker: deliver due daily digests + instant alerts.

Run every hour. Each subscription sends once per local day, at/after its own
delivery_hour_local — this is what makes '6:30 AM in your timezone' TRUE.
Idempotent end to end: unique delivery rows + Resend idempotency keys.
"""
import os

from . import db
from .jobs import record_job
from .log import log
from .main import send_subscription_digests


def run():
    conn = db.get_conn()
    conn.autocommit = False
    try:
        with record_job(conn, "hourly_digests"):
            sent = send_subscription_digests(conn)
            try:
                from .alerts import send_instant_alerts
                alerts = send_instant_alerts(conn,
                                             base_url=os.getenv("ACTION_BASE_URL", ""))
            except Exception as exc:  # noqa: BLE001 — alerts never block digests
                conn.rollback()
                alerts = 0
                log("instant_alerts_error", error=type(exc).__name__)
            log("hourly_digests_done", digests=sent, alerts=alerts)
    finally:
        conn.close()


if __name__ == "__main__":
    run()
