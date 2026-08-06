"""Vendor entity resolution and profiles. Public data only."""
import re
from collections import Counter

_SUFFIXES = {"INC", "LLC", "LC", "CORP", "CORPORATION", "LIMITED", "LTD", "CO", "COMPANY",
             "LLP", "LP", "PLC", "PC", "INCORPORATED"}


def normalize_vendor_name(name: str | None) -> str:
    """Uppercase, strip punctuation and common suffixes. Display name is kept
    separately; never merge vendors on fuzzy names alone (prefer UEI/CAGE)."""
    if not name:
        return ""
    up = re.sub(r"[^A-Z0-9 ]", " ", name.upper())
    parts = [p for p in up.split() if p]
    while parts and parts[-1] in _SUFFIXES:
        parts.pop()
    return " ".join(parts)


def same_vendor(a: dict, b: dict) -> bool:
    """High-confidence identity: UEI match, else CAGE match, else exact
    normalized name. Fuzzy-only matches are deliberately NOT merged."""
    if a.get("recipient_uei") and a.get("recipient_uei") == b.get("recipient_uei"):
        return True
    if a.get("recipient_cage") and a.get("recipient_cage") == b.get("recipient_cage"):
        return True
    na, nb = normalize_vendor_name(a.get("recipient_name")), normalize_vendor_name(b.get("recipient_name"))
    return bool(na) and na == nb


def build_vendor_profile(awards: list[dict]) -> dict:
    """Aggregate a vendor's public award history into a profile dict."""
    if not awards:
        return {}
    name = awards[0].get("recipient_name") or ""
    obligations = sum(float(a.get("obligated_amount") or 0) for a in awards)
    dates = sorted(d for d in (a.get("award_date") for a in awards) if d)
    top = lambda key: [{"value": v, "count": c} for v, c in  # noqa: E731
                       Counter(a.get(key) for a in awards if a.get(key)).most_common(5)]
    return {
        "recipient_name": name,
        "normalized_recipient_name": normalize_vendor_name(name),
        "recipient_uei": next((a.get("recipient_uei") for a in awards if a.get("recipient_uei")), None),
        "recipient_cage": next((a.get("recipient_cage") for a in awards if a.get("recipient_cage")), None),
        "total_obligations": round(obligations, 2),
        "award_count": len(awards),
        "first_award_date": str(dates[0]) if dates else None,
        "last_award_date": str(dates[-1]) if dates else None,
        "top_agencies": top("awarding_subtier"),
        "top_naics": top("naics"),
        "top_psc": top("psc"),
        "top_offices": top("awarding_office"),
    }
