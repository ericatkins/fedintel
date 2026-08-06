"""Adapter: US Census Geocoder (free, no key) — place → congressional district.

Coverage endpoint: geocoding.geo.census.gov onelineaddress with layers for the
current congressional districts. A city-level lookup returns the district of
the city's matched point; cities can span districts, so callers must carry the
confidence tier, never present a city-tier match as certain.
"""
import requests

from ..log import log

URL = "https://geocoding.geo.census.gov/geocoder/geographies/onelineaddress"
TIMEOUT = 30


def lookup_district(place: str) -> dict | None:
    """place: 'City, ST', 'City, ST 12345', or a street address. Returns
    {'state': 'AL', 'congressional_district': 5, 'raw': ...} or None."""
    try:
        resp = requests.get(URL, params={
            "address": place, "benchmark": "Public_AR_Current",
            "vintage": "Current_Current", "format": "json",
            "layers": "Congressional Districts",
        }, timeout=TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError) as exc:
        log("census_geocode_error", error=type(exc).__name__)
        return None
    matches = (((data or {}).get("result") or {}).get("addressMatches")) or []
    if not matches:
        return None
    geo = (matches[0].get("geographies") or {})
    cds = next((v for k, v in geo.items() if "Congressional" in k), None) or []
    if not cds:
        return None
    cd = cds[0]
    try:
        district = int(cd.get("CD119") or cd.get("BASENAME") or 0)
    except (TypeError, ValueError):
        district = 0
    return {"state": (cd.get("STUSAB") or "").upper() or None,
            "congressional_district": district,
            "raw": {"matched": matches[0].get("matchedAddress"),
                    "layer": {k: None for k in geo}}}
