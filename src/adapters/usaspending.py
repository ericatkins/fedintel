"""USAspending adapter: historical awards, spending aggregates, budget context.

Primary source for award history and funding analytics. No API key required;
still treat every field as untrusted and every error as potentially sensitive.
Adapter contract: functions return normalized dicts matching contract_awards /
funding_accounts columns.
"""
import hashlib
import json
from datetime import date, timedelta

import requests

from ..intel.vendors import normalize_vendor_name

BASE = "https://api.usaspending.gov/api/v2"
AWARD_TYPE_CODES = ["A", "B", "C", "D"]  # contracts
PAGE_LIMIT = 100


class UsaSpendingError(RuntimeError):
    """Sanitized USAspending failure."""


def _post(path: str, payload: dict) -> dict:
    try:
        resp = requests.post(f"{BASE}{path}", json=payload, timeout=60)
    except requests.RequestException as exc:
        raise UsaSpendingError(f"network error: {type(exc).__name__}") from None
    if resp.status_code >= 400:
        raise UsaSpendingError(f"USAspending status {resp.status_code} on {path}")
    try:
        return resp.json()
    except ValueError:
        raise UsaSpendingError(f"non-JSON response on {path}") from None


def _get(path: str) -> dict:
    try:
        resp = requests.get(f"{BASE}{path}", timeout=60)
    except requests.RequestException as exc:
        raise UsaSpendingError(f"network error: {type(exc).__name__}") from None
    if resp.status_code >= 400:
        raise UsaSpendingError(f"USAspending status {resp.status_code} on {path}")
    return resp.json()


FIELDS = [
    "Award ID", "Recipient Name", "Description", "Start Date", "End Date",
    "Award Amount", "Total Outlays", "Awarding Agency", "Awarding Sub Agency",
    "Contract Award Type", "recipient_id", "NAICS", "PSC", "Last Date to Order",
    "Base Obligation Date", "prime_award_recipient_id",
]


def search_awards(subtier: str | None = None, naics: list[str] | None = None,
                  psc: list[str] | None = None, keywords: list[str] | None = None,
                  years_back: int = 10, max_pages: int = 5):
    """Yield normalized award dicts from spending_by_award search."""
    today = date.today()
    filters: dict = {
        "award_type_codes": AWARD_TYPE_CODES,
        "time_period": [{"start_date": str(today - timedelta(days=365 * years_back)),
                         "end_date": str(today)}],
    }
    if subtier:
        filters["agencies"] = [{"type": "awarding", "tier": "subtier", "name": subtier}]
    if naics:
        filters["naics_codes"] = naics
    if psc:
        filters["psc_codes"] = psc
    if keywords:
        filters["keywords"] = keywords

    page = 1
    while page <= max_pages:
        data = _post("/search/spending_by_award/", {
            "filters": filters, "fields": FIELDS, "limit": PAGE_LIMIT,
            "page": page, "sort": "Start Date", "order": "desc",
        })
        results = data.get("results", []) or []
        for rec in results:
            if isinstance(rec, dict):
                yield normalize_usaspending_award(rec)
        if not data.get("page_metadata", {}).get("hasNext") or not results:
            return
        page += 1


def normalize_usaspending_award(rec: dict) -> dict:
    """USAspending spending_by_award row -> contract_awards shape."""
    amount = rec.get("Award Amount")
    basis = json.dumps({"id": rec.get("generated_internal_id") or rec.get("Award ID"),
                        "amt": amount, "end": rec.get("End Date")}, sort_keys=True)
    name = rec.get("Recipient Name")
    return {
        "source": "usaspending",
        "source_award_id": str(rec.get("generated_internal_id") or rec.get("Award ID") or ""),
        "piid": rec.get("Award ID"),
        "parent_award_id": rec.get("prime_award_recipient_id"),
        "solicitation_number": rec.get("Solicitation ID"),
        "award_title": (rec.get("Description") or "")[:500],
        "award_description": rec.get("Description") or "",
        "recipient_name": name,
        "recipient_name_normalized": normalize_vendor_name(name),
        "recipient_uei": rec.get("recipient_uei") or rec.get("Recipient UEI"),
        "recipient_cage": None,
        "awarding_department": rec.get("Awarding Agency"),
        "awarding_subtier": rec.get("Awarding Sub Agency"),
        "awarding_office": rec.get("Awarding Office"),
        "awarding_office_code": rec.get("awarding_office_code"),
        "funding_department": rec.get("Funding Agency"),
        "funding_subtier": rec.get("Funding Sub Agency"),
        "funding_office": rec.get("Funding Office"),
        "naics": str(rec.get("NAICS") or "") or None,
        "psc": str(rec.get("PSC") or "") or None,
        "award_type": rec.get("Contract Award Type"),
        "contract_type": None,
        "contract_vehicle": None,
        "extent_competed": rec.get("extent_competed"),
        "set_aside": rec.get("Set Aside Type") or rec.get("type_set_aside"),
        "award_date": rec.get("Base Obligation Date") or rec.get("Start Date"),
        "period_start": rec.get("Start Date"),
        "period_end": rec.get("End Date"),
        "obligated_amount": float(amount) if amount not in (None, "") else None,
        "total_obligated_amount": float(amount) if amount not in (None, "") else None,
        "potential_total_value": None,
        "place_of_performance_json": rec.get("Place of Performance") or {},
        "raw_json": rec,
        "content_hash": hashlib.sha256(basis.encode()).hexdigest()[:32],
    }


def agency_budgetary_resources(toptier_code: str) -> list[dict]:
    """Agency-level budgetary resources per FY -> funding_accounts rows.
    This is agency-level CONTEXT ONLY (see funding.py truthfulness rules)."""
    data = _get(f"/agency/{toptier_code}/budgetary_resources/")
    rows = []
    for fy in data.get("agency_data_by_year", []) or []:
        rows.append({
            "agency_code": toptier_code,
            "agency_name": data.get("agency_name"),
            "fiscal_year": fy.get("fiscal_year"),
            "budgetary_resources": fy.get("agency_budgetary_resources"),
            "obligations": fy.get("agency_total_obligated"),
            "outlays": None,
            "source": "usaspending",
            "raw_json": fy,
        })
    return rows


def federal_accounts_for(subtier: str, naics: list[str] | None = None) -> list[dict]:
    """Top federal accounts funding this subtier/category -> funding_accounts rows."""
    filters: dict = {"agencies": [{"type": "funding", "tier": "subtier", "name": subtier}],
                     "award_type_codes": AWARD_TYPE_CODES}
    if naics:
        filters["naics_codes"] = naics
    data = _post("/search/spending_by_category/federal_account/",
                 {"filters": filters, "limit": 10})
    rows = []
    for r in data.get("results", []) or []:
        rows.append({
            "federal_account_code": r.get("code"),
            "federal_account_name": r.get("name"),
            "obligations": r.get("amount"),
            "fiscal_year": None,
            "source": "usaspending",
            "raw_json": r,
        })
    return rows
