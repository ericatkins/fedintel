"""Auth primitives: password hashing, session tokens."""
from datetime import datetime, timedelta, timezone

from src.web.auth import hash_password, hash_token, new_session_token, password_policy_error, verify_password


def test_password_roundtrip_and_uniqueness():
    h1, h2 = hash_password("correct horse battery"), hash_password("correct horse battery")
    assert h1 != h2  # unique salts
    assert verify_password("correct horse battery", h1)
    assert not verify_password("wrong", h1)


def test_password_verify_rejects_garbage_hashes():
    assert not verify_password("x", "not-a-hash")
    assert not verify_password("x", "")
    assert not verify_password("x", "md5$deadbeef")


def test_password_policy():
    assert password_policy_error("short") is not None
    assert password_policy_error("long enough password") is None


def test_session_tokens_hashed_at_rest():
    token, token_hash, expires = new_session_token()
    assert token not in token_hash          # DB never stores the raw token
    assert hash_token(token) == token_hash
    assert expires > datetime.now(timezone.utc) + timedelta(days=13)
