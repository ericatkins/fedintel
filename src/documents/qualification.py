"""Qualification analysis: extracted requirements × company profile → gaps.

This is the "should I even bid?" layer. It is deliberately conservative about
the word DISQUALIFIED:

- 'disqualified'  : eligibility you cannot buy your way into for this bid
                    (set-aside status you don't hold). Prime bidding is barred.
- 'blocking'      : a hard gate you could still clear by teaming or subbing
                    (contract vehicle, clearance, facility clearance).
- 'gap'           : a requirement you don't currently meet but can often
                    obtain, sub out, or address in the proposal.
- 'met'           : the profile satisfies it.
- 'unknown'       : the profile doesn't say — asked, never assumed.

Silence in a profile is NEVER treated as capability, and silence in the
documents is never treated as absence of a requirement.
"""
# Ordered low → high; the rank map is DERIVED so no literal clearance name is
# assigned a constant inline (which static analyzers read as a hardcoded
# credential). Holding a higher tier satisfies a lower requirement.
CLEARANCE_ORDER = ("public trust", "confidential", "secret", "top secret", "ts/sci")
CLEARANCE_RANK = {name: rank for rank, name in enumerate(CLEARANCE_ORDER, start=1)}
# Requirements that bar a prime bid outright when unmet.
ELIGIBILITY_TYPES = {"set_aside"}
# Requirements that gate the bid but can be met through a teaming arrangement.
TEAMABLE_TYPES = {"vehicle", "clearance"}
# Requirements that are informational for fit, never blocking on their own.
ADVISORY_TYPES = {"evaluation", "submission", "deliverable", "personnel",
                  "place", "wage", "bonding"}

SET_ASIDE_SYNONYMS = {
    "8(a)": {"8(a)", "8a", "8(a) certified"},
    "HUBZone": {"hubzone"},
    "SDVOSB": {"sdvosb", "service-disabled veteran", "service disabled veteran",
               "vosb"},
    "WOSB": {"wosb", "women-owned", "women owned", "edwosb"},
    "Total Small Business": {"small business", "small", "total small business"},
}


def _profile_list(profile: dict, *keys) -> list[str]:
    values: list[str] = []
    for key in keys:
        raw = (profile or {}).get(key)
        if isinstance(raw, list):
            values += [str(v) for v in raw]
        elif isinstance(raw, str) and raw.strip():
            values += [part.strip() for part in raw.split(",") if part.strip()]
    return [v.strip() for v in values if v.strip()]


def _holds_clearance(profile: dict, required: str) -> bool | None:
    held = _profile_list(profile, "clearances")
    if not held:
        return None                                  # unknown, not "no"
    required_rank = CLEARANCE_RANK.get(required.lower())
    if required_rank is None:
        return any(required.lower() in h.lower() for h in held)
    best = max((CLEARANCE_RANK.get(h.lower().strip(), 0) for h in held),
               default=0)
    return best >= required_rank


def _holds_token(profile: dict, value: str, *keys) -> bool | None:
    held = _profile_list(profile, *keys)
    if not held:
        return None
    target = value.lower()
    for item in held:
        item_lower = item.lower()
        if target in item_lower or item_lower in target:
            return True
    return False


def _eligible_set_aside(profile: dict, value: str) -> bool | None:
    held = _profile_list(profile, "set_aside_eligibility", "certifications")
    if not held:
        return None
    held_lower = " ".join(held).lower()
    synonyms = SET_ASIDE_SYNONYMS.get(value, {value.lower()})
    return any(token in held_lower for token in synonyms)


def assess(requirements: list[dict], profile: dict) -> dict:
    """Returns {verdict, rows, blocking, disqualifying, gaps, unknowns}."""
    rows = []
    for req in requirements or []:
        rtype, value = req["requirement_type"], req["value"]
        if rtype == "clearance":
            holds = _holds_clearance(profile, value)
        elif rtype == "vehicle":
            holds = _holds_token(profile, value, "contract_vehicles")
        elif rtype == "set_aside":
            holds = _eligible_set_aside(profile, value)
        elif rtype == "certification":
            holds = _holds_token(profile, value, "certifications")
        else:
            holds = None
        if holds is True:
            status = "met"
        elif holds is None:
            status = "unknown" if rtype not in ADVISORY_TYPES else "advisory"
        elif rtype in ELIGIBILITY_TYPES:
            status = "disqualified"
        elif rtype in TEAMABLE_TYPES:
            status = "blocking"
        else:
            status = "gap"
        rows.append({**req, "status": status})

    disqualifying = [r for r in rows if r["status"] == "disqualified"]
    blocking = [r for r in rows if r["status"] == "blocking"]
    gaps = [r for r in rows if r["status"] == "gap"]
    unknowns = [r for r in rows if r["status"] == "unknown"]
    if disqualifying:
        verdict = "not eligible to prime"
    elif blocking:
        verdict = "blocked unless teaming"
    elif gaps:
        verdict = "qualified with gaps"
    elif unknowns:
        verdict = "qualified — profile incomplete"
    elif rows:
        verdict = "qualified"
    else:
        verdict = "no requirements extracted"
    return {"verdict": verdict, "rows": rows, "disqualifying": disqualifying,
            "blocking": blocking, "gaps": gaps, "unknowns": unknowns}


SCORE_CAPS = {"not eligible to prime": 15, "blocked unless teaming": 55}


def apply_to_score(score: int, assessment: dict) -> tuple[int, list[str]]:
    """Cap the match score when the bid is barred or gated. Capping (not
    zeroing) keeps the opportunity visible for teaming decisions."""
    cap = SCORE_CAPS.get(assessment.get("verdict", ""))
    if cap is None or score <= cap:
        return score, []
    detail = ", ".join(sorted({r["value"] for r in
                               (assessment["disqualifying"] or assessment["blocking"])}))
    return cap, [f"score capped at {cap}: {assessment['verdict']} ({detail})"]
