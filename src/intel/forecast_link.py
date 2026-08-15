"""Forecast-to-opportunity linking: "this opportunity follows that forecast".

Deterministic scoring with stored evidence. A link is recorded only above
threshold; the UI always shows why. Pure functions — no fetching."""
from datetime import date

from .similarity import cosine

LINK_THRESHOLD = 45


def _same_org(a: str | None, b: str | None) -> bool:
    if not a or not b:
        return False
    a, b = a.lower().strip(), b.lower().strip()
    return a in b or b in a


def score_forecast_link(opp: dict, forecast: dict) -> dict | None:
    """Score one (opportunity, forecast) pair. Returns None below threshold."""
    score, evidence = 0, []
    opp_orgs = " > ".join(str(v) for v in (opp.get("agency"),
                                           opp.get("agency_path")) if v)
    if _same_org(opp_orgs, forecast.get("agency")) or \
            _same_org(opp_orgs, forecast.get("subtier")):
        score += 20
        evidence.append("same agency")
        if _same_org(opp.get("office"), forecast.get("office")):
            score += 10
            evidence.append("same contracting office")
    o_naics, f_naics = opp.get("naics") or "", forecast.get("naics") or ""
    if o_naics and f_naics:
        if o_naics == f_naics:
            score += 25
            evidence.append(f"same NAICS {o_naics}")
        elif o_naics[:4] == f_naics[:4]:
            score += 12
            evidence.append(f"same NAICS family {o_naics[:4]}xx")
    sim = cosine(f"{opp.get('title', '')} {opp.get('description_text', '')}",
                 f"{forecast.get('title', '')} {forecast.get('description', '')}")
    score += round(40 * sim)
    if sim >= 0.3:
        evidence.append(f"title/description similarity {round(sim * 100)}%")
    posted, anticipated = opp.get("posted_date"), \
        forecast.get("anticipated_solicitation")
    if posted and anticipated:
        try:
            gap = abs((date.fromisoformat(str(posted)[:10]) -
                       date.fromisoformat(str(anticipated)[:10])).days)
            if gap <= 270:
                score += 10
                evidence.append(
                    f"posted within {gap} days of the forecast's anticipated "
                    "solicitation date")
        except ValueError:
            pass
    if score < LINK_THRESHOLD or len(evidence) < 2:
        return None
    return {"similarity_score": min(100, score),
            "confidence": min(90, score),
            "evidence": evidence}


def link_forecasts(opp: dict, forecasts: list[dict]) -> list[dict]:
    """All above-threshold links for one opportunity, best first."""
    links = []
    for fc in forecasts:
        res = score_forecast_link(opp, fc)
        if res:
            links.append({**res, "forecast": fc})
    links.sort(key=lambda x: -x["similarity_score"])
    return links
