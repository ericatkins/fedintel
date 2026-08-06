"""SAM.gov adapter.

Pulls from the Get Opportunities API v2 and yields raw notice dicts.
Adapter contract: fetch() -> iterable of raw dicts for normalize.normalize_sam().

API docs: https://open.gsa.gov/api/get-opportunities-public-api/
Notes:
- Requires api_key (SAM.gov > Account Details); the key rides in the query
  string, so NOTHING in this module may log a request URL or a raw
  requests exception (HTTPError messages embed the full URL).
- Dates MM/dd/yyyy, max range 1 year, limit max 1000, paginate with offset.
- Personal keys are rate limited; keep LOOKBACK_DAYS small, pull once daily.
"""
import time
from datetime import date, datetime, timedelta

import requests

from ..config import LOOKBACK_DAYS, SAM_API_KEY, TZ
from ..log import log

BASE_URL = "https://api.sam.gov/opportunities/v2/search"
PAGE_SIZE = 1000


class SamApiError(RuntimeError):
    """Sanitized SAM.gov API failure (never contains the request URL/key)."""


def _fmt(d: date) -> str:
    return d.strftime("%m/%d/%Y")


def _get(params: dict) -> requests.Response:
    try:
        return requests.get(BASE_URL, params=params, timeout=60)
    except requests.RequestException as exc:
        raise SamApiError(f"network error: {type(exc).__name__}") from None


def fetch(naics: str | None = None, ptype: str | None = None):
    """Yield raw opportunity dicts posted within the lookback window."""
    posted_to: date = datetime.now(TZ).date()
    posted_from = posted_to - timedelta(days=LOOKBACK_DAYS)
    offset = 0
    while True:
        params = {
            "api_key": SAM_API_KEY,
            "postedFrom": _fmt(posted_from),
            "postedTo": _fmt(posted_to),
            "limit": PAGE_SIZE,
            "offset": offset,
        }
        if naics:
            params["ncode"] = naics
        if ptype:
            params["ptype"] = ptype

        resp = _get(params)
        if resp.status_code == 429:
            log("sam_rate_limited", naics=naics, action="backoff 30s")
            time.sleep(30)
            resp = _get(params)
            if resp.status_code == 429:
                log("sam_rate_limited", naics=naics, action="skipping remainder")
                return
        if resp.status_code >= 400:
            # Never re-raise requests' HTTPError: its message embeds the URL+key.
            raise SamApiError(f"SAM.gov API status {resp.status_code}")

        try:
            data = resp.json()
        except ValueError:
            raise SamApiError("SAM.gov returned non-JSON response") from None
        records = data.get("opportunitiesData", []) or []
        yield from records
        total = int(data.get("totalRecords", 0) or 0)
        offset += PAGE_SIZE
        if offset >= total or not records:
            return


def fetch_all():
    """Pull one broad query per target NAICS. Dedup happens downstream.

    A failing NAICS query is logged and skipped; the run continues so one
    bad query never costs you the whole morning digest.
    """
    from ..config import NAICS_TARGETS

    seen = set()
    for naics in NAICS_TARGETS:
        try:
            for rec in fetch(naics=naics):
                nid = rec.get("noticeId") if isinstance(rec, dict) else None
                if nid and nid not in seen:
                    seen.add(nid)
                    yield rec
        except SamApiError as exc:
            log("sam_query_failed", naics=naics, error=str(exc))
            continue
