"""Adapter: USAspending spending_by_geography at congressional-district scope.

Aggregates obligations by PLACE OF PERFORMANCE district per fiscal year, with
optional awarding-agency filter. This measures money flowing INTO a district —
it says nothing about who caused it; callers must preserve that framing.
Note: district shapes change at redistricting; USAspending reports against the
district boundaries in effect for the period queried.
"""
import requests

from ..log import log

URL = "https://api.usaspending.gov/api/v2/search/spending_by_geography/"
TIMEOUT = 60


def district_obligations(fiscal_year: int, agency: str | None = None) -> list[dict]:
    """Returns [{'state','district','obligations'}] for one FY (Oct 1–Sep 30).
    agency: toptier awarding agency name, or None for all agencies."""
    filters = {
        "time_period": [{"start_date": f"{fiscal_year - 1}-10-01",
                         "end_date": f"{fiscal_year}-09-30"}],
    }
    if agency:
        filters["agencies"] = [{"type": "awarding", "tier": "toptier",
                                "name": agency}]
    payload = {"scope": "place_of_performance", "geo_layer": "district",
               "filters": filters}
    try:
        resp = requests.post(URL, json=payload, timeout=TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError) as exc:
        log("usaspending_geo_error", fy=fiscal_year, agency=agency,
            error=type(exc).__name__)
        return []
    return parse_results(data)


def parse_results(data: dict) -> list[dict]:
    out = []
    for row in (data or {}).get("results") or []:
        shape = (row.get("shape_code") or "").strip()      # e.g. 'AL05', 'WY00'
        if len(shape) < 3:
            continue
        state, district_text = shape[:2].upper(), shape[2:]
        try:
            district = int(district_text)
        except ValueError:
            continue
        amount = float(row.get("aggregated_amount") or 0)
        if amount <= 0:
            continue
        out.append({"state": state, "district": district, "obligations": amount})
    return out
