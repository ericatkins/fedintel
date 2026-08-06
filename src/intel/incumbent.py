"""Incumbent analysis and work-origin assessment.

Truthfulness rules enforced here:
- 'confirmed_incumbent' ONLY on same solicitation/contract number or explicit
  notice language naming the incumbent.
- 'no_known_incumbent' is reported as exactly that — never as "no incumbent".
- Every output carries confidence, evidence, and caveats.
"""
import re
from datetime import date

from .confidence import band

INCUMBENT_LANGUAGE = [
    "incumbent", "follow-on", "follow on", "recompete", "existing system",
    "current system", "existing application", "migration", "modernization",
    "operations and maintenance", "o&m", "sustainment", "continue",
]

NEW_START_SIGNALS = [
    "prototype", "pilot", "proof of concept", "initial capability",
    "new requirement", "market research", "request for information",
]
EXISTING_SYSTEM_SIGNALS = [
    "modernization", "migration", "sustainment", "operations and maintenance",
    "o&m", "upgrade", "enhancement", "legacy system", "existing application",
    "database migration", "cloud migration", "current system", "incumbent",
    "recompete", "follow-on", "support services",
]


def analyze_incumbent(opp: dict, links: list[dict], today: date | None = None) -> dict:
    """Return the incumbent analysis dict per spec."""
    today = today or date.today()
    text = f"{opp.get('title','')} {opp.get('description_text','')}".lower()
    notice_mentions = [kw for kw in INCUMBENT_LANGUAGE if kw in text]
    caveats = []

    # Tier 1: confirmed — same solicitation/contract family
    confirmed = [ln for ln in links if ln["link_type"] in ("same_solicitation", "same_contract")
                 and ln["award"].get("recipient_name")]
    if confirmed:
        best = confirmed[0]
        return _result(
            status="confirmed_incumbent",
            name=best["award"]["recipient_name"],
            confidence=min(95, 85 + (5 if notice_mentions else 0)),
            evidence=[f"prior award {best['award'].get('piid') or best['award'].get('source_award_id')} "
                      f"shares the solicitation/contract number"] + best["evidence"],
            links=links, notice_mentions=notice_mentions,
            caveats=["Confirmation is based on identifier match in public award data."],
        )

    # Tier 2: likely — same office, same NAICS/PSC, high similarity, recent end
    strong = []
    for ln in links:
        a = ln["award"]
        ev = " ".join(ln["evidence"])
        if "same buying office" not in ev or not a.get("recipient_name"):
            continue
        sim_ok = ln["similarity_score"] >= 55
        ends_near = _ends_within(a, today, months=12)
        if sim_ok and (("NAICS" in ev or "PSC" in ev) or ends_near):
            strong.append((ln, ends_near))
    if strong:
        ln, ends_near = strong[0]
        conf = 55 + min(20, (ln["similarity_score"] - 55) // 2)
        if ends_near:
            conf += 10
        if notice_mentions:
            conf += 5
        if not notice_mentions:
            caveats.append("No explicit incumbent language found in the SAM.gov notice.")
        return _result("likely_incumbent", ln["award"]["recipient_name"], min(89, conf),
                       ln["evidence"] + (["prior award period ends within 12 months of this posting"]
                                         if ends_near else []),
                       links, notice_mentions, caveats)

    # Tier 3: possible — similar work exists somewhere nearby
    possible = [ln for ln in links if ln["similarity_score"] >= 40 and ln["award"].get("recipient_name")]
    if possible:
        ln = possible[0]
        caveats.append("Match is scope/agency-level only; office or identifier confirmation absent.")
        return _result("possible_incumbent", ln["award"]["recipient_name"],
                       min(49, 25 + ln["similarity_score"] // 4),
                       ln["evidence"], links, notice_mentions, caveats)

    if not links:
        return _result("insufficient_data", None, 10, [], links, notice_mentions,
                       ["No related award history loaded for this office/category. "
                        "Absence of data is not evidence of absence of an incumbent."])
    return _result("no_known_incumbent", None, 30,
                   ["related awards found, but none resembles a predecessor contract"],
                   links, notice_mentions,
                   ["'No known incumbent found' is not the same as 'there is no incumbent'."])


def _result(status, name, confidence, evidence, links, notice_mentions, caveats):
    recompete_why, new_work_why = _recompete_arguments(status, notice_mentions, links)
    return {
        "incumbent_status": status,
        "likely_incumbent_name": name,
        "incumbent_confidence": max(0, min(100, confidence)),
        "confidence_band": band(confidence),
        "supporting_evidence": evidence,
        "notice_language_signals": notice_mentions,
        "prior_awards_considered": [
            {"source_award_id": ln["award"].get("source_award_id"),
             "recipient": ln["award"].get("recipient_name"),
             "similarity_score": ln["similarity_score"]}
            for ln in links[:10]
        ],
        "why_this_may_be_a_recompete": recompete_why,
        "why_this_may_be_new_work": new_work_why,
        "caveats": caveats,
    }


def _recompete_arguments(status, notice_mentions, links):
    recompete, new_work = [], []
    if status in ("confirmed_incumbent", "likely_incumbent"):
        recompete.append("a plausible predecessor award exists")
    if any(m in ("recompete", "follow-on", "follow on", "incumbent") for m in notice_mentions):
        recompete.append("notice language references prior/continuing work")
    if any(m in ("modernization", "migration", "legacy system", "existing system", "current system")
           for m in notice_mentions):
        recompete.append("notice references an existing system")
    if not links:
        new_work.append("no related prior awards found in loaded data")
    if not notice_mentions:
        new_work.append("no continuation language in the notice")
    return recompete, new_work


def _ends_within(award: dict, today: date, months: int) -> bool:
    end = award.get("period_end")
    if not end:
        return False
    try:
        end_d = date.fromisoformat(str(end)[:10])
    except ValueError:
        return False
    return abs((end_d - today).days) <= months * 30


def assess_work_origin(opp: dict, links: list[dict]) -> dict:
    """Classify: new start / modernization / O&M / recompete / task order /
    research prototype / follow-on / unclear — with evidence and caveats."""
    text = f"{opp.get('title','')} {opp.get('description_text','')}".lower()
    new_hits = [s for s in NEW_START_SIGNALS if s in text]
    exist_hits = [s for s in EXISTING_SYSTEM_SIGNALS if s in text]
    has_predecessor = any(ln["link_type"] in ("same_solicitation", "same_contract") for ln in links)
    strong_history = any(ln["similarity_score"] >= 55 for ln in links)
    ntype = (opp.get("notice_type") or "").lower()

    if has_predecessor or "recompete" in text:
        label, conf = "recompete", 80 if has_predecessor else 65
    elif re.search(r"task order|delivery order|idiq|bpa call", text):
        label, conf = "task_order_under_existing_vehicle", 70
    elif any(s in text for s in ("operations and maintenance", "o&m", "sustainment")):
        label, conf = "om_sustainment", 70
    elif any(s in text for s in ("modernization", "migration", "legacy system",
                                 "existing system", "current system", "upgrade")):
        label, conf = "modernization_of_existing_system", 70 if strong_history else 60
    elif any(s in text for s in ("prototype", "proof of concept", "pilot")):
        label, conf = "research_prototype", 65
    elif new_hits and not exist_hits and not strong_history:
        label, conf = "new_start", 60 if "sources sought" in ntype or "rfi" in ntype else 55
    elif exist_hits:
        label, conf = "follow_on_development", 50
    else:
        label, conf = "unclear", 30

    caveats = []
    if not links:
        caveats.append("No prior-award evidence loaded; assessment rests on notice language alone.")
    return {
        "work_origin_assessment": label,
        "confidence": conf,
        "confidence_band": band(conf),
        "evidence_from_posting": {"new_start_signals": new_hits, "existing_system_signals": exist_hits},
        "evidence_from_historical_awards": {
            "predecessor_identifier_match": has_predecessor,
            "similar_award_count": sum(1 for ln in links if ln["similarity_score"] >= 40),
        },
        "caveats": caveats,
    }
