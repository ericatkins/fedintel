"""Materialization logic for vendor_profiles and office_market_stats.

Pure aggregation functions over award dicts (testable without a database);
enrich.py handles fetching rows and persisting results.
"""
from collections import defaultdict
from statistics import median

from .offices import office_key
from .vendors import build_vendor_profile, normalize_vendor_name


def group_awards_by_vendor(awards: list[dict]) -> dict[tuple, list[dict]]:
    """Group by (normalized_name, uei). UEI splits same-name vendors;
    same UEI different display names still groups (identifier wins)."""
    groups: dict[tuple, list[dict]] = defaultdict(list)
    by_uei: dict[str, tuple] = {}
    for a in awards:
        norm = normalize_vendor_name(a.get("recipient_name"))
        uei = a.get("recipient_uei") or ""
        if not norm and not uei:
            continue
        key = by_uei.get(uei) if uei and uei in by_uei else (norm, uei)
        if uei:
            by_uei[uei] = key
        groups[key].append(a)
    return groups


def vendor_profiles(awards: list[dict]) -> list[dict]:
    return [build_vendor_profile(group) for group in group_awards_by_vendor(awards).values()
            if group]


def office_market_stats(awards: list[dict]) -> list[dict]:
    """Aggregate awards into (office_key, fiscal_year, naics) stat rows."""
    groups: dict[tuple, list[dict]] = defaultdict(list)
    identities: dict[str, dict] = {}
    for a in awards:
        identity = {
            "organization_code": a.get("awarding_office_code"),
            "office_name": a.get("awarding_office"),
            "subtier_name": a.get("awarding_subtier"),
            "department_name": a.get("awarding_department"),
        }
        key, _, _ = office_key(identity)
        if key == "unknown":
            continue
        identities[key] = identity
        fy = _fiscal_year(a.get("award_date"))
        if fy is None:
            continue
        groups[(key, fy, a.get("naics"), a.get("psc"))].append(a)

    rows = []
    for (key, fy, naics, psc), group in groups.items():
        vals = [float(a.get("obligated_amount") or 0) for a in group]
        vendors = {normalize_vendor_name(a.get("recipient_name")) for a in group
                   if a.get("recipient_name")}
        by_vendor: dict[str, float] = defaultdict(float)
        for a in group:
            by_vendor[normalize_vendor_name(a.get("recipient_name")) or "UNKNOWN"] += \
                float(a.get("obligated_amount") or 0)
        total = sum(vals)
        top_share = round(100 * max(by_vendor.values()) / total, 1) if total else None
        set_aside = sum(1 for a in group if a.get("set_aside")
                        and "none" not in a["set_aside"].lower())
        small_biz = sum(1 for a in group if a.get("set_aside")
                        and "small business" in a["set_aside"].lower())
        competed = [a for a in group if a.get("extent_competed")]
        competed_full = sum(1 for a in competed
                            if "full" in a["extent_competed"].lower()
                            or a["extent_competed"].lower() == "competed")
        rows.append({
            "office_key": key,
            "identity": identities[key],
            "fiscal_year": fy,
            "naics": naics,
            "psc": psc,
            "fedintel_category": _category_for_naics(naics),
            "award_count": len(group),
            "total_obligations": round(total, 2),
            "median_award_value": round(median(vals), 2) if vals else None,
            "average_award_value": round(total / len(vals), 2) if vals else None,
            "largest_award_value": round(max(vals), 2) if vals else None,
            "unique_vendor_count": len(vendors),
            "top_vendor_share": top_share,
            "small_business_share": round(100 * small_biz / len(group), 1),
            "set_aside_share": round(100 * set_aside / len(group), 1),
            "competed_share": (round(100 * competed_full / len(competed), 1)
                               if competed else None),
        })
    return rows


NAICS_CATEGORIES = {
    "541511": "Software", "541512": "Software", "541519": "Software",
    "518210": "Cloud/Data", "541513": "IT Services", "541690": "Technical Consulting",
    "541330": "Engineering", "541715": "R&D",
}


def _category_for_naics(naics) -> str | None:
    return NAICS_CATEGORIES.get(str(naics or "")) or None


def _fiscal_year(award_date) -> int | None:
    if not award_date:
        return None
    s = str(award_date)
    try:
        year, month = int(s[:4]), int(s[5:7])
    except (ValueError, IndexError):
        return None
    return year + 1 if month >= 10 else year  # federal FY starts Oct 1
