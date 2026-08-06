"""Congressional delegation intelligence for an opportunity's place of
performance: who represents it, whether they sit on committees that matter to
the buying agency, how to engage their offices, and what the FEC-reported
funding picture looks like — with Fedintel's evidence discipline throughout.

Confidence tiers for the House match (senators are always state-certain):
- 90 address_geocode : street-level Census geocode
- 60 city_geocode    : city centroid geocode — cities can span districts
-  0 state_only      : district unknown; senators + engagement guidance only
"""
import re
from datetime import date

STATE_CODES = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI", "ID", "IL",
    "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT",
    "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI",
    "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY", "DC", "PR",
    "GU", "VI", "AS", "MP",
}


def parse_place(place_of_performance: str | None) -> dict:
    """'Huntsville, AL' / 'Huntsville, AL 35808' / 'AL' → parts + place_key."""
    text = (place_of_performance or "").strip()
    if not text:
        return {"city": None, "state": None, "zip": None, "place_key": None}
    zip_match = re.search(r"\b(\d{5})(?:-\d{4})?\s*$", text)
    zip_code = zip_match.group(1) if zip_match else None
    if zip_match:
        text = text[:zip_match.start()].strip().rstrip(",")
    parts = [p.strip() for p in text.split(",") if p.strip()]
    state = parts[-1].upper() if parts and parts[-1].upper() in STATE_CODES else None
    city = ", ".join(parts[:-1]) if state and len(parts) > 1 else (
        None if state else text or None)
    key = "|".join(p or "" for p in ((city or "").lower(), state or "", zip_code or ""))
    return {"city": city, "state": state, "zip": zip_code,
            "place_key": key if state else None}


