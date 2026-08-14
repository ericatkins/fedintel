"""Procurement forecast adapter: DHS APFS API + operator CSV imports.

Agency procurement forecasts are the single highest-value pre-solicitation
demand signal, but the sources are fragmented:

- DHS publishes the Acquisition Planning Forecast System with a public JSON
  API (no key). This adapter implements that API contract; the fixture in
  tests/fixtures mirrors the documented record shape. NOTE: live validation
  is pending in restricted environments (see docs/DATA_SOURCES.md) — the
  adapter fails soft and the pipeline continues without forecasts.
- Most other agencies publish XLSX/CSV forecast files on their OSDBU pages
  (acquisition.gov keeps the directory). Those arrive through the CSV import,
  and every row must carry a source or it is rejected — same rule as staff
  rosters and election results.

Adapter contract: functions return normalized dicts matching the
procurement_forecasts columns. Raw records are retained in raw_json.
"""
import csv
import hashlib
import json
import time
from datetime import date

import requests

APFS_BASE = "https://apfs-cloud.dhs.gov/api/forecast/"
PAGE_LIMIT = 100
_REQUEST_GAP_SECONDS = 1.0


class ForecastError(RuntimeError):
    """Sanitized forecast-source failure."""


def _get(url: str, params: dict) -> dict | list:
    try:
        resp = requests.get(url, params=params, timeout=60,
                            headers={"Accept": "application/json"})
    except requests.RequestException as exc:
        raise ForecastError(f"network error: {type(exc).__name__}") from None
    if resp.status_code >= 400:
        raise ForecastError(f"forecast source status {resp.status_code}")
    try:
        return resp.json()
    except ValueError:
        raise ForecastError("non-JSON response from forecast source") from None


def _hash(record: dict) -> str:
    return hashlib.sha256(
        json.dumps(record, sort_keys=True, default=str).encode()).hexdigest()


def _clean_date(value) -> str | None:
    if not value:
        return None
    text = str(value).strip()[:10]
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError:
        return None


def _dollar_range(text) -> tuple[float | None, float | None]:
    """APFS publishes ranges like '$250,000 to $500,000' or '$1M - $5M'."""
    if not text:
        return None, None
    cleaned = str(text).lower().replace(",", "").replace("$", "")
    cleaned = cleaned.replace(" to ", "|").replace(" - ", "|").replace("-", "|")
    parts = [p.strip() for p in cleaned.split("|") if p.strip()]
    values = []
    for p in parts[:2]:
        mult = 1.0
        if p.endswith("m"):
            mult, p = 1e6, p[:-1]
        elif p.endswith("k"):
            mult, p = 1e3, p[:-1]
        try:
            values.append(float(p) * mult)
        except ValueError:
            continue
    if not values:
        return None, None
    return values[0], values[-1]


_APFS_ACTION = {
    "new requirement": "new_requirement",
    "new": "new_requirement",
    "recompete": "recompete",
    "re-compete": "recompete",
    "option": "option",
}


def normalize_apfs(rec: dict) -> dict:
    """Normalize one APFS record to the procurement_forecasts shape."""
    low, high = _dollar_range(rec.get("dollar_range") or
                              rec.get("estimated_value"))
    action_raw = str(rec.get("action_type") or
                     rec.get("requirement_type") or "").strip().lower()
    incumbent = (rec.get("incumbent_contractor") or
                 rec.get("incumbent") or None)
    apfs_id = rec.get("apfs_number") or rec.get("id")
    return {
        "source": "dhs_apfs",
        "source_record_id": str(apfs_id),
        "agency": "DEPT OF HOMELAND SECURITY",
        "subtier": rec.get("component") or rec.get("organization"),
        "office": rec.get("contracting_office"),
        "title": (rec.get("title") or rec.get("requirement_title") or
                  "").strip() or "(untitled forecast)",
        "description": rec.get("description") or rec.get("requirement_description"),
        "naics": str(rec.get("naics") or rec.get("naics_code") or "") or None,
        "psc": None,
        "estimated_value_low": low,
        "estimated_value_high": high,
        "action_type": _APFS_ACTION.get(action_raw, "unknown"),
        "incumbent_name": str(incumbent).strip() if incumbent else None,
        "contract_vehicle": rec.get("contract_vehicle"),
        "set_aside": rec.get("small_business_program") or rec.get("set_aside"),
        "anticipated_solicitation": _clean_date(
            rec.get("estimated_solicitation_release_date") or
            rec.get("anticipated_solicitation_release")),
        "anticipated_award": _clean_date(
            rec.get("estimated_award_date") or rec.get("anticipated_award")),
        "fiscal_year": int(rec["fiscal_year"]) if str(
            rec.get("fiscal_year") or "").isdigit() else None,
        "place_of_performance": rec.get("place_of_performance"),
        "point_of_contact": rec.get("point_of_contact") or
                            rec.get("small_business_specialist"),
        "source_url": f"https://apfs-cloud.dhs.gov/forecast/{apfs_id}"
                      if apfs_id else None,
        "raw_json": rec,
        "content_hash": _hash(rec),
    }


def fetch_apfs(max_pages: int = 10):
    """Yield normalized DHS APFS forecast records, paging politely."""
    offset = 0
    for _ in range(max_pages):
        data = _get(APFS_BASE, {"limit": PAGE_LIMIT, "offset": offset})
        rows = data.get("results", data) if isinstance(data, dict) else data
        if not rows:
            return
        for rec in rows:
            yield normalize_apfs(rec)
        if len(rows) < PAGE_LIMIT:
            return
        offset += PAGE_LIMIT
        time.sleep(_REQUEST_GAP_SECONDS)


# ---- operator CSV import ----------------------------------------------------

CSV_REQUIRED = ("source_record_id", "agency", "title", "source_url")
CSV_OPTIONAL = ("subtier", "office", "description", "naics", "psc",
                "estimated_value_low", "estimated_value_high", "action_type",
                "incumbent_name", "contract_vehicle", "set_aside",
                "anticipated_solicitation", "anticipated_award", "fiscal_year",
                "place_of_performance", "point_of_contact")


def parse_forecast_csv(path: str):
    """Yield normalized rows from an operator-provided forecast CSV.

    Every row must carry source_record_id, agency, title, and source_url
    (the provenance rule: no source, no row). Rejected rows raise so the
    operator fixes the file rather than silently losing records."""
    with open(path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for lineno, row in enumerate(reader, start=2):
            missing = [c for c in CSV_REQUIRED if not (row.get(c) or "").strip()]
            if missing:
                raise ForecastError(
                    f"line {lineno}: missing required column(s) "
                    f"{', '.join(missing)} — forecasts without provenance are "
                    "rejected")
            action = (row.get("action_type") or "").strip().lower() or None
            if action and action not in ("new_requirement", "recompete",
                                         "option", "unknown"):
                action = "unknown"
            rec = {k: (row.get(k) or "").strip() or None
                   for k in CSV_REQUIRED + CSV_OPTIONAL}
            yield {
                **rec,
                "source": "csv_import",
                "action_type": action,
                "estimated_value_low": float(rec["estimated_value_low"])
                    if rec.get("estimated_value_low") else None,
                "estimated_value_high": float(rec["estimated_value_high"])
                    if rec.get("estimated_value_high") else None,
                "anticipated_solicitation": _clean_date(
                    rec.get("anticipated_solicitation")),
                "anticipated_award": _clean_date(rec.get("anticipated_award")),
                "fiscal_year": int(rec["fiscal_year"])
                    if str(rec.get("fiscal_year") or "").isdigit() else None,
                "raw_json": dict(row),
                "content_hash": _hash(dict(row)),
            }
