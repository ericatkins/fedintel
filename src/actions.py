"""Signed action links (v2) for digest buttons and web actions.

Token binds: opportunity ID + action + optional subscription/user ID +
expiration. HMAC-SHA256, constant-time comparison, expired/unknown rejected.

If ACTION_BASE_URL / ACTION_SECRET are unset, actions are disabled and the
digest renders View-only. Cron never depends on the web service.
"""
import hashlib
import hmac
import time

from .config import ACTION_BASE_URL, ACTION_SECRET

ACTIONS = ("track", "save", "ignore", "pursuing", "good_match", "bad_match", "hide_similar")
DEFAULT_TTL_SECONDS = 14 * 24 * 3600  # digest links stay valid for two weeks


def enabled() -> bool:
    return bool(ACTION_BASE_URL and ACTION_SECRET)


def _mac(opportunity_id: int, action: str, sub: int, org: int, exp: int) -> str:
    msg = f"{opportunity_id}:{action}:{sub}:{org}:{exp}".encode()
    return hmac.new(ACTION_SECRET.encode(), msg, hashlib.sha256).hexdigest()[:32]


def sign(opportunity_id: int, action: str, sub: int = 0, org: int = 0,
         exp: int | None = None) -> tuple[str, int]:
    exp = exp or int(time.time()) + DEFAULT_TTL_SECONDS
    return _mac(opportunity_id, action, sub, org, exp), exp


def verify(opportunity_id: int, action: str, token: str, sub: int, org: int,
           exp: int, now: int | None = None) -> bool:
    """Constant-time verify; rejects unknown actions and expired tokens.
    Token binds opportunity + action + subscription + organization + expiry."""
    if not enabled() or action not in ACTIONS:
        return False
    try:
        exp = int(exp)
        sub = int(sub)
        org = int(org)
    except (TypeError, ValueError):
        return False
    if (now or int(time.time())) > exp:
        return False
    return hmac.compare_digest(_mac(opportunity_id, action, sub, org, exp), token or "")


def url(opportunity_id: int, action: str, sub: int = 0, org: int = 0) -> str | None:
    if not enabled() or action not in ACTIONS:
        return None
    token, exp = sign(opportunity_id, action, sub, org)
    base = ACTION_BASE_URL.rstrip("/")
    return f"{base}/a/{opportunity_id}/{action}?t={token}&e={exp}&s={sub}&o={org}"