# Buying agency → committees of jurisdiction (authorizers + the appropriations
# subcommittee that funds them). Keys are matched as substrings of the agency
# name; codes are thomas_ids from the committees dataset (4-char = full
# committee; membership rows for subcommittees share the 4-char prefix).
AGENCY_COMMITTEE_MAP: list[tuple[tuple[str, ...], list[dict]]] = [
    (("DEFENSE", "ARMY", "NAVY", "AIR FORCE", "SPACE FORCE", "MARINE", "DARPA",
      "DEFENSE LOGISTICS", "DEFENSE INFORMATION", "MISSILE"), [
        {"code": "HSAS", "why": "authorizes DoD programs (NDAA)"},
        {"code": "SSAS", "why": "authorizes DoD programs (NDAA)"},
        {"code": "HSAP", "why": "appropriates DoD funding (Defense subcommittee)"},
        {"code": "SSAP", "why": "appropriates DoD funding (Defense subcommittee)"},
    ]),
    (("VETERANS",), [
        {"code": "HSVR", "why": "authorizes VA programs"},
        {"code": "SSVA", "why": "authorizes VA programs"},
        {"code": "HSAP", "why": "appropriates VA funding (MilCon-VA subcommittee)"},
        {"code": "SSAP", "why": "appropriates VA funding (MilCon-VA subcommittee)"},
    ]),
    (("HOMELAND", "FEMA", "CUSTOMS", "TSA", "COAST GUARD", "SECRET SERVICE",
      "CISA", "IMMIGRATION"), [
        {"code": "HSHM", "why": "authorizes DHS programs"},
        {"code": "SSGA", "why": "DHS oversight (HSGAC)"},
        {"code": "HSAP", "why": "appropriates DHS funding (Homeland subcommittee)"},
        {"code": "SSAP", "why": "appropriates DHS funding (Homeland subcommittee)"},
    ]),
    (("HEALTH AND HUMAN", "NATIONAL INSTITUTES", "CENTERS FOR DISEASE",
      "CENTERS FOR MEDICARE", "FOOD AND DRUG"), [
        {"code": "HSIF", "why": "health authorization (Energy & Commerce)"},
        {"code": "SSHR", "why": "health authorization (HELP)"},
        {"code": "HSAP", "why": "appropriates HHS funding (Labor-HHS subcommittee)"},
        {"code": "SSAP", "why": "appropriates HHS funding (Labor-HHS subcommittee)"},
    ]),
    (("ENERGY",), [
        {"code": "HSIF", "why": "energy authorization (Energy & Commerce)"},
        {"code": "SSEG", "why": "energy authorization (Energy & Natural Resources)"},
        {"code": "HSAP", "why": "appropriates DOE funding (Energy-Water subcommittee)"},
        {"code": "SSAP", "why": "appropriates DOE funding (Energy-Water subcommittee)"},
    ]),
    (("NASA", "AERONAUTICS AND SPACE",), [
        {"code": "HSSY", "why": "authorizes NASA (Science, Space & Technology)"},
        {"code": "SSCM", "why": "authorizes NASA (Commerce, Science & Transportation)"},
        {"code": "HSAP", "why": "appropriates NASA funding (CJS subcommittee)"},
        {"code": "SSAP", "why": "appropriates NASA funding (CJS subcommittee)"},
    ]),
    (("TRANSPORTATION", "FEDERAL AVIATION", "HIGHWAY", "RAILROAD", "MARITIME"), [
        {"code": "HSPW", "why": "authorizes DOT programs (T&I)"},
        {"code": "SSCM", "why": "authorizes DOT programs (Commerce)"},
        {"code": "HSAP", "why": "appropriates DOT funding (THUD subcommittee)"},
        {"code": "SSAP", "why": "appropriates DOT funding (THUD subcommittee)"},
    ]),
    (("JUSTICE", "FEDERAL BUREAU OF INVESTIGATION", "DRUG ENFORCEMENT",
      "PRISONS", "MARSHALS"), [
        {"code": "HSJU", "why": "authorizes DOJ programs"},
        {"code": "SSJU", "why": "authorizes DOJ programs"},
        {"code": "HSAP", "why": "appropriates DOJ funding (CJS subcommittee)"},
        {"code": "SSAP", "why": "appropriates DOJ funding (CJS subcommittee)"},
    ]),
    (("AGRICULTURE", "FOREST SERVICE"), [
        {"code": "HSAG", "why": "authorizes USDA programs"},
        {"code": "SSAF", "why": "authorizes USDA programs"},
        {"code": "HSAP", "why": "appropriates USDA funding (Agriculture subcommittee)"},
        {"code": "SSAP", "why": "appropriates USDA funding (Agriculture subcommittee)"},
    ]),
    (("GENERAL SERVICES", "OFFICE OF PERSONNEL"), [
        {"code": "HSGO", "why": "GSA oversight (Oversight & Accountability)"},
        {"code": "SSGA", "why": "GSA oversight (HSGAC)"},
        {"code": "HSAP", "why": "appropriates GSA funding (FSGG subcommittee)"},
        {"code": "SSAP", "why": "appropriates GSA funding (FSGG subcommittee)"},
    ]),
    (("COMMERCE", "NIST", "NOAA", "CENSUS", "PATENT"), [
        {"code": "HSSY", "why": "science authorization (SST)"},
        {"code": "SSCM", "why": "authorizes Commerce programs"},
        {"code": "HSAP", "why": "appropriates Commerce funding (CJS subcommittee)"},
        {"code": "SSAP", "why": "appropriates Commerce funding (CJS subcommittee)"},
    ]),
    (("INTERIOR", "ENVIRONMENTAL PROTECTION", "GEOLOGICAL"), [
        {"code": "HSII", "why": "authorizes Interior programs (Natural Resources)"},
        {"code": "SSEV", "why": "EPA authorization (EPW)"},
        {"code": "HSAP", "why": "appropriates Interior/EPA funding"},
        {"code": "SSAP", "why": "appropriates Interior/EPA funding"},
    ]),
]

_ALWAYS_RELEVANT = [
    {"code": "HSSM", "why": "House Small Business — contracting goals & set-aside oversight"},
    {"code": "SSSB", "why": "Senate Small Business — contracting goals & set-aside oversight"},
]


