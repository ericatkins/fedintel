"""Dossier orchestrator: assembles all eleven sections from pure modules.

build_dossier() is a pure function over (opportunity, awards, accounts,
budget_rows) so the whole product surface is testable without a database or
network. Persistence and candidate fetching live in enrich.py / db_intel.py.
"""
from datetime import date, datetime, timezone

from .funding import build_funding_context
from .incumbent import analyze_incumbent, assess_work_origin
from .linking import last_10_relevant, link_awards
from .market import acquisition_pattern, competition_landscape, market_size
from .offices import buyer_profile, office_identity_from_opportunity
from .recommend import recommend

DOSSIER_VERSION = 1


def build_dossier(opp: dict, classification: dict, awards_office: list[dict],
                  awards_subtier: list[dict], accounts: list[dict],
                  budget_rows: list[dict], today: date | None = None) -> dict:
    """awards_office: award history attributed to the buying office.
    awards_subtier: broader subtier/category history (fallback context)."""
    today = today or date.today()
    identity = office_identity_from_opportunity(opp)
    quality: list[str] = []

    pool = awards_office if awards_office else awards_subtier
    level = "office" if awards_office else "subtier"
    if not awards_office and awards_subtier:
        quality.append("Office-level award history incomplete; subtier-level data used.")
    if not pool:
        quality.append("No historical award data loaded for this office/subtier/category.")

    links = link_awards(opp, identity, pool, today=today)
    if not any(ln["link_type"] == "same_solicitation" for ln in links):
        quality.append("No exact solicitation-number match found.")
    quality.append("USAspending and SAM.gov may differ due to timing, updates, or reporting corrections.")
    quality.append("Incumbent analysis is inferred from historical awards, not confirmed by the notice, "
                   "unless marked confirmed.")

    incumbent = analyze_incumbent(opp, links, today=today)
    origin = assess_work_origin(opp, links)
    funding = build_funding_context(opp, links, accounts, budget_rows)
    if funding["label_key"] in ("agency", "likely"):
        quality.append("Budget data is agency/account-level and does not prove funding for "
                       "this specific opportunity.")
    market = market_size(pool, today=today, level=level)
    competition = competition_landscape(pool)
    acq = acquisition_pattern(pool, opp)
    profile = buyer_profile(identity, awards_office or awards_subtier)

    relevant = last_10_relevant(links)
    sim_values = [float(ln["award"].get("obligated_amount") or 0)
                  for ln in relevant if ln["award"].get("obligated_amount")]
    similar_range = (min(sim_values), max(sim_values)) if len(sim_values) >= 2 else None

    days_left = None
    if opp.get("response_deadline"):
        d = opp["response_deadline"]
        d = d if getattr(d, "tzinfo", None) else d.replace(tzinfo=timezone.utc)
        days_left = (d.date() - today).days

    rec = recommend(classification.get("score", 0), days_left, incumbent, market,
                    competition, origin, funding, similar_range)

    return {
        "dossier_version": DOSSIER_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "snapshot": _snapshot(opp, classification, rec, origin),
        "buyer_profile": profile,
        "similar_work": [_link_row(ln) for ln in links[:25]],
        "last_10_relevant_awards": [_link_row(ln) for ln in relevant],
        "incumbent_analysis": incumbent,
        "work_origin_assessment": origin,
        "funding_context": funding,
        "market_size": market,
        "competition_landscape": competition,
        "acquisition_pattern": acq,
        "pursuit_recommendation": rec,
        "data_quality": quality,
        "similar_award_range": similar_range,
    }


def _snapshot(opp, classification, rec, origin):
    return {
        "title": opp.get("title"),
        "agency": opp.get("agency"),
        "office": opp.get("office"),
        "notice_type": opp.get("notice_type"),
        "naics": opp.get("naics"),
        "psc": opp.get("psc"),
        "set_aside": opp.get("set_aside"),
        "place_of_performance": opp.get("place_of_performance"),
        "response_deadline": str(opp.get("response_deadline") or ""),
        "match_score": classification.get("score"),
        "category": classification.get("category"),
        "acquisition_stage": opp.get("notice_type"),
        "recommendation": rec.get("recommendation"),
        "what_this_is": _plain_summary(opp, classification, origin),
    }


def _plain_summary(opp, classification, origin) -> str:
    """Deterministic 'what this is' line; AI can later replace with a grounded
    summary but the dossier must not depend on it."""
    agency = opp.get("agency") or "Agency"
    cat = (classification.get("category") or "software work").lower()
    origin_label = origin.get("work_origin_assessment", "unclear").replace("_", " ")
    return (f"{agency} office appears to be seeking {cat}; assessment suggests "
            f"{origin_label} based on notice language and award history.")


def _link_row(ln) -> dict:
    a = ln["award"]
    return {
        "source_award_id": a.get("source_award_id"),
        "piid": a.get("piid"),
        "title": a.get("award_title"),
        "vendor": a.get("recipient_name"),
        "award_date": str(a.get("award_date") or ""),
        "obligated_amount": a.get("obligated_amount"),
        "potential_total_value": a.get("potential_total_value"),
        "award_type": a.get("award_type"),
        "naics": a.get("naics"),
        "psc": a.get("psc"),
        "contract_vehicle": a.get("contract_vehicle"),
        "awarding_office": a.get("awarding_office"),
        "link_type": ln["link_type"],
        "similarity_score": ln["similarity_score"],
        "reason_matched": ln["evidence"],
        "source": a.get("source"),
    }


def intel_line(dossier: dict) -> str:
    """One compact intelligence line for the email digest."""
    n = len(dossier.get("similar_work", []))
    parts = []
    if n:
        yrs = {str(r.get("award_date") or "")[:4] for r in dossier["similar_work"] if r.get("award_date")}
        since = f" since FY{min(yrs)}" if yrs and min(yrs).isdigit() else ""
        parts.append(f"{n} similar award{'s' if n != 1 else ''} from this buyer{since}")
    inc = dossier.get("incumbent_analysis", {})
    if inc.get("likely_incumbent_name"):
        qualifier = {"confirmed_incumbent": "confirmed incumbent",
                     "likely_incumbent": "likely incumbent",
                     "possible_incumbent": "possible incumbent"}.get(inc.get("incumbent_status"))
        if qualifier:
            parts.append(f"{qualifier} {inc['likely_incumbent_name']} "
                         f"({inc.get('incumbent_confidence', 0)}% confidence)")
    rng = dossier.get("similar_award_range")
    if rng:
        parts.append(f"similar-award range ${rng[0]:,.0f}–${rng[1]:,.0f}")
    if not parts:
        return "Intel: no comparable award history found in public data yet."
    return "Intel: " + "; ".join(parts) + "."
