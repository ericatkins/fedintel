"""Auth primitives: password hashing and DB-backed session tokens.

- Passwords: scrypt (stdlib), per-user random salt, constant-time compare.
- Sessions: 256-bit random token in an HttpOnly cookie; the DATABASE stores
  only sha256(token), so a DB leak cannot mint sessions. Expiry enforced
  server-side; logout revokes.
Pure functions here; persistence lives in store.py.
"""
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

_SCRYPT_N, _SCRYPT_R, _SCRYPT_P = 2**14, 8, 1
SESSION_TTL = timedelta(days=14)
MIN_PASSWORD_LEN = 10


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt,
                            n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P)
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt_hex, digest_hex = stored.split("$")
        if scheme != "scrypt":
            return False
        digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt_hex),
                                n=int(n), r=int(r), p=int(p))
        return hmac.compare_digest(digest.hex(), digest_hex)
    except (ValueError, AttributeError):
        return False


def new_session_token() -> tuple[str, str, datetime]:
    """Returns (cookie_token, token_hash_for_db, expires_at)."""
    token = secrets.token_urlsafe(32)
    return token, hash_token(token), datetime.now(timezone.utc) + SESSION_TTL


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def password_policy_error(password: str) -> str | None:
    if len(password or "") < MIN_PASSWORD_LEN:
        return f"Password must be at least {MIN_PASSWORD_LEN} characters."
    return None
