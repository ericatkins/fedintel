"""Market size, trend, and competition/vendor landscape from award history."""
from collections import Counter, defaultdict
from datetime import date
from statistics import median

from .vendors import normalize_vendor_name


def _year(a):
    d = a.get("award_date")
    try:
        return int(str(d)[:4]) if d else None
    except ValueError:
        return None


def market_size(awards: list[dict], today: date | None = None, level: str = "office") -> dict:
    """Obligations/counts over 1/3/5-year windows plus a trend label."""
    today = today or date.today()
    if not awards:
        return {"level": level, "trend": "insufficient data", "windows": {},
                "note": f"{level.title()}-level historical data is thin."}

    def window(yrs):
        sub = [a for a in awards if _year(a) and _year(a) > today.year - yrs]
        vals = [float(a.get("obligated_amount") or 0) for a in sub]
        return {
            "award_count": len(sub),
            "total_obligations": round(sum(vals), 2),
            "average_award_size": round(sum(vals) / len(vals), 2) if vals else None,
            "median_award_size": round(median(vals), 2) if vals else None,
            "largest_award": round(max(vals), 2) if vals else None,
        }

    by_year = defaultdict(float)
    for a in awards:
        y = _year(a)
        if y:
            by_year[y] += float(a.get("obligated_amount") or 0)
    years = sorted(y for y in by_year if y >= today.year - 5)
    trend = "insufficient data"
    yoy = None
    if len(years) >= 3:
        vals = [by_year[y] for y in years]
        first_half = sum(vals[: len(vals) // 2]) / max(1, len(vals) // 2)
        second_half = sum(vals[len(vals) // 2:]) / max(1, len(vals) - len(vals) // 2)
        swings = sum(1 for i in range(1, len(vals))
                     if vals[i - 1] and abs(vals[i] - vals[i - 1]) / vals[i - 1] > 0.6)
        if swings >= len(vals) - 1 and len(vals) >= 3:
            trend = "volatile"
        elif first_half and second_half / first_half >= 1.15:
            trend = "growing"
        elif first_half and second_half / first_half <= 0.85:
            trend = "declining"
        else:
            trend = "flat"
        if len(years) >= 2 and by_year[years[-2]]:
            yoy = round(100 * (by_year[years[-1]] - by_year[years[-2]]) / by_year[years[-2]], 1)

    return {
        "level": level,
        "windows": {"12m": window(1), "3y": window(3), "5y": window(5)},
        "trend": trend,
        "yoy_change_pct": yoy,
        "by_year": {str(y): round(by_year[y], 2) for y in sorted(by_year)},
    }


def competition_landscape(awards: list[dict]) -> dict:
    """Vendor landscape, concentration, and competition label."""
    if not awards:
        return {"label": "insufficient data", "vendors": [], "unique_vendor_count": 0}

    by_vendor = defaultdict(lambda: {"obligations": 0.0, "award_count": 0,
                                     "last_award_date": None, "naics": Counter(),
                                     "agencies": Counter(), "name": None})
    total = 0.0
    for a in awards:
        key = normalize_vendor_name(a.get("recipient_name")) or "UNKNOWN"
        v = by_vendor[key]
        v["name"] = v["name"] or a.get("recipient_name")
        amt = float(a.get("obligated_amount") or 0)
        v["obligations"] += amt
        total += amt
        v["award_count"] += 1
        d = str(a.get("award_date") or "")
        if d and (v["last_award_date"] is None or d > v["last_award_date"]):
            v["last_award_date"] = d
        if a.get("naics"):
            v["naics"][a["naics"]] += 1
        if a.get("awarding_subtier"):
            v["agencies"][a["awarding_subtier"]] += 1

    ranked = sorted(by_vendor.values(), key=lambda v: v["obligations"], reverse=True)
    top3_share = round(100 * sum(v["obligations"] for v in ranked[:3]) / total, 1) if total else None

    set_aside_awards = sum(1 for a in awards if a.get("set_aside")
                           and "none" not in a["set_aside"].lower())
    small_biz_share = round(100 * set_aside_awards / len(awards), 1)

    if top3_share is None:
        label = "insufficient data"
    elif len(ranked) == 1 or (top3_share >= 85 and ranked[0]["obligations"] / total >= 0.6):
        label = "incumbent-dominated"
    elif top3_share >= 70:
        label = "highly concentrated"
    elif top3_share >= 45:
        label = "moderately concentrated"
    else:
        label = "fragmented market"
    if small_biz_share >= 40:
        label += "; small-business friendly"
    elif small_biz_share <= 10 and len(awards) >= 5:
        label += "; large-business dominated"

    return {
        "label": label,
        "unique_vendor_count": len(ranked),
        "top3_share_pct": top3_share,
        "small_business_setaside_share_pct": small_biz_share,
        "vendors": [
            {"vendor_name": v["name"], "obligations": round(v["obligations"], 2),
             "award_count": v["award_count"], "last_award_date": v["last_award_date"],
             "common_naics": [n for n, _ in v["naics"].most_common(3)],
             "agencies_served": [x for x, _ in v["agencies"].most_common(3)],
             "fit_reason": "prior awards in this office/category"}
            for v in ranked[:10]
        ],
    }


def acquisition_pattern(awards: list[dict], opp: dict) -> dict:
    """How this office tends to buy, and what this posting likely becomes."""
    types = Counter(a.get("award_type") for a in awards if a.get("award_type"))
    vehicles = Counter(a.get("contract_vehicle") for a in awards if a.get("contract_vehicle"))
    ntype = (opp.get("notice_type") or "").lower()
    text = f"{opp.get('title','')} {opp.get('description_text','')}".lower()
    likely = {
        "likely_to_become_rfp": "sources sought" in ntype or "presolicitation" in ntype,
        "likely_market_research_only": "rfi" in ntype or "special notice" in ntype,
        "likely_task_order": any("task" in (t or "").lower() for t in types) and bool(vehicles),
        "likely_set_aside": bool(opp.get("set_aside")),
        "near_term_vs_early_signal": ("near-term solicitation" if "solicitation" in ntype
                                      else "early signal"),
    }
    if "idiq" in text or "task order" in text:
        likely["likely_task_order"] = True
    return {
        "common_award_types": [{"type": t, "count": c} for t, c in types.most_common(5)],
        "common_vehicles": [{"vehicle": v, "count": c} for v, c in vehicles.most_common(5)],
        "assessment": likely,
    }
