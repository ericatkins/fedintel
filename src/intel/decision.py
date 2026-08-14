"""Capture Decision Stack: the decomposed, explainable decision model.

Replaces reliance on one merged match score with ten separately-assessed
dimensions, each carrying its own rating, evidence, confidence, unknowns,
materiality, and mitigation. The summary recommendation is derived from the
dimensions by ordered deterministic rules — never from an opaque blend.

Pure function over already-stored records (dossier, qualification, profile,
company projects). Per-organization judgment, computed at read time, so it is
never cached across tenants.

Ratings: strong | moderate | weak | blocked | unknown.
'unknown' is visually and semantically distinct from 'weak': silence in a
profile or missing enrichment is never treated as a negative finding.
"""
from .confidence import band

RECOMMENDATIONS = {
    "pursue_prime": "Pursue as prime",
    "pursue_prime_with_partner": "Pursue as prime with partner",
    "pursue_subcontract": "Pursue as subcontractor",
    "shape": "Shape before pursuing",
    "track": "Track for future action",
    "conditional": "Pursue only if a named condition changes",
    "no_bid": "No-bid",
    "insufficient_evidence": "Insufficient evidence",
}

EARLY_STAGES = ("sources sought", "rfi", "request for information",
                "presolicitation", "pre-solicitation", "special notice")

_RATING_RANK = {"blocked": 0, "weak": 1, "unknown": 2, "moderate": 3, "strong": 4}


def _dim(key, name, rating, evidence, confidence, materiality,
         unknowns=None, mitigation=None, score=None):
    return {
        "key": key,
        "name": name,
        "rating": rating,
        "score": score,
        "evidence": [e for e in evidence if e],
        "confidence": max(0, min(100, confidence)),
        "confidence_band": band(confidence),
        "unknowns": unknowns or [],
        "materiality": materiality,
        "mitigation": mitigation,
    }


def _eligibility(qualification):
    if not qualification or qualification.get("verdict") == "no requirements extracted":
        return _dim("eligibility", "Eligibility", "unknown",
                    ["No document requirements extracted yet — eligibility cannot "
                     "be judged from the notice metadata alone."],
                    30, "gate",
                    unknowns=["set-aside, vehicle, and clearance requirements"],
                    mitigation="Read the solicitation documents; extraction may "
                               "still be pending.")
    verdict = qualification["verdict"]
    if qualification.get("disqualifying"):
        vals = sorted({r["value"] for r in qualification["disqualifying"]})
        return _dim("eligibility", "Eligibility", "blocked",
                    [f"Set-aside eligibility not held: {', '.join(vals)} "
                     "(from solicitation documents)"],
                    85, "gate",
                    mitigation="Prime bidding is barred; subcontracting to an "
                               "eligible prime remains possible.")
    if qualification.get("blocking"):
        vals = sorted({r["value"] for r in qualification["blocking"]})
        return _dim("eligibility", "Eligibility", "weak",
                    [f"Gated requirement(s) not held: {', '.join(vals)}"],
                    75, "gate",
                    mitigation="Clearable by teaming with a vehicle/clearance "
                               "holder.")
    if verdict == "qualified — profile incomplete" or qualification.get("unknowns"):
        n = len(qualification.get("unknowns", []))
        return _dim("eligibility", "Eligibility", "unknown",
                    [f"{n} extracted requirement(s) cannot be judged because the "
                     "company profile does not list vehicles, clearances, or "
                     "certifications."],
                    40, "gate",
                    unknowns=[r["value"] for r in qualification.get("unknowns", [])[:5]],
                    mitigation="Complete the company profile qualification fields.")
    if verdict in ("qualified", "qualified with gaps"):
        gaps = qualification.get("gaps", [])
        ev = ["Profile satisfies every extracted eligibility requirement."]
        if gaps:
            ev.append(f"{len(gaps)} non-gating gap(s) remain: "
                      + ", ".join(sorted({g['value'] for g in gaps})[:4]))
        return _dim("eligibility", "Eligibility",
                    "strong" if not gaps else "moderate", ev, 80, "gate")
    return _dim("eligibility", "Eligibility", "unknown", [verdict], 30, "gate")


