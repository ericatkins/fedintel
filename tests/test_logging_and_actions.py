import os

from src.actions import sign, verify
from src.log import sanitize


def test_sanitize_strips_query_strings():
    msg = "error at https://api.sam.gov/opportunities/v2/search?api_key=SECRET123&limit=10"
    out = sanitize(msg)
    assert "SECRET123" not in out
    assert "[params-redacted]" in out


def test_sanitize_strips_known_secret_values():
    os.environ["SAM_API_KEY"] = "super-secret-key-xyz"
    out = sanitize("failure: super-secret-key-xyz rejected")
    assert "super-secret-key-xyz" not in out


def test_action_tokens_v2(monkeypatch):
    monkeypatch.setattr("src.actions.ACTION_BASE_URL", "https://app.fedintel.example")
    monkeypatch.setattr("src.actions.ACTION_SECRET", "s3cr3t")
    token, exp = sign(42, "track", sub=7, org=3)
    assert verify(42, "track", token, sub=7, org=3, exp=exp)
    assert not verify(42, "ignore", token, sub=7, org=3, exp=exp)   # action bound
    assert not verify(43, "track", token, sub=7, org=3, exp=exp)    # opp bound
    assert not verify(42, "track", token, sub=8, org=3, exp=exp)    # sub bound
    assert not verify(42, "track", token, sub=7, org=4, exp=exp)    # org bound
    assert not verify(42, "track", token, sub=7, org=3, exp=exp + 1)
    assert not verify(42, "track", token, sub=7, org=3, exp=exp, now=exp + 10)
    assert not verify(42, "track", token, sub=7, org=3, exp="junk")
    assert not verify(42, "unknown_action", token, sub=7, org=3, exp=exp)


def test_action_url_contains_expiry(monkeypatch):
    monkeypatch.setattr("src.actions.ACTION_BASE_URL", "https://app.fedintel.example")
    monkeypatch.setattr("src.actions.ACTION_SECRET", "s3cr3t")
    from src.actions import url
    u = url(42, "track", sub=7, org=3)
    assert u.startswith("https://app.fedintel.example/a/42/track?t=")
    assert "&e=" in u and "&s=7" in u and "&o=3" in u
    assert url(42, "not_an_action") is None


def test_redaction_ignores_short_placeholder_secrets(monkeypatch):
    """A dev-shell placeholder like SAM_API_KEY=x must not blind-replace
    substrings of ordinary words (found live: 'extracted' -> 'e[...]tracted')."""
    monkeypatch.setenv("SAM_API_KEY", "x")
    assert sanitize("document status extracted") == "document status extracted"
    monkeypatch.setenv("SAM_API_KEY", "REALKEY_abcdef123456789")
    out = sanitize("request failed key=REALKEY_abcdef123456789 done")
    assert "REALKEY" not in out and "[SAM_API_KEY-redacted]" in out
