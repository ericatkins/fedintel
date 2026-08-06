"""URL and content safety helpers. All SAM.gov data is untrusted input."""
from urllib.parse import urlsplit

ALLOWED_SAM_HOSTS = {"sam.gov", "www.sam.gov", "beta.sam.gov"}


def safe_sam_url(url: str | None, notice_id: str | None = None) -> str | None:
    """Return a safe HTTPS SAM.gov URL, a fallback built from notice_id,
    or None (render title without a link).

    Rejects: non-HTTPS schemes (javascript:, data:, http:), protocol-relative
    URLs, non-SAM hosts, malformed URLs, empty values, and embedded credentials.
    """
    candidate = (url or "").strip()
    if candidate:
        try:
            parts = urlsplit(candidate)
        except ValueError:
            parts = None
        if (
            parts is not None
            and parts.scheme == "https"
            and parts.hostname
            and parts.hostname.lower() in ALLOWED_SAM_HOSTS
            and not parts.username
            and not parts.password
        ):
            return candidate

    nid = (notice_id or "").strip()
    # notice IDs are alphanumeric; refuse anything that could alter the URL
    if nid and nid.replace("-", "").isalnum():
        return f"https://sam.gov/opp/{nid}/view"
    return None
