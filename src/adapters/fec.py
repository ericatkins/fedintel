"""Adapter: FEC API (api.open.fec.gov) — campaign-finance aggregates.

TRUTHFULNESS RULES (enforced here, preserved by every caller):
- Corporations cannot contribute to federal candidates. 'Employer' rows are
  aggregates of INDIVIDUAL contributions by the employer those individuals
  reported. Never render these as "Company X donated".
- 'PAC' rows are receipts from political committees (which include corporate
  PACs, trade associations, leadership PACs, and party committees).
Requires FEC_API_KEY (free; DEMO_KEY works for light use).
"""
import os

import requests

from ..log import log

BASE = "https://api.open.fec.gov/v1"
TIMEOUT = 30


def _key() -> str:
    return os.getenv("FEC_API_KEY", "DEMO_KEY")


def _get(path: str, **params):
    resp = requests.get(f"{BASE}{path}",
                        params={"api_key": _key(), "per_page": 20, **params},
                        timeout=TIMEOUT)
    resp.raise_for_status()
    return resp.json()


def principal_committee_id(candidate_id: str) -> str | None:
    try:
        data = _get(f"/candidate/{candidate_id}/committees/", designation="P")
    except requests.RequestException as exc:
        log("fec_error", endpoint="committees", error=type(exc).__name__)
        return None
    results = data.get("results") or []
    return results[0]["committee_id"] if results else None


def top_employers(committee_id: str, cycle: int, limit: int = 10) -> list[dict]:
    """Aggregated INDIVIDUAL contributions by reported employer."""
    try:
        data = _get("/schedules/schedule_a/by_employer/",
                    committee_id=committee_id, cycle=cycle,
                    sort="-total", per_page=limit)
    except requests.RequestException as exc:
        log("fec_error", endpoint="by_employer", error=type(exc).__name__)
        return []
    return [{"contributor_name": r.get("employer") or "NOT REPORTED",
             "total": float(r.get("total") or 0),
             "contribution_count": r.get("count"),
             "kind": "employer_aggregate"}
            for r in (data.get("results") or []) if r.get("total")]


def committee_totals(committee_id: str, cycle: int) -> dict | None:
    """Financial summary: receipts, disbursements, cash on hand (last report)."""
    try:
        data = _get(f"/committee/{committee_id}/totals/", cycle=cycle)
    except requests.RequestException as exc:
        log("fec_error", endpoint="totals", error=type(exc).__name__)
        return None
    results = data.get("results") or []
    if not results:
        return None
    r = results[0]
    return {"receipts": float(r.get("receipts") or 0),
            "disbursements": float(r.get("disbursements") or 0),
            "cash_on_hand": float(r.get("last_cash_on_hand_end_period") or 0)}


def district_candidates(state: str, district: int | None, cycle: int,
                        office: str = "H") -> list[dict]:
    """Candidates who have FILED for this seat this cycle (challenger scan)."""
    params = {"state": state, "cycle": cycle, "office": office,
              "sort": "-receipts" if False else "name"}
    if office == "H" and district is not None:
        params["district"] = f"{district:02d}"
    try:
        data = _get("/candidates/search/", **params)
    except requests.RequestException as exc:
        log("fec_error", endpoint="candidates", error=type(exc).__name__)
        return []
    out = []
    for r in (data.get("results") or []):
        out.append({"candidate_id": r.get("candidate_id"),
                    "candidate_name": r.get("name"),
                    "party": r.get("party"),
                    "incumbent_challenge": r.get("incumbent_challenge"),
                    "principal_committee_id":
                        ((r.get("principal_committees") or [{}])[0]
                         .get("committee_id"))})
    return out


def top_pacs(committee_id: str, cycle: int, limit: int = 10) -> list[dict]:
    """Largest itemized receipts from political committees (first page,
    best-effort — labeled as PAC/committee receipts)."""
    try:
        data = _get("/schedules/schedule_a/",
                    committee_id=committee_id, two_year_transaction_period=cycle,
                    is_individual="false", sort="-contribution_receipt_amount",
                    per_page=limit)
    except requests.RequestException as exc:
        log("fec_error", endpoint="schedule_a", error=type(exc).__name__)
        return []
    seen: dict[str, dict] = {}
    for r in (data.get("results") or []):
        name = (r.get("contributor_name") or "").strip()
        amount = float(r.get("contribution_receipt_amount") or 0)
        if not name or amount <= 0:
            continue
        row = seen.setdefault(name, {"contributor_name": name, "total": 0.0,
                                     "contribution_count": 0, "kind": "pac"})
        row["total"] += amount
        row["contribution_count"] += 1
    return sorted(seen.values(), key=lambda r: -r["total"])[:limit]
