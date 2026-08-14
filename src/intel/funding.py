"""Funding context with strict truthfulness labels.

Labels (exclusive, in priority order):
- direct_funding_link:     award funding data explicitly maps to an account
- likely_related_account:  inferred from agency/category/prior awards
- agency_level_context:    only broad agency budget info exists
- no_public_funding_context

Never implies a solicitation is funded because the agency requested budget
authority. 'Budget-aligned' != 'funded'.
"""
from collections import Counter

from .confidence import band

LABELS = {
    "direct": "Direct funding link found",
    "likely": "Likely related funding account",
    "agency": "Agency-level budget context",
    "none": "No public funding context found",
}


def build_funding_context(opp: dict, linked_awards: list[dict],
                          accounts: list[dict], budget_rows: list[dict]) -> dict:
    """accounts: funding_accounts rows attributable to linked awards (explicit
    federal-account mapping from spending data). budget_rows: agency/account
    level budgetary resources / President's Budget rows for the opportunity's
    agency."""
    caveats = [
        "Budget data is agency/account-level and does not prove funding for this specific opportunity.",
        "USAspending and SAM.gov may differ due to timing, updates, or reporting corrections.",
    ]

    if accounts:
        conf = 80
        return _ctx("direct", conf, opp, accounts, budget_rows, linked_awards, caveats + [
            "Direct link reflects funding of PRIOR related awards, not this solicitation itself."])

    # Infer likely accounts from funding agencies on similar prior awards
    funding_agencies = Counter(
        ln["award"].get("funding_subtier") or ln["award"].get("funding_department")
        for ln in linked_awards
        if ln["award"].get("funding_subtier") or ln["award"].get("funding_department")
    )
    if funding_agencies:
        conf = 42
        return _ctx("likely", conf, opp, [], budget_rows, linked_awards, caveats + [
            "Inferred from agency and prior awards only."],
            likely_funding_agency=funding_agencies.most_common(1)[0][0])

    if budget_rows:
        conf = 30
        return _ctx("agency", conf, opp, [], budget_rows, linked_awards, caveats)

    return _ctx("none", 10, opp, [], [], linked_awards,
                ["No public funding context found for this agency/category in loaded data."])


def build_funding_ladder(budget_rows: list[dict]) -> dict | None:
    """Per-fiscal-year ladder over cached account rows, using the disciplined
    money-stage vocabulary: REQUESTED (President's Budget) is not AVAILABLE
    (budgetary resources), and available is not OBLIGATED. Each stage appears
    only when the data for it exists; nothing is interpolated."""
    if not budget_rows:
        return None
    by_fy: dict[int, dict] = {}
    for row in budget_rows:
        fy = row.get("fiscal_year")
        if not fy:
            continue
        agg = by_fy.setdefault(int(fy), {"fiscal_year": int(fy),
                                         "requested": 0.0, "available": 0.0,
                                         "obligated": 0.0})
        agg["requested"] += float(row.get("president_budget_amount") or 0)
        agg["available"] += float(row.get("budgetary_resources") or 0)
        agg["obligated"] += float(row.get("obligations") or 0)
    if not by_fy:
        return None
    rows = [by_fy[fy] for fy in sorted(by_fy)]
    for i, r in enumerate(rows):
        r["obligation_rate_pct"] = (round(100 * r["obligated"] / r["available"])
                                    if r["available"] else None)
        prev = rows[i - 1] if i else None
        r["yoy_available_pct"] = (
            round(100 * (r["available"] - prev["available"]) / prev["available"])
            if prev and prev["available"] and r["available"] else None)

    notes = []
    latest = rows[-1]
    if latest["yoy_available_pct"] is not None and \
            abs(latest["yoy_available_pct"]) >= 10:
        direction = "increased" if latest["yoy_available_pct"] > 0 else "decreased"
        notes.append(f"Budgetary resources {direction} "
                     f"{abs(latest['yoy_available_pct'])}% from the prior "
                     f"fiscal year (FY{latest['fiscal_year']}).")
    if latest["obligation_rate_pct"] is not None:
        if latest["obligation_rate_pct"] >= 50:
            notes.append(f"FY{latest['fiscal_year']} obligations are "
                         f"{latest['obligation_rate_pct']}% of available "
                         "resources — active execution at the account level.")
        else:
            notes.append(f"FY{latest['fiscal_year']} obligations are only "
                         f"{latest['obligation_rate_pct']}% of available "
                         "resources so far.")
    if any(r["requested"] for r in rows):
        notes.append("'Requested' is President's Budget material — a request "
                     "is not an appropriation.")
    return {
        "rows": [{k: v for k, v in r.items()} for r in rows[-6:]],
        "notes": notes,
        "caveats": ["Ladder is account/agency-level from cached USAspending "
                    "data; it never proves this specific opportunity is "
                    "funded. Appropriations bill status and apportionments "
                    "are not yet ingested."],
    }


def _ctx(kind, conf, opp, accounts, budget_rows, linked_awards, caveats, likely_funding_agency=None):
    prior_obligations = round(sum(
        float(ln["award"].get("obligated_amount") or 0) for ln in linked_awards), 2)
    return {
        "label": LABELS[kind],
        "label_key": kind,
        "confidence": conf,
        "confidence_band": band(conf),
        "likely_funding_agency": likely_funding_agency or opp.get("agency"),
        "possible_federal_accounts": [
            {"code": a.get("federal_account_code"), "name": a.get("federal_account_name"),
             "fiscal_year": a.get("fiscal_year")} for a in accounts[:5]
        ],
        "agency_budgetary_resources": [
            {"fiscal_year": b.get("fiscal_year"),
             "budgetary_resources": b.get("budgetary_resources"),
             "obligations": b.get("obligations"),
             "source": b.get("source")} for b in budget_rows[:6]
        ],
        "prior_obligations_similar_work": prior_obligations,
        "presidents_budget_language": [
            b.get("program_language") for b in budget_rows
            if b.get("source") == "omb_budget" and b.get("program_language")
        ][:3],
        "ladder": build_funding_ladder(budget_rows),
        "caveats": caveats,
    }