def _capability_fit(match, opp):
    score = match.get("score")
    reasons = list(match.get("reasons") or [])[:4]
    if score is None:
        return _dim("capability_fit", "Capability fit", "unknown",
                    ["No per-organization match computed yet."], 20, "high",
                    unknowns=["profile-to-requirement fit"],
                    mitigation="Save a company profile to trigger rescoring.")
    if score >= 75:
        rating = "strong"
    elif score >= 55:
        rating = "moderate"
    else:
        rating = "weak"
    ev = [f"Deterministic match score {score}/100 against your profile"] + reasons
    return _dim("capability_fit", "Capability fit", rating, ev,
                70, "high", score=score,
                mitigation=None if rating != "weak" else
                "Low keyword/NAICS overlap — verify against the actual PWS "
                "before dismissing.")


def _past_performance(projects, opp):
    if not projects:
        return _dim("past_performance", "Past performance", "unknown",
                    ["No past projects recorded in your evidence library."],
                    20, "high",
                    unknowns=["deliverable history relevant to this requirement"],
                    mitigation="Add past projects (customer, value, scope, dates) "
                               "on the profile page to enable proof mapping.")
    naics = (opp.get("naics") or "")[:4]
    agency = (opp.get("agency") or "").lower()
    same_naics = [p for p in projects if (p.get("naics") or "")[:4] == naics and naics]
    same_agency = [p for p in projects
                   if agency and agency in (p.get("customer_agency") or "").lower()]
    ev, rating = [], "weak"
    if same_agency and same_naics:
        rating = "strong"
    elif same_agency or same_naics:
        rating = "moderate"
    if same_naics:
        ev.append(f"{len(same_naics)} recorded project(s) in NAICS {naics}xx")
    if same_agency:
        ev.append(f"{len(same_agency)} recorded project(s) for {opp.get('agency')}")
    if not ev:
        ev.append(f"{len(projects)} project(s) recorded, but none matches this "
                  "NAICS or agency")
    return _dim("past_performance", "Past performance", rating, ev, 60, "high",
                mitigation=None if rating != "weak" else
                "Consider teaming with a partner holding directly relevant past "
                "performance.")


def _buyer_position(projects, dossier, opp):
    agency = (opp.get("agency") or "").lower()
    office = (opp.get("office") or "").lower()
    ev, unknowns = [], []
    if projects:
        office_hits = [p for p in projects
                       if office and office in (p.get("customer_office") or "").lower()]
        agency_hits = [p for p in projects
                       if agency and agency in (p.get("customer_agency") or "").lower()]
        if office_hits:
            return _dim("buyer_position", "Buyer position", "strong",
                        [f"{len(office_hits)} recorded project(s) with this buying "
                         "office"], 75, "medium")
        if agency_hits:
            return _dim("buyer_position", "Buyer position", "moderate",
                        [f"{len(agency_hits)} recorded project(s) at {opp.get('agency')}"
                         " (different office)"], 65, "medium")
        ev.append("No recorded work with this agency in your evidence library.")
        return _dim("buyer_position", "Buyer position", "weak", ev, 55, "medium",
                    mitigation="A customer-access teaming partner can substitute "
                               "for direct familiarity.")
    unknowns.append("your history with this buyer")
    return _dim("buyer_position", "Buyer position", "unknown",
                ["No past projects recorded — buyer familiarity cannot be "
                 "assessed."], 20, "medium",
                unknowns=unknowns,
                mitigation="Record past projects to assess customer familiarity.")


def _incumbent_position(incumbent, forecasts=None):
    status = (incumbent or {}).get("incumbent_status", "insufficient_data")
    name = (incumbent or {}).get("likely_incumbent_name")
    conf = (incumbent or {}).get("incumbent_confidence", 0)
    ev = list((incumbent or {}).get("supporting_evidence", []))[:3]
    stated = next((f for f in forecasts or [] if f.get("incumbent_name")), None)
    if stated:
        f_name = stated["incumbent_name"]
        forecast_ev = (f"The agency's own procurement forecast names {f_name} "
                       "as the incumbent (primary source)")
        if name and f_name.lower() != name.lower():
            ev.append(forecast_ev + f" — CONFLICTS with the award-history "
                      f"read ({name}); verify before acting on either")
        elif name:
            ev.append(forecast_ev + " — corroborates the award-history read")
            conf = min(95, conf + 10)
        else:
            return _dim("incumbent_position", "Incumbent position", "weak",
                        [forecast_ev,
                         "Award history alone could not identify an incumbent "
                         "— the forecast is the only source."],
                        70, "high",
                        mitigation="Verify the forecast-stated incumbent's "
                                   "current contract before building a "
                                   "displacement strategy.")
    if status == "confirmed_incumbent":
        return _dim("incumbent_position", "Incumbent position", "weak",
                    [f"Confirmed incumbent {name} ({conf}/100)"] + ev, conf, "high",
                    mitigation="Recompetes are winnable with named discriminators "
                               "or a teaming position; investigate incumbent "
                               "performance signals first.")
    if status == "likely_incumbent":
        return _dim("incumbent_position", "Incumbent position", "weak",
                    [f"Likely incumbent {name} ({conf}/100)"] + ev, conf, "high",
                    mitigation="Verify the incumbency before investing — the link "
                               "is inferred, not confirmed.")
    if status == "possible_incumbent":
        return _dim("incumbent_position", "Incumbent position", "moderate",
                    [f"Possible incumbent {name} ({conf}/100) — scope/agency-level "
                     "match only"] + ev, conf, "medium")
    if status == "no_known_incumbent":
        return _dim("incumbent_position", "Incumbent position", "moderate",
                    ["No known incumbent found in related award history — note "
                     "this is not proof there is no incumbent."], 45, "medium")
    return _dim("incumbent_position", "Incumbent position", "unknown",
                ["No related award history loaded; incumbency cannot be "
                 "assessed."], 15, "high",
                unknowns=["predecessor contract and incumbent identity"])


