"""Fetch solicitation attachments. THIS IS A SECURITY BOUNDARY.

Attachments are untrusted binaries from an external system, so every fetch is
constrained: SAM.gov hosts only (SSRF defense reusing the existing allowlist),
HTTPS only, hard byte cap streamed (never load an unbounded body), request
timeout, no redirects to other hosts, and the API key is never logged. Files
are stored as extracted TEXT plus a sha256 — Fedintel never executes, renders,
or re-serves the original binary.
"""
import hashlib
import os
import re
from urllib.parse import urlsplit

import requests

from ..log import log
from ..safety import ALLOWED_SAM_HOSTS

MAX_BYTES = 20 * 1024 * 1024          # 20 MB per document
TIMEOUT = 45
CHUNK = 64 * 1024

SUPPORTED_TYPES = ("application/pdf", "application/octet-stream", "text/plain")


def safe_document_url(url: str | None) -> str | None:
    """HTTPS SAM.gov URLs only — same allowlist as notice links."""
    candidate = (url or "").strip()
    if not candidate:
        return None
    try:
        parts = urlsplit(candidate)
    except ValueError:
        return None
    if (parts.scheme == "https" and parts.hostname
            and parts.hostname.lower() in ALLOWED_SAM_HOSTS
            and not parts.username and not parts.password):
        return candidate
    return None


def filename_from(headers: dict, url: str) -> str:
    """Never trust a server-supplied filename: strip paths and exotic chars."""
    disposition = headers.get("content-disposition") or ""
    match = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)"?', disposition)
    raw = match.group(1) if match else urlsplit(url).path.rsplit("/", 1)[-1]
    cleaned = re.sub(r"[^A-Za-z0-9._-]", "_", (raw or "attachment").strip())[:120]
    return cleaned or "attachment"


def fetch_document(url: str) -> dict:
    """Returns {status, content, filename, content_type, byte_size, sha256}.
    status: fetched | failed | too_large | unsupported | skipped."""
    safe_url = safe_document_url(url)
    if not safe_url:
        return {"status": "skipped", "error": "url not on the SAM.gov allowlist"}
    params = {}
    api_key = os.getenv("SAM_API_KEY", "")
    if api_key and "api_key=" not in safe_url:
        params["api_key"] = api_key          # never logged; requests handles it
    try:
        with requests.get(safe_url, params=params, timeout=TIMEOUT,
                          stream=True, allow_redirects=False) as resp:
            if resp.status_code >= 300:
                log("document_fetch_failed", status=resp.status_code)
                return {"status": "failed", "error": f"http {resp.status_code}"}
            content_type = (resp.headers.get("content-type") or "").split(";")[0].strip()
            declared = resp.headers.get("content-length")
            if declared and int(declared) > MAX_BYTES:
                return {"status": "too_large", "error": f"{declared} bytes",
                        "content_type": content_type}
            body = bytearray()
            for chunk in resp.iter_content(CHUNK):
                body.extend(chunk)
                if len(body) > MAX_BYTES:    # cap even when length is unstated
                    return {"status": "too_large", "error": f">{MAX_BYTES} bytes",
                            "content_type": content_type}
            content = bytes(body)
            filename = filename_from(resp.headers, safe_url)
    except requests.RequestException as exc:
        log("document_fetch_error", error=type(exc).__name__)
        return {"status": "failed", "error": type(exc).__name__}
    if content_type and content_type not in SUPPORTED_TYPES and \
            not filename.lower().endswith((".pdf", ".txt")):
        return {"status": "unsupported", "error": content_type,
                "filename": filename, "content_type": content_type}
    return {"status": "fetched", "content": content, "filename": filename,
            "content_type": content_type, "byte_size": len(content),
            "sha256": hashlib.sha256(content).hexdigest()}


def resource_links(raw_json: dict) -> list[str]:
    """Attachment URLs from a stored SAM notice record."""
    links = (raw_json or {}).get("resourceLinks")
    out = []
    if isinstance(links, list):
        for link in links:
            if isinstance(link, str) and safe_document_url(link):
                out.append(link)
    return out
