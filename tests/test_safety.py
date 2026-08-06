import pytest

from src.safety import safe_sam_url


@pytest.mark.parametrize("url", [
    "https://sam.gov/opp/abc/view",
    "https://www.sam.gov/opp/abc/view",
    "https://beta.sam.gov/opp/abc/view",
])
def test_safe_urls_pass_through(url):
    assert safe_sam_url(url) == url


@pytest.mark.parametrize("url", [
    "javascript:alert(1)",
    "data:text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg==",
    "http://sam.gov/opp/abc/view",              # not HTTPS
    "//sam.gov/opp/abc/view",                    # protocol-relative
    "https://evil.com/opp/abc/view",             # wrong host
    "https://sam.gov.evil.com/x",                # suffix spoof
    "https://user:pass@sam.gov/x",               # embedded credentials
    "https://[malformed",                        # malformed
    "",
    None,
])
def test_unsafe_urls_fall_back_to_notice_id(url):
    assert safe_sam_url(url, "abc123") == "https://sam.gov/opp/abc123/view"


def test_unsafe_url_and_unsafe_notice_id_yields_none():
    assert safe_sam_url("javascript:alert(1)", "abc/../../evil?x=1") is None
    assert safe_sam_url(None, None) is None


def test_hyphenated_notice_id_ok():
    assert safe_sam_url(None, "abc-123-def") == "https://sam.gov/opp/abc-123-def/view"