def _competitive_position(competition):
    label = (competition or {}).get("label", "insufficient data")
    top3 = (competition or {}).get("top3_share_pct")
    vendors = (competition or {}).get("unique_vendor_count", 0)
    ev = [f"Market shape at this buyer: {label}"]
    if top3 is not None:
        ev.append(f"Top-3 vendor share {top3}% across {vendors} vendor(s)")
    if label == "insufficient data":
        return _dim("competitive_position", "Competitive position", "unknown",
                    ["No comparable-award vendor landscape loaded."], 20, "medium",
                    unknowns=["who the likely competitors are"])
    if "incumbent-dominated" in label or "concentrated" in label:
        return _dim("competitive_position", "Competitive position", "weak", ev,
                    60, "medium",
                    mitigation="Concentrated markets favor teaming with, or "
                               "displacing, the dominant vendor.")
    if "fragmented" in label:
        return _dim("competitive_position", "Competitive position", "moderate",
                    ev + ["Fragmented vendor base — room for a new entrant"],
                    60, "medium")
    return _dim("competitive_position", "Competitive position", "moderate", ev,
                55, "medium")


def _economic_attractiveness(value_est, market):
    trend = (market or {}).get("trend", "insufficient data")
    if not value_est:
        return _dim("economic_attractiveness", "Economic attractiveness", "unknown",
                    ["No defensible comparable-award value basis yet (needs ≥2 "
                     "comparable awards)."], 25, "medium",
                    unknowns=["expected contract value range"])
    ev = [f"Comparable awards from this buyer: "
          f"${value_est['low']:,.0f}–${value_est['high']:,.0f} "
          f"(median ${value_est['median']:,.0f}, n={value_est['basis']})"]
    rating = "moderate"
    if trend == "growing":
        ev.append("Category spending at this buyer is growing")
        rating = "strong"
    elif trend == "declining":
        ev.append("Category spending at this buyer is declining")
        rating = "weak"
    return _dim("economic_attractiveness", "Economic attractiveness", rating,
                ev, 55, "medium")


def _strategic_value(weights, opp, match):
    feats = []
    naics = opp.get("naics")
    agency = opp.get("agency")
    for feature, w in (weights or {}).items():
        if w > 0 and ((naics and feature == f"naics:{naics}")
                      or (agency and feature == f"agency:{agency}")):
            feats.append(f"Your feedback history favors {feature} (+{w})")
        elif w < 0 and ((naics and feature == f"naics:{naics}")
                        or (agency and feature == f"agency:{agency}")):
            feats.append(f"Your feedback history disfavors {feature} ({w})")
    if not weights:
        return _dim("strategic_value", "Strategic value", "unknown",
                    ["No learned preference signal yet — mark good/bad matches "
                     "to teach the model your strategy."], 20, "low",
                    unknowns=["fit with your strategic direction"])
    negative = any("disfavors" in f for f in feats)
    positive = any("favors" in f and "disfavors" not in f for f in feats)
    if positive and not negative:
        return _dim("strategic_value", "Strategic value", "strong", feats, 55, "low")
    if negative and not positive:
        return _dim("strategic_value", "Strategic value", "weak", feats, 55, "low")
    return _dim("strategic_value", "Strategic value", "moderate",
                feats or ["No learned signal for this agency/NAICS either way."],
                40, "low")


