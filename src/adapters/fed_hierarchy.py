"""SAM.gov Federal Hierarchy public API adapter.

Used to normalize department/subtier identities. Public hierarchy may not
expose full office-level detail; office identity falls back to opportunity
and award records (see intel/offices.py), and rows are stored with
source_confidence reflecting that.
"""
import requests

from ..config import SAM_API_KEY
from ..log import log

BASE_URL = "https://api.sam.gov/prod/federalorganizations/v1/orgs"


class HierarchyError(RuntimeError):
    """Sanitized hierarchy API failure."""


def lookup(org_key: str) -> dict | None:
    """Fetch one org record; returns a buyer_offices-shaped dict or None."""
    try:
        resp = requests.get(BASE_URL, params={"api_key": SAM_API_KEY, "fhorgid": org_key},
                            timeout=30)
    except requests.RequestException as exc:
        raise HierarchyError(f"network error: {type(exc).__name__}") from None
    if resp.status_code >= 400:
        log("hierarchy_lookup_failed", status=resp.status_code)
        return None
    try:
        data = resp.json()
    except ValueError:
        return None
    orgs = (data.get("orglist") or []) if isinstance(data, dict) else []
    if not orgs:
        return None
    org = orgs[0]
    return {
        "department_name": org.get("l1OrgName") or org.get("departmentName"),
        "department_code": str(org.get("l1OrgKey") or "") or None,
        "subtier_name": org.get("l2OrgName") or org.get("agencyName"),
        "subtier_code": str(org.get("l2OrgKey") or "") or None,
        "office_name": org.get("fhorgname"),
        "office_code": str(org.get("fhorgid") or "") or None,
        "organization_code": str(org.get("fhorgid") or "") or None,
        "location_json": {"city": org.get("cityName"), "state": org.get("stateName")},
        "source_confidence": 85,
        "raw_hierarchy_json": org,
    }
