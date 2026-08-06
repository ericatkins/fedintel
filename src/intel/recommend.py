"""Pursuit recommendation engine. Deterministic, explainable, honest."""
from .confidence import band

OPTIONS = ("Pursue now", "Track closely", "Investigate incumbent first",
           "Find teammate", "Watch only", "Ignore", "Insufficient data")


def recommend(opp_score: int, days_left, incumbent: dict, market: dict,
              competition: dict, work_origin: dict, funding: dict,
              similar_range: tuple | None) -> dict:
    reasons, risks, actions = [], [], []
    inc_status = incumbent.get("incumbent_status")
    inc_conf = incumbent.get("incumbent_confidence", 0)
    comp_label = competition.get("label", "insufficient data")
    trend = market.get("trend", "insufficient data")
    has_history = bool(market.get("windows", {}).get("5y", {}).get("award_count"))

    if opp_score < 30:
        rec, conf = "Ignore", 70
        reasons.append(f"low fit score ({opp_score}) against your profile")
    elif not has_history and trend == "insufficient data" and inc_status == "insufficient_data":
        rec, conf = "Insufficient data", 40
        reasons.append("no historical award context loaded for this office/category")
        actions.append("Trigger intelligence refresh; check back after enrichment completes")
    elif inc_status == "confirmed_incumbent" and inc_conf >= 85:
        rec, conf = "Investigate incumbent first", 78
        reasons.append(f"confirmed incumbent {incumbent.get('likely_incumbent_name')}")
        risks.append("incumbent recompetes are hard to unseat without discriminators")
        actions.append("Review the predecessor award and identify performance gaps")
    elif "incumbent-dominated" in comp_label and opp_score < 75:
        rec, conf = "Watch only", 65
        reasons.append("market is incumbent-dominated and fit is moderate")
        risks.append("high capture cost against a dominant vendor")
    elif opp_score >= 80 and (days_left is None or days_left > 7):
        early = work_origin.get("work_origin_assessment") in ("new_start", "unclear") or \
            (opp_score >= 80 and "early" in str(market.get("note", "")))
        if inc_status in ("likely_incumbent", "possible_incumbent"):
            rec, conf = "Track closely", 75
            reasons.append(f"strong fit ({opp_score}) but a {inc_status.replace('_',' ')} exists")
            actions.append("Assess teaming with or against the likely incumbent")
        elif early:
            rec, conf = "Track closely", 72
            reasons.append("strong fit at an early acquisition stage")
            actions.append("Respond to market research and shape the requirement")
        else:
            rec, conf = "Pursue now", 80
            reasons.append(f"strong fit ({opp_score}) with workable timeline")
            actions.append("Begin bid/no-bid review and outline immediately")
    elif opp_score >= 60:
        rec, conf = "Track closely", 68
        reasons.append(f"moderate-strong fit ({opp_score})")
        if "fragmented" in comp_label:
            reasons.append("fragmented vendor market — room for a new entrant")
        if "large-business dominated" in comp_label:
            rec = "Find teammate"
            reasons.append("large-business dominated market suggests subcontract path")
            actions.append("Identify prime candidates from the vendor landscape")
    else:
        rec, conf = "Watch only", 60
        reasons.append(f"fit score {opp_score} below pursuit threshold")

    if days_left is not None and days_left <= 3 and rec in ("Pursue now", "Track closely"):
        risks.append(f"only {days_left} days to respond")
    if trend == "declining":
        risks.append("spending in this category is declining at this buyer")
    if funding.get("label_key") in ("agency", "none"):
        risks.append("no direct funding evidence — budget alignment is not funding")
    if similar_range:
        reasons.append(f"similar awards from this buyer ranged "
                       f"${similar_range[0]:,.0f}–${similar_range[1]:,.0f}")
    if not actions:
        actions.append("Review the linked prior awards and the buyer office profile")

    return {
        "recommendation": rec,
        "confidence": conf,
        "confidence_band": band(conf),
        "top_reasons": reasons[:5],
        "top_risks": risks[:3],
        "next_actions": actions[:3],
    }