def _execution_readiness(days_left, qualification, documents):
    ev, rating, mitigation = [], "moderate", None
    if days_left is None:
        ev.append("No response deadline posted")
    elif days_left < 0:
        ev.append("Response deadline has passed")
        rating = "blocked"
    elif days_left <= 3:
        ev.append(f"Only {days_left} day(s) remain to respond")
        rating = "weak"
        mitigation = "A credible response in this window requires existing " \
                     "boilerplate and immediate go decision."
    elif days_left <= 10:
        ev.append(f"{days_left} days remain — workable but tight")
    else:
        ev.append(f"{days_left} days remain")
        rating = "strong"
    n_docs = len(documents or [])
    if n_docs:
        pending = sum(1 for d in documents
                      if d.get("fetch_status") not in ("extracted", "fetched"))
        ev.append(f"{n_docs} solicitation document(s); "
                  f"{n_docs - pending} processed")
    rows = len((qualification or {}).get("rows", []))
    if rows >= 12:
        ev.append(f"{rows} extracted requirements — a substantial compliance "
                  "burden")
    return _dim("execution_readiness", "Execution readiness", rating, ev,
                65, "medium", mitigation=mitigation)


def _intelligence_completeness(dossier, documents, qualification):
    missing, present = [], []
    if not dossier:
        return _dim("intelligence_completeness", "Intelligence completeness",
                    "weak", ["Dossier not generated yet — enrichment pending."],
                    80, "low",
                    unknowns=["award history", "incumbent", "buyer profile",
                              "funding context"])
    if dossier.get("similar_work"):
        present.append(f"{len(dossier['similar_work'])} linked prior awards")
    else:
        missing.append("prior-award history")
    if (dossier.get("incumbent_analysis") or {}).get("incumbent_status") \
            not in (None, "insufficient_data"):
        present.append("incumbent assessment")
    else:
        missing.append("incumbent assessment")
    if (dossier.get("funding_context") or {}).get("label_key") not in (None, "none"):
        present.append("funding context")
    else:
        missing.append("funding context")
    if documents:
        done = sum(1 for d in documents if d.get("fetch_status") == "extracted")
        present.append(f"{done}/{len(documents)} documents text-extracted")
        if done < len(documents):
            missing.append("full document extraction")
    else:
        missing.append("solicitation documents")
    if not (qualification or {}).get("rows"):
        missing.append("extracted requirements")
    total = len(present) + len(missing)
    pct = round(100 * len(present) / total) if total else 0
    rating = "strong" if pct >= 75 else ("moderate" if pct >= 40 else "weak")
    ev = [f"Dossier completeness {pct}%"]
    if present:
        ev.append("Loaded: " + "; ".join(present))
    return _dim("intelligence_completeness", "Intelligence completeness", rating,
                ev, 75, "low", unknowns=missing, score=pct)


