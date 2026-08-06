"""Send digest via Resend. Returns (ok, provider_message_id, error).

Never logs API keys, auth headers, or full provider response bodies —
only status codes and a sanitized short error string.
"""
import requests

from .config import DIGEST_FROM, DIGEST_TO, RESEND_API_KEY
from .log import log


def _headers(idempotency_key: str | None) -> dict:
    """Idempotency-Key makes provider retries safe: a worker timeout after
    Resend accepted the email cannot produce a duplicate send on rerun."""
    headers = {"Authorization": f"Bearer {RESEND_API_KEY}"}
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key
    return headers


def send(subject: str, html: str, to_override: list[str] | None = None,
         idempotency_key: str | None = None) -> tuple[bool, str | None, str | None]:
    if not RESEND_API_KEY or not (to_override or DIGEST_TO):
        log("email_skipped", reason="RESEND_API_KEY or DIGEST_TO not configured")
        return False, None, "email not configured"
    try:
        resp = requests.post(
            "https://api.resend.com/emails",
            headers=_headers(idempotency_key),
            json={"from": DIGEST_FROM, "to": to_override or DIGEST_TO,
                  "subject": subject, "html": html},
            timeout=30,
        )
    except requests.RequestException as exc:
        log("email_error", error=type(exc).__name__)
        return False, None, f"request error: {type(exc).__name__}"
    if resp.status_code >= 300:
        log("email_failed", status=resp.status_code)
        return False, None, f"provider status {resp.status_code}"
    try:
        message_id = resp.json().get("id")
    except ValueError:
        message_id = None
    log("email_sent", status=resp.status_code)
    return True, message_id, None


def send_plain(to_email: str, subject: str, body: str,
               idempotency_key: str | None = None) -> str:
    """Plain-text transactional email (verification, password reset).
    Raises on failure; callers decide whether that is fatal."""
    if not RESEND_API_KEY:
        raise RuntimeError("RESEND_API_KEY not configured")
    resp = requests.post(
        "https://api.resend.com/emails",
        headers=_headers(idempotency_key),
        json={"from": DIGEST_FROM, "to": [to_email], "subject": subject, "text": body},
        timeout=30,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"resend status {resp.status_code}")
    return (resp.json() or {}).get("id", "")
