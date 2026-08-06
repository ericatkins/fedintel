"""Opportunity-to-award linking with the spec's similarity model.

Every link carries a similarity_score (0-100), a link_type, and evidence.
Deterministic; the semantic terms use token cosine (similarity.py) and can be
swapped for embeddings without changing this scoring frame.
"""
from datetime import date

from .offices import office_key
from .similarity import cosine, solnum_family

WEIGHTS = {
    "same_office": 25,
    "same_subtier": 10,
    "same_naics": 15,
    "same_psc": 15,
    "title_semantic": 15,       # scaled by cosine
    "description_semantic": 15, # scaled by cosine
    "same_pop": 5,
    "solnum_family": 15,
    "same_vehicle": 10,
    "recent_5y": 10,
    "older_10y": -10,
}
_MAX_RAW = sum(v for v in WEIGHTS.values() if v > 0)  # normalize to 100


def score_link(opp: dict, award: dict, opp_office: dict, today: date | None = None) -> dict:
    """Return {'similarity_score', 'link_type', 'evidence': [..]}."""
    today = today or date.today()
    ev, raw = [], 0.0

    ok, _, _ = office_key(opp_office)
    ak, _, _ = office_key({
        "organization_code": award.get("awarding_office_code"),
        "office_name": award.get("awarding_office"),
        "subtier_name": award.get("awarding_subtier"),
        "department_name": award.get("awarding_department"),
    })
    same_office = ok != "unknown" and ok == ak
    if same_office:
        raw += WEIGHTS["same_office"]
        ev.append("same buying office")
    elif (opp_office.get("subtier_name") and award.get("awarding_subtier")
          and opp_office["subtier_name"].strip().upper() == award["awarding_subtier"].strip().upper()):
        raw += WEIGHTS["same_subtier"]
        ev.append("same subtier agency")

    if opp.get("naics") and opp.get("naics") == award.get("naics"):
        raw += WEIGHTS["same_naics"]
        ev.append(f"same NAICS {opp['naics']}")
    if opp.get("psc") and opp.get("psc") == award.get("psc"):
        raw += WEIGHTS["same_psc"]
        ev.append(f"same PSC {opp['psc']}")

    t = cosine(opp.get("title"), award.get("award_title"))
    if t >= 0.25:
        raw += WEIGHTS["title_semantic"] * t
        ev.append(f"title similarity {round(t * 100)}%")
    d = cosine(opp.get("description_text"), award.get("award_description"))
    if d >= 0.25:
        raw += WEIGHTS["description_semantic"] * d
        ev.append(f"description similarity {round(d * 100)}%")

    opp_pop = (opp.get("place_of_performance") or "").strip().upper()
    aw_pop = ""
    pj = award.get("place_of_performance_json") or {}
    if isinstance(pj, dict):
        aw_pop = ", ".join(p for p in (pj.get("city"), pj.get("state")) if p).upper()
    if opp_pop and opp_pop == aw_pop:
        raw += WEIGHTS["same_pop"]
        ev.append("same place of performance")

    solnum_match = solnum_family(opp.get("solicitation_number"), award.get("solicitation_number"))
    if solnum_match:
        raw += WEIGHTS["solnum_family"]
        ev.append("same solicitation number family")

    if opp.get("contract_vehicle") and opp.get("contract_vehicle") == award.get("contract_vehicle"):
        raw += WEIGHTS["same_vehicle"]
        ev.append("same contract vehicle")

    yrs = _age_years(award, today)
    if yrs is not None and yrs <= 5:
        raw += WEIGHTS["recent_5y"]
        ev.append("awarded within 5 years")
    elif yrs is not None and yrs > 10:
        raw += WEIGHTS["older_10y"]
        ev.append("older than 10 years (penalized)")

    score = max(0, min(100, round(100 * raw / _MAX_RAW)))
    return {"similarity_score": score, "link_type": _link_type(solnum_match, same_office, opp, award, t),
            "evidence": ev}


def _link_type(solnum_match: bool, same_office: bool, opp: dict, award: dict, title_sim: float) -> str:
    if solnum_match:
        return "same_solicitation"
    if opp.get("piid") and opp.get("piid") == award.get("piid"):
        return "same_contract"
    if same_office and opp.get("naics") and opp.get("naics") == award.get("naics"):
        return "same_office_same_naics"
    if same_office and opp.get("psc") and opp.get("psc") == award.get("psc"):
        return "same_office_same_psc"
    if title_sim >= 0.5:
        return "similar_scope"
    return "similar_scope"


def _age_years(award: dict, today: date):
    d = award.get("award_date")
    if not d:
        return None
    try:
        y = int(str(d)[:4])
    except ValueError:
        return None
    return today.year - y


def link_awards(opp: dict, opp_office: dict, awards: list[dict],
                min_score: int = 20, today: date | None = None) -> list[dict]:
    """Score every candidate award; return links sorted by similarity."""
    links = []
    for a in awards:
        res = score_link(opp, a, opp_office, today=today)
        if res["similarity_score"] >= min_score:
            links.append({**res, "award": a})
    links.sort(key=lambda x: x["similarity_score"], reverse=True)
    return links


def last_10_relevant(links: list[dict]) -> list[dict]:
    """Spec selection: relevance-ranked (not merely most recent), tiered by
    (1) same office + NAICS/PSC, (2) same office + similar scope,
    (3) same subtier + NAICS/PSC, (4) department-level highly similar."""
    def tier(link):
        lt, ev = link["link_type"], " ".join(link["evidence"])
        if lt in ("same_solicitation", "same_contract"):
            return 0
        if lt in ("same_office_same_naics", "same_office_same_psc"):
            return 1
        if "same buying office" in ev:
            return 2
        if "same subtier" in ev and ("NAICS" in ev or "PSC" in ev):
            return 3
        return 4
    ranked = sorted(links, key=lambda x: (tier(x), -x["similarity_score"],
                                          str(x["award"].get("award_date") or "")), )
    return ranked[:10]
