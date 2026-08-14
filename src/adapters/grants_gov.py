"""Grants.gov adapter: opportunity search + detail, normalized for the
grants vertical.

Grants.gov exposes a public JSON API (no key): `search2` for paged search
hits and `fetchOpportunity` for the full synopsis (award floor/ceiling,
expected awards, applicant types, cost sharing). This adapter implements
both. NOTE: live validation is pending in restricted network environments
(the API host is blocked where this was built) — normalization is verified
against fixtures mirroring the documented response shapes; verify field
names on the first production run (see docs/DATA_SOURCES.md).

Grants are a SEPARATE vertical: these records never enter contract scoring.
"""
import hashlib
import json
import time

import requests

BASE = "https://api.grants.gov/v1/api"
PAGE_ROWS = 100
_REQUEST_GAP_SECONDS = 1.0


class GrantsGovError(RuntimeError):
    """Sanitized Grants.gov failure."""


def _post(path: str, payload: dict) -> dict:
    try:
        resp = requests.post(f"{BASE}{path}", json=payload, timeout=60,
                             headers={"Accept": "application/json"})
    except requests.RequestException as exc:
        raise GrantsGovError(f"network error: {type(exc).__name__}") from None
    if resp.status_code >= 400:
        raise GrantsGovError(f"Grants.gov status {resp.status_code} on {path}")
    try:
        return resp.json()
    except ValueError:
        raise GrantsGovError("non-JSON response from Grants.gov") from None


def _hash(record: dict) -> str:
    return hashlib.sha256(
        json.dumps(record, sort_keys=True, default=str).encode()).hexdigest()


def _num(value):
    if value in (None, "", "none"):
        return None
    try:
        return float(str(value).replace(",", ""))
    except ValueError:
        return None


_STATUS = {"posted": "posted", "forecasted": "forecasted",
           "closed": "closed", "archived": "archived"}

_INSTRUMENT = {"G": "grant", "CA": "cooperative_agreement",
               "O": "other", "PC": "other"}


def normalize_search_hit(hit: dict) -> dict:
    """Normalize one search2 oppHit. Search hits are thin: award amounts and
    eligibility arrive via fetchOpportunity enrichment."""
    gid = str(hit.get("id") or hit.get("number"))
    return {
        "source": "grants_gov",
        "source_grant_id": gid,
        "opportunity_number": hit.get("number"),
        "title": (hit.get("title") or "").strip() or "(untitled)",
        "agency_code": hit.get("agencyCode"),
        "agency_name": hit.get("agencyName") or hit.get("agency"),
        "assistance_listings": [a for a in (hit.get("alist") or
                                            hit.get("cfdaList") or []) if a],
        "opportunity_status": _STATUS.get(
            str(hit.get("oppStatus") or "").lower(), None),
        "posted_date": (hit.get("openDate") or None),
        "close_date": (hit.get("closeDate") or None),
        "award_floor": None,
        "award_ceiling": None,
        "expected_awards": None,
        "total_funding": None,
        "funding_instrument": None,
        "category": None,
        "eligible_applicants": [],
        "cost_sharing": None,
        "description_text": None,
        "source_url": f"https://grants.gov/search-results-detail/{gid}",
        "raw_json": hit,
        "content_hash": _hash(hit),
    }


def apply_detail(rec: dict, detail: dict) -> dict:
    """Merge a fetchOpportunity synopsis into a normalized search record."""
    syn = (detail.get("synopsis") or detail.get("forecast") or {}) \
        if isinstance(detail, dict) else {}
    out = dict(rec)
    out.update({
        "award_floor": _num(syn.get("awardFloor")) or rec.get("award_floor"),
        "award_ceiling": _num(syn.get("awardCeiling")) or rec.get("award_ceiling"),
        "expected_awards": int(syn["expectedNumberOfAwards"])
            if str(syn.get("expectedNumberOfAwards") or "").isdigit() else None,
        "total_funding": _num(syn.get("estimatedFunding")),
        "cost_sharing": {"Yes": True, "No": False}.get(
            str(syn.get("costSharing") or "").capitalize()),
        "eligible_applicants": [
            (a.get("description") or a.get("id") or "").strip()
            for a in (syn.get("applicantTypes") or []) if a],
        "funding_instrument": next(
            (_INSTRUMENT.get(str(fi.get("id") or ""), "other")
             for fi in (syn.get("fundingInstruments") or [])), None),
        "description_text": (syn.get("synopsisDesc") or
                             syn.get("description") or None),
        "raw_json": {"hit": rec.get("raw_json"), "detail": detail},
    })
    out["content_hash"] = _hash(out["raw_json"])
    return out


def search_grants(keyword: str | None = None, statuses: str = "posted",
                  max_pages: int = 5):
    """Yield normalized (thin) grant records from search2, paging politely."""
    start = 0
    for _ in range(max_pages):
        data = _post("/search2", {"rows": PAGE_ROWS, "startRecordNum": start,
                                  "keyword": keyword or "",
                                  "oppStatuses": statuses})
        hits = ((data.get("data") or {}).get("oppHits")) or []
        if not hits:
            return
        for hit in hits:
            yield normalize_search_hit(hit)
        if len(hits) < PAGE_ROWS:
            return
        start += PAGE_ROWS
        time.sleep(_REQUEST_GAP_SECONDS)


def fetch_detail(grant_id: str) -> dict:
    """Full opportunity detail (synopsis) for one grant id."""
    return _post("/fetchOpportunity", {"opportunityId": grant_id})
