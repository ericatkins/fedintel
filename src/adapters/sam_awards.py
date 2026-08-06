"""SAM.gov award-notice adapter.

SAM.gov's opportunities API exposes award notices (ptype=a) carrying an
`award` block (number, amount, awardee, date). These are a secondary award
source — great for linking solicitation numbers to awardees — while
USAspending remains primary for spend analytics. Same key-hygiene rules as
the opportunities adapter: never log request URLs or raw HTTP errors.
"""
import hashlib
import json

from ..intel.vendors import normalize_vendor_name
from . import sam_gov


def fetch_award_notices(naics: str | None = None):
    """Yield normalized contract_awards rows from SAM award notices."""
    for rec in sam_gov.fetch(naics=naics, ptype="a"):
        norm = normalize_sam_award(rec)
        if norm:
            yield norm


def normalize_sam_award(rec: dict) -> dict | None:
    if not isinstance(rec, dict):
        return None
    award = rec.get("award") or {}
    if not isinstance(award, dict):
        award = {}
    awardee = award.get("awardee") or {}
    if not isinstance(awardee, dict):
        awardee = {}
    notice_id = rec.get("noticeId")
    if not notice_id:
        return None
    name = awardee.get("name")
    amount = award.get("amount")
    try:
        amount = float(str(amount).replace(",", "")) if amount not in (None, "") else None
    except ValueError:
        amount = None
    path = rec.get("fullParentPathName") or ""
    parts = path.split(".") if isinstance(path, str) else []
    basis = json.dumps({"id": notice_id, "amt": amount, "num": award.get("number")}, sort_keys=True)
    return {
        "source": "sam.gov",
        "source_award_id": str(notice_id),
        "piid": award.get("number"),
        "parent_award_id": None,
        "solicitation_number": rec.get("solicitationNumber"),
        "award_title": (rec.get("title") or "")[:500],
        "award_description": rec.get("description") if isinstance(rec.get("description"), str) else "",
        "recipient_name": name,
        "recipient_name_normalized": normalize_vendor_name(name),
        "recipient_uei": awardee.get("ueiSAM"),
        "recipient_cage": awardee.get("cageCode"),
        "awarding_department": parts[0] if parts else None,
        "awarding_subtier": parts[1] if len(parts) > 1 else None,
        "awarding_office": parts[-1] if parts else None,
        "awarding_office_code": (rec.get("organizationCode")
                                 if isinstance(rec.get("organizationCode"), str) else None),
        "funding_department": None, "funding_subtier": None, "funding_office": None,
        "naics": rec.get("naicsCode") if isinstance(rec.get("naicsCode"), str) else None,
        "psc": rec.get("classificationCode") if isinstance(rec.get("classificationCode"), str) else None,
        "award_type": rec.get("type"),
        "contract_type": None, "contract_vehicle": None,
        "extent_competed": None,
        "set_aside": rec.get("typeOfSetAside"),
        "award_date": award.get("date"),
        "period_start": None, "period_end": None,
        "obligated_amount": amount,
        "total_obligated_amount": amount,
        "potential_total_value": None,
        "place_of_performance_json": rec.get("placeOfPerformance") or {},
        "raw_json": rec,
        "content_hash": hashlib.sha256(basis.encode()).hexdigest()[:32],
    }
