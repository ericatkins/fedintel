"""Normalize raw source records into the common opportunity schema.

Every adapter maps into this shape. Downstream code (dedup, classify, score,
digest) never touches source-specific fields — that's what makes adding state
and city adapters cheap later.

All fields are untrusted. Validation lives in validate(); rendering-time
escaping lives in digest.py; URL safety lives in safety.py.
"""
import hashlib
import json
from datetime import datetime


class InvalidRecord(ValueError):
    """Raised when a normalized record fails minimum validation."""


def content_hash(rec: dict) -> str:
    basis = json.dumps(
        {
            "title": rec.get("title"),
            "type": rec.get("type"),
            "deadline": rec.get("responseDeadLine"),
            "desc": rec.get("description"),
            "naics": rec.get("naicsCode"),
        },
        sort_keys=True,
    )
    return hashlib.sha256(basis.encode()).hexdigest()[:32]


def parse_dt(val):
    """Parse SAM.gov date/datetime strings; None if unparseable."""
    if not val or not isinstance(val, str):
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(val, fmt)
        except (ValueError, TypeError):
            continue
    return None


def _pop_text(rec: dict) -> str | None:
    pop = rec.get("placeOfPerformance")
    if not isinstance(pop, dict):
        return None
    city = ((pop.get("city") or {}).get("name") or "") if isinstance(pop.get("city"), dict) else ""
    state = ((pop.get("state") or {}).get("code") or "") if isinstance(pop.get("state"), dict) else ""
    out = ", ".join(p for p in (city, state) if p)
    return out or None


def _office_identity(rec: dict) -> tuple[str | None, str | None]:
    """Return (buying_office_name, office_location).

    Identity preference: fullParentPathName final segment (the actual buying
    office) > officeAddress only as LOCATION, never identity. organizationCode
    / fullParentPathCode ride along in raw_json for intel-office resolution."""
    office_name = None
    path = rec.get("fullParentPathName")
    if isinstance(path, str) and "." in path:
        office_name = path.split(".")[-1].strip() or None
    addr = rec.get("officeAddress")
    location = None
    if isinstance(addr, dict):
        city = addr.get("city") if isinstance(addr.get("city"), str) else None
        state = addr.get("state") if isinstance(addr.get("state"), str) else None
        location = ", ".join(p for p in (city, state) if p) or None
    return office_name, location


def _agency(rec: dict) -> str | None:
    path = rec.get("fullParentPathName")
    if isinstance(path, str) and path:
        return path.split(".")[0]
    dept = rec.get("department")
    return dept if isinstance(dept, str) else None


def normalize_sam(rec: dict) -> dict:
    """SAM.gov v2 record -> normalized opportunity dict. Raises InvalidRecord
    if the record can't be represented safely."""
    if not isinstance(rec, dict):
        raise InvalidRecord("record is not an object")
    office_name, office_location = _office_identity(rec)
    opp = {
        "source": "sam.gov",
        "source_notice_id": rec.get("noticeId"),
        "solicitation_number": rec.get("solicitationNumber"),
        "title": (rec.get("title") or "").strip() if isinstance(rec.get("title"), str) else "",
        "agency": _agency(rec),
        "office": office_name,
        "office_location": office_location,
        "jurisdiction": "federal",
        "notice_type": rec.get("type") if isinstance(rec.get("type"), str) else None,
        "naics": rec.get("naicsCode") if isinstance(rec.get("naicsCode"), str) else None,
        "set_aside": rec.get("typeOfSetAside") or rec.get("typeOfSetAsideDescription"),
        "posted_date": parse_dt(rec.get("postedDate")),
        "response_deadline": parse_dt(rec.get("responseDeadLine")),
        "place_of_performance": _pop_text(rec),
        "description_text": rec.get("description") if isinstance(rec.get("description"), str) else "",
        "url": rec.get("uiLink") if isinstance(rec.get("uiLink"), str) else None,
        "raw_json": rec,
        "content_hash": content_hash(rec),
    }
    validate(opp)
    return opp


def validate(opp: dict):
    """Minimum bar for storage. A bad record raises; the ingest loop skips it."""
    nid = opp.get("source_notice_id")
    if not nid or not isinstance(nid, str):
        raise InvalidRecord("missing noticeId")
    if len(nid) > 200:
        raise InvalidRecord("noticeId implausibly long")
    if not opp.get("title"):
        raise InvalidRecord("missing title")
    if len(opp["title"]) > 1000:
        opp["title"] = opp["title"][:1000]
    if opp.get("set_aside") is not None and not isinstance(opp["set_aside"], str):
        opp["set_aside"] = None