def committee_relevance(agency: str | None,
                        member_committees: list[dict]) -> list[dict]:
    """Which of THIS member's assignments matter for THIS buying agency."""
    agency_upper = (agency or "").upper()
    wanted: dict[str, str] = {}
    for keys, committees in AGENCY_COMMITTEE_MAP:
        if any(k in agency_upper for k in keys):
            for c in committees:
                wanted.setdefault(c["code"], c["why"])
            break
    for c in _ALWAYS_RELEVANT:
        wanted.setdefault(c["code"], c["why"])
    by_parent: dict[str, dict] = {}
    sub_counts: dict[str, int] = {}
    for assignment in member_committees or []:
        code = assignment.get("code") or ""
        parent = code[:4]
        if parent not in wanted:
            continue
        if len(code) > 4:
            sub_counts[parent] = sub_counts.get(parent, 0) + 1
        current = by_parent.get(parent)
        if current is None or (len(code) == 4 and len(current["code"]) > 4):
            by_parent[parent] = {"code": code,
                                 "name": assignment.get("name"),
                                 "title": assignment.get("title"),
                                 "why": wanted[parent]}
    hits = []
    for parent, hit in by_parent.items():
        subs = sub_counts.get(parent, 0)
        if subs:
            hit = dict(hit, why=f"{hit['why']}; sits on {subs} subcommittee(s)")
            hit["name"] = (hit["name"] or "").split(" (subcommittee")[0]
        hits.append(hit)
    return sorted(hits, key=lambda h: h["code"])


# Standard congressional-office roles worth asking for by function — guidance,
# not data. Named staff only ever come from imported, sourced records.
STAFF_ROLE_PLAYBOOK = [
    {"role_tag": "military_la",
     "ask_for": "Military Legislative Assistant (MLA)",
     "when": "DoD programs, NDAA provisions, base/installation work"},
    {"role_tag": "approps",
     "ask_for": "Appropriations LA (or clerk, if the member sits on Approps)",
     "when": "program funding levels, Community Project Funding requests"},
    {"role_tag": "district_director",
     "ask_for": "District/State Director",
     "when": "local jobs impact, site visits, in-district announcements"},
    {"role_tag": "grants",
     "ask_for": "Grants & Federal Projects Coordinator",
     "when": "letters of support, agency inquiry assistance"},
    {"role_tag": "scheduler",
     "ask_for": "Scheduler / Director of Operations",
     "when": "requesting the member or chief of staff's time"},
]

COMPLIANCE_NOTE = (
    "Engagement guardrails: congressional offices may make status inquiries and "
    "write support letters, but may not direct an award. During an active "
    "solicitation, route questions ONLY through the contracting officer — "
    "procurement-integrity rules (FAR 3.104) restrict back-channel contact and "
    "agencies log congressional inquiries. Campaign contributions are a "
    "separate, regulated activity; never link them to procurement outcomes. "
    "Funding figures shown are public FEC aggregates of individual "
    "contributions by reported employer, plus PAC receipts — corporations "
    "cannot contribute to federal candidates."
)


def engagement_windows(today: date | None = None) -> list[dict]:
    """Legislative-calendar tie-ins that affect capture timing."""
    today = today or date.today()
    fy = today.year + (1 if today.month >= 10 else 0)
    windows = [
        {"window": f"FY{fy + 1} appropriations & Community Project Funding",
         "timing": "member request deadlines typically March–April",
         "use": "program-level funding advocacy and CPF (earmark) requests for "
                "eligible entities"},
        {"window": f"FY{fy + 1} NDAA cycle",
         "timing": "member proposals typically due spring; markup early summer",
         "use": "defense program authorizations, pilot-program language, "
                "small-business contracting provisions"},
        {"window": "Federal Q4 (July–September)",
         "timing": f"FY{fy} year-end obligation push",
         "use": "agencies obligate remaining funds; delegation awareness helps "
                "post-award announcements"},
    ]
    if today.month >= 10 or today.month <= 3:
        windows.append(
            {"window": "Continuing-resolution risk",
             "timing": "start of the fiscal year until full-year appropriations",
             "use": "new starts often frozen under a CR — weigh in funding "
                    "context; delegation offices track passage timing"})
    return windows


def resolve_confidence(method: str) -> int:
    return {"address_geocode": 90, "city_geocode": 60, "state_only": 0}.get(method, 0)


def format_funding_label(kind: str) -> str:
    return {"employer_aggregate":
                "individual contributions aggregated by reported employer (FEC)",
            "pac": "PAC/committee receipts (FEC)"}.get(kind, kind)