def _summarize(dims, opp, days_left):
    """Ordered deterministic rules. First match wins; rationale explains why."""
    d = {x["key"]: x for x in dims}
    elig, fit = d["eligibility"], d["capability_fit"]
    inc = d["incumbent_position"]
    completeness = d["intelligence_completeness"]
    stage = (opp.get("notice_type") or "").lower()
    early = any(s in stage for s in EARLY_STAGES)
    rationale = []

    fit_rank = _RATING_RANK[fit["rating"]]
    if d["execution_readiness"]["rating"] == "blocked":
        key = "no_bid"
        rationale.append("The response deadline has passed.")
    elif elig["rating"] == "blocked":
        if fit_rank >= _RATING_RANK["moderate"]:
            key = "pursue_subcontract"
            rationale.append("Prime bidding is barred by set-aside eligibility, "
                             "but capability fit supports a subcontract position.")
        else:
            key = "no_bid"
            rationale.append("Barred from priming and capability fit is weak or "
                             "unknown.")
    elif (completeness["rating"] == "weak" and fit["rating"] == "unknown"
          and inc["rating"] == "unknown"):
        key = "insufficient_evidence"
        rationale.append("Neither fit nor market intelligence is loaded yet; "
                         "wait for enrichment before deciding.")
    elif elig["rating"] == "weak" and elig["materiality"] == "gate":
        if fit_rank >= _RATING_RANK["moderate"]:
            key = "pursue_prime_with_partner"
            rationale.append("A gated requirement (vehicle/clearance) is missing "
                             "but clearable by teaming; fit otherwise supports "
                             "pursuit.")
        else:
            key = "track"
            rationale.append("Gated requirement plus modest fit — monitor rather "
                             "than invest.")
    elif early and fit_rank >= _RATING_RANK["moderate"]:
        key = "shape"
        rationale.append(f"Early acquisition stage ({opp.get('notice_type')}) — "
                         "responding to market research shapes the requirement "
                         "before competitors see the RFP.")
    elif inc["rating"] == "weak" and "Confirmed incumbent" in \
            " ".join(inc["evidence"]):
        key = "conditional"
        rationale.append("A confirmed incumbent holds this work; pursue only if "
                         "you identify a concrete incumbent weakness or a "
                         "teaming path.")
    elif inc["rating"] == "weak" and "Likely incumbent" in \
            " ".join(inc["evidence"]):
        key = "track"
        rationale.append("Fit supports pursuit but a likely incumbent was "
                         "inferred from award history — verify the incumbency "
                         "and assess teaming with or against them before "
                         "committing capture budget.")
    elif fit["rating"] == "strong" and (days_left is None or days_left > 7):
        key = "pursue_prime"
        rationale.append("Strong capability fit with a workable timeline and no "
                         "gating obstacle found.")
    elif fit["rating"] == "strong":
        key = "conditional"
        rationale.append("Strong fit but very little time remains; pursue only "
                         "with existing response material.")
    elif fit_rank >= _RATING_RANK["moderate"]:
        key = "track"
        rationale.append("Moderate fit — watch for amendments, incumbent news, "
                         "or a teaming opening before committing capture "
                         "budget.")
    elif fit["rating"] == "unknown":
        key = "insufficient_evidence"
        rationale.append("Capability fit cannot be assessed until a company "
                         "profile is saved.")
    else:
        key = "no_bid"
        rationale.append("Weak fit with no offsetting strategic or positional "
                         "advantage found.")

    weak_gates = [x for x in dims if x["rating"] in ("weak", "blocked")
                  and x["materiality"] in ("gate", "high")]
    for w in weak_gates[:2]:
        if w["mitigation"]:
            rationale.append(f"{w['name']}: {w['mitigation']}")

    known = sum(1 for x in dims if x["rating"] != "unknown")
    conf = round(30 + 55 * known / len(dims))
    return {
        "recommendation_key": key,
        "recommendation": RECOMMENDATIONS[key],
        "confidence": conf,
        "confidence_band": band(conf),
        "rationale": rationale,
    }


def build_decision_stack(opp: dict, match: dict, dossier: dict | None,
                         qualification: dict | None, value_est: dict | None,
                         documents: list[dict] | None, days_left: int | None,
                         projects: list[dict] | None = None,
                         weights: dict[str, int] | None = None,
                         forecasts: list[dict] | None = None) -> dict:
    """The per-organization decision stack for one opportunity.

    All inputs are stored records; nothing here fetches or invents. Unknown
    inputs produce 'unknown' ratings, never fabricated negatives."""
    dossier = dossier or {}
    dims = [
        _eligibility(qualification),
        _capability_fit(match or {}, opp),
        _past_performance(projects, opp),
        _buyer_position(projects, dossier, opp),
        _incumbent_position(dossier.get("incumbent_analysis"), forecasts),
        _competitive_position(dossier.get("competition_landscape")),
        _economic_attractiveness(value_est, dossier.get("market_size")),
        _strategic_value(weights, opp, match or {}),
        _execution_readiness(days_left, qualification, documents),
        _intelligence_completeness(dossier, documents, qualification),
    ]
    summary = _summarize(dims, opp, days_left)
    advantages = [x["evidence"][0] for x in dims
                  if x["rating"] == "strong" and x["evidence"]][:3]
    risks = [x["evidence"][0] for x in dims
             if x["rating"] in ("weak", "blocked") and x["evidence"]
             and x["materiality"] in ("gate", "high")][:3]
    if not risks:
        risks = [x["evidence"][0] for x in dims
                 if x["rating"] == "weak" and x["evidence"]][:3]
    completeness = next(x for x in dims
                        if x["key"] == "intelligence_completeness")
    order = {"gate": 0, "high": 1, "medium": 2, "low": 3}
    mitigations = sorted(
        (x for x in dims if x["rating"] in ("weak", "blocked", "unknown")
         and x["mitigation"]),
        key=lambda x: order[x["materiality"]])
    next_action = (mitigations[0]["mitigation"] if mitigations
                   else "Review the solicitation documents and linked prior "
                        "awards.")
    return {
        "summary": summary,
        "dimensions": dims,
        "top_advantages": advantages,
        "top_risks": risks,
        "next_action": next_action,
        "completeness_pct": completeness.get("score") or 0,
    }
