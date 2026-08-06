"""General-purpose signed tokens (HMAC-SHA256, expiring, purpose-bound).

Used for: digest action links, unsubscribe links, email verification,
password resets. A token binds purpose + up to three subject IDs + expiry, so
a token minted for one purpose/subject can never be replayed for another.
"""
import hashlib
import hmac
import os
import time

from .config import ACTION_SECRET

DEFAULT_TTLS = {
    "action": 14 * 24 * 3600,
    "unsub": 90 * 24 * 3600,
    "verify_email": 3 * 24 * 3600,
    "reset_password": 2 * 3600,
}


def _secret() -> str:
    # Live env read (not frozen at import): APP_SECRET wins, ACTION_SECRET is
    # the fallback so one secret can serve both digests and account tokens.
    return (os.getenv("APP_SECRET", "") or os.getenv("ACTION_SECRET", "")
            or ACTION_SECRET)


def enabled() -> bool:
    return bool(_secret())


def _mac(purpose: str, a: int, b: int, c: int, exp: int) -> str:
    msg = f"{purpose}:{a}:{b}:{c}:{exp}".encode()
    return hmac.new(_secret().encode(), msg, hashlib.sha256).hexdigest()[:32]


def sign(purpose: str, a: int = 0, b: int = 0, c: int = 0,
         exp: int | None = None) -> tuple[str, int]:
    exp = exp or int(time.time()) + DEFAULT_TTLS.get(purpose, 24 * 3600)
    return _mac(purpose, a, b, c, exp), exp


def verify(purpose: str, token: str, a: int = 0, b: int = 0, c: int = 0,
           exp: int = 0, now: int | None = None) -> bool:
    if not enabled():
        return False
    try:
        a, b, c, exp = int(a), int(b), int(c), int(exp)
    except (TypeError, ValueError):
        return False
    if (now or int(time.time())) > exp:
        return False
    return hmac.compare_digest(_mac(purpose, a, b, c, exp), token or "")
