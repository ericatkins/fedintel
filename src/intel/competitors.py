"""Competitive and teaming intelligence from public award records.

Ranks likely competitors from actual buyer history (not "every vendor in the
NAICS") and surfaces teaming candidates with the gap each one fills. Every
row carries its evidence; the disclosed limitation is that public prime-award
data does not show subcontract relationships or vehicle holdings, so outputs
are candidates, never confirmed relationships.

Pure function over already-linked records. No fetching.
"""
from datetime import date

MAX_COMPETITORS = 8
MAX_PARTNERS = 5


def _year(value) -> int | None:
    text = str(value or "")[:4]
    return int(text) if text.isdigit() else None


def _aggregate(awards: list[dict]) -> dict[str, dict]:
    vendors: dict[str, dict] = {}
    for a in awards:
        name = a.get("recipient_name")
        if not name:
            continue
        v = vendors.setdefault(name, {
            "vendor": name, "award_count": 0, "obligations": 0.0,
            "last_award_date": "", "set_aside_awards": 0, "amounts": []})
        v["award_count"] += 1
        amt = float(a.get("obligated_amount") or 0)
        v["obligations"] += amt
        if amt:
            v["amounts"].append(amt)
        d = str(a.get("award_date") or "")
        if d > v["last_award_date"]:
            v["last_award_date"] = d
        sa = str(a.get("set_aside") or "").lower()
        if sa and "none" not in sa:
            v["set_aside_awards"] += 1
    return vendors


def build_competitive_teaming(opp: dict, awards: list[dict],
                              incumbent: dict | None,
                              today: date | None = None) -> dict:
    today = today or date.today()
    caveats = [
        "Built from public prime-award records at this buyer. Subcontract "
        "relationships and vehicle holdings are not comprehensively public — "
        "treat rows as candidates, not confirmed relationships.",
        "Small-business standing is inferred from set-aside award history, "
        "not SBA certification data.",
    ]
    if not awards:
        return {"status": "insufficient_data", "competitors": [],
                "teaming_candidates": [],
                "caveats": caveats + ["No award history loaded for this "
                                      "buyer/category."]}

    vendors = _aggregate(awards)
    inc_name = (incumbent or {}).get("likely_incumbent_name")
    recent_cut = today.year - 3
    med_amounts = sorted(x for v in vendors.values() for x in v["amounts"])
    market_median = med_amounts[len(med_amounts) // 2] if med_amounts else 0
    opp_set_aside = bool((opp.get("set_aside") or "").strip())

    def strength(v):
        s = min(40, v["award_count"] * 12)
        ly = _year(v["last_award_date"])
        if ly and ly >= recent_cut:
            s += 25
        if v["vendor"] == inc_name:
            s += 25
        s += min(10, int(v["obligations"] / 1e6))
        return min(100, s)

    ranked = sorted(vendors.values(), key=lambda v: -strength(v))
    competitors, partners = [], []
    for v in ranked:
        ly = _year(v["last_award_date"])
        recent = bool(ly and ly >= recent_cut)
        sa_share = (v["set_aside_awards"] / v["award_count"]
                    if v["award_count"] else 0)
        evidence = [f"{v['award_count']} award(s) at this buyer, "
                    f"${v['obligations']:,.0f} total, most recent "
                    f"{v['last_award_date'] or 'unknown'}"]
        if v["vendor"] == inc_name:
            read = ("incumbent — the vendor to beat or to team with; see the "
                    "incumbent analysis for confidence and caveats")
        elif v["award_count"] >= 2 and recent:
            read = "repeat performer at this buyer — likely competitor"
        elif recent:
            read = "recent performer at this buyer — possible competitor"
        else:
            read = ("historical performer only — weaker competitive signal "
                    "(no recent award in loaded data)")
        if opp_set_aside and v["award_count"] >= 2 and sa_share < 0.25:
            evidence.append(
                f"only {round(sa_share * 100)}% of their awards here were "
                "set-aside — they may be other-than-small")
            partner_reason = ("If other-than-small, they cannot prime this "
                              "set-aside: a displaced incumbent or large "
                              "performer is often the strongest subcontractor "
                              "or mentor-protégé partner available.")
            partners.append({"vendor": v["vendor"],
                             "gap_filled": "scale, incumbency knowledge, or "
                                           "customer reachback",
                             "evidence": evidence + [partner_reason]})
        avg = (v["obligations"] / v["award_count"]) if v["award_count"] else 0
        if market_median and avg and avg < market_median * 0.3 and sa_share >= 0.5:
            partners.append({"vendor": v["vendor"],
                             "gap_filled": "set-aside eligibility with proven "
                                           "buyer access (potential prime or "
                                           "co-bid partner)",
                             "evidence": evidence})
        competitors.append({"vendor": v["vendor"],
                            "strength": strength(v),
                            "is_incumbent": v["vendor"] == inc_name,
                            "evidence": evidence, "read": read})

    seen: set[str] = set()
    unique_partners = []
    for p in partners:
        if p["vendor"] not in seen:
            seen.add(p["vendor"])
            unique_partners.append(p)
    return {
        "status": "ok",
        "competitors": competitors[:MAX_COMPETITORS],
        "teaming_candidates": unique_partners[:MAX_PARTNERS],
        "vendor_count": len(vendors),
        "caveats": caveats,
    }
