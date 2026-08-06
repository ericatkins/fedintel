"""Job-run observability: every cron entrypoint records a job_runs row."""
import contextlib

from .log import log


@contextlib.contextmanager
def record_job(conn, job_name: str):
    """Context manager: yields a mutable stats dict; writes job_runs on exit."""
    stats = {"fetched": 0, "inserted": 0, "amended": 0, "failed": 0, "api_calls": 0}
    job_id = None
    try:
        with conn.cursor() as cur:
            cur.execute("insert into job_runs (job_name) values (%s) returning id",
                        (job_name,))
            job_id = cur.fetchone()[0]
        conn.commit()
    except Exception:  # noqa: BLE001 — observability must never break the job
        conn.rollback()
    try:
        yield stats
        _finish(conn, job_id, "ok", stats, None)
        log("job_finished", job=job_name, **stats)
    except Exception as exc:
        _finish(conn, job_id, "failed", stats, f"{type(exc).__name__}: {exc}"[:500])
        raise


def _finish(conn, job_id, status, stats, error):
    if job_id is None:
        return
    try:
        with conn.cursor() as cur:
            cur.execute(
                """update job_runs set finished_at=now(), status=%s,
                     records_fetched=%s, records_inserted=%s, records_amended=%s,
                     records_failed=%s, api_calls=%s, error_summary=%s
                   where id=%s""",
                (status, stats["fetched"], stats["inserted"], stats["amended"],
                 stats["failed"], stats["api_calls"], error, job_id))
        conn.commit()
    except Exception:  # noqa: BLE001
        conn.rollback()
