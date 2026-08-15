"""Grant applicant-type eligibility: deterministic, conservative, grants-only.

This is the first slice of grant readiness — it answers exactly one question
("does the NOFO's eligible-applicant list include organizations like yours?")
and refuses to answer anything it can't. Verdicts:

- likely_eligible   : your applicant type (or 'unrestricted') appears in the
                      grant's eligible-applicant list
- not_listed        : the list exists and your type is not in it — this is
                      NOT a certainty; eligibility text is nuanced, read the
                      NOFO
- unknown           : your profile doesn't state an applicant type, or the
                      grant record carries no eligibility list

Never reuses contract set-aside logic.
"""
APPLICANT_TYPES = ("small business", "other business", "nonprofit",
                   "university", "state government", "local government",
                   "tribal", "individual")

_SYNONYMS = {
    "small business": ("small business", "for-profit", "for profit",
                       "businesses"),
    "other business": ("for-profit", "for profit", "businesses",
                       "organizations other than"),
    "nonprofit": ("nonprofit", "non-profit"),
    "university": ("higher education", "university", "universities",
                   "colleges"),
    "state government": ("state government", "state controlled", "states"),
    "local government": ("local government", "county", "city or township",
                         "local governments"),
    "tribal": ("tribal", "native american", "tribes"),
    "individual": ("individual",),
}


def assess_grant_eligibility(grant: dict, applicant_type: str | None) -> dict:
    caveats = ["Eligibility text in NOFOs is nuanced (partnerships, "
               "fiscal sponsors, program-specific rules) — always read the "
               "notice before ruling yourself in or out."]
    elig = [str(e).lower() for e in (grant.get("eligible_applicants") or [])
            if e]
    if not applicant_type:
        return {"verdict": "unknown",
                "why": "Your profile doesn't state an applicant type yet.",
                "caveats": caveats}
    if not elig:
        return {"verdict": "unknown",
                "why": "No eligible-applicant list loaded for this grant.",
                "caveats": caveats}
    joined = " ".join(elig)
    if "unrestricted" in joined or "anyone" in joined:
        return {"verdict": "likely_eligible",
                "why": "The grant lists unrestricted eligibility.",
                "caveats": caveats}
    tokens = _SYNONYMS.get(applicant_type.lower(), (applicant_type.lower(),))
    matched = [t for t in tokens if t in joined]
    if matched:
        note = None
        if grant.get("cost_sharing") is True:
            note = ("Cost sharing is required — confirm your organization "
                    "can commit matching resources.")
        return {"verdict": "likely_eligible",
                "why": f"The eligible-applicant list includes "
                       f"'{matched[0]}'.",
                "cost_share_note": note,
                "caveats": caveats}
    return {"verdict": "not_listed",
            "why": f"'{applicant_type}' does not appear in the eligible-"
                   "applicant list "
                   f"({'; '.join(elig[:3])}{'…' if len(elig) > 3 else ''}).",
            "caveats": caveats}
