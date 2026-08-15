"""Executive Intelligence Brief: the grounded narrative at the top of the
dossier.

Every sentence is assembled deterministically from fields already stored and
shown elsewhere on the page — the brief is a reading order, not a new claim.
Each paragraph carries `refs`, the dossier sections that substantiate it, so
a reader can audit any line in one click. No generative AI is involved; a
future AI layer may rephrase these paragraphs but may never add facts.
"""

_RATING_WORD = {"strong": "strong", "moderate": "workable", "weak": "weak",
                "blocked": "blocked", "unknown": "not yet assessable"}


def _p(text, *refs):
    return {"text": text, "refs": list(refs)}


def _need_paragraph(opp, dossier):
    origin = (dossier.get("work_origin_assessment") or {})
    label = (origin.get("work_origin_assessment") or "unclear").replace("_", " ")
    stage = opp.get("notice_type") or "notice"
    agency = opp.get("agency") or "The agency"
    office = opp.get("office")
    who = f"{agency}{' (' + office + ')' if office else ''}"
    text = (f"{who} has posted a {stage.lower()} for "
            f"“{opp.get('title', '')}”. The work-origin assessment "
            f"reads this as {label} "
            f"({origin.get('confidence', 0)}/100 confidence).")
    return _p(text, "Work origin", "Opportunity facts")


def _why_paragraph(dossier, forecasts, oversight):
    parts, refs = [], []
    fam = dossier.get("contract_family") or {}
    rc = fam.get("recompete") or {}
    if rc.get("estimated_expiration"):
        parts.append(f"a predecessor contract's recorded period ends "
                     f"{rc['estimated_expiration']}")
        refs.append("Contract family")
    for f in forecasts or []:
        if f.get("action_type") == "recompete":
            parts.append("the agency's own forecast planned this as a "
                         "recompete")
            refs.append("Forecast lineage")
            break
        if f.get("title"):
            parts.append("the requirement appears in the agency's "
                         "procurement forecast")
            refs.append("Forecast lineage")
            break
    for f in oversight or []:
        kind = "cited by the notice" if f.get("link_kind") == "cited" else \
            "linked as inferred context"
        parts.append(f"an oversight finding "
                     f"({f.get('report_number') or 'GAO/IG'}) addressing this "
                     f"program area is {kind}")
        refs.append("Why this requirement exists")
        break
    if not parts:
        return _p("No public demand driver (expiring contract, forecast, or "
                  "oversight finding) is linked in loaded data — the cause of "
                  "the requirement is unknown, which is not the same as "
                  "absent.", "Evidence & source ledger")
    return _p("Why now: " + "; ".join(parts) + ".", *dict.fromkeys(refs))


def _history_paragraph(dossier):
    inc = dossier.get("incumbent_analysis") or {}
    fam = dossier.get("contract_family") or {}
    status = (inc.get("incumbent_status") or "insufficient_data")
    name = inc.get("likely_incumbent_name")
    n = fam.get("member_count") or 0
    refs = ["Incumbent analysis", "Contract family"]
    if status == "insufficient_data":
        return _p("No related award history is loaded for this buyer and "
                  "category yet — incumbency and history cannot be assessed. "
                  "Absence of data is not evidence of absence.", *refs)
    bits = []
    if name:
        tier = status.replace("_", " ")
        bits.append(f"{name} is the {tier} "
                    f"({inc.get('incumbent_confidence', 0)}/100)")
    else:
        bits.append("no known incumbent was found in related award history")
    if n:
        bits.append(f"the reconstructed contract family holds {n} prior "
                    f"action(s), {fam.get('confirmed_count', 0)} confirmed by "
                    "shared identifiers")
    vul = (fam.get("vulnerability") or {}).get("assessment")
    if vul and vul != "no defensible assessment":
        bits.append(f"the public-signal vulnerability read is “{vul}”")
    return _p("History: " + "; ".join(bits) + ".", *refs)


def _buyer_paragraph(dossier):
    dna = dossier.get("buyer_dna") or {}
    comp = dossier.get("competition_landscape") or {}
    refs = ["Buyer DNA", "Competitive landscape"]
    if dna.get("status") != "ok":
        return _p("How this office buys is not yet comparable to peers — the "
                  "award pools are too thin for behavioral labels.", *refs)
    labels = [lb["label"] for lb in dna.get("labels") or []]
    text = (f"Buyer behavior vs peers: "
            f"{', '.join(labels) if labels else 'no material deviations'}"
            f"; the vendor landscape here is "
            f"{comp.get('label', 'not assessed')}.")
    return _p(text, *refs)


def _position_paragraph(decision):
    dims = {d["key"]: d for d in decision.get("dimensions") or []}
    strongest = max((d for d in dims.values() if d["rating"] == "strong"),
                    key=lambda d: d["confidence"], default=None)
    gates = [d for d in dims.values()
             if d["rating"] in ("weak", "blocked")
             and d["materiality"] in ("gate", "high")]
    refs = ["Capture decision stack"]
    bits = []
    if strongest:
        bits.append(f"your strongest position is {strongest['name'].lower()} "
                    f"({strongest['evidence'][0]})")
    if gates:
        g = gates[0]
        bits.append(f"the largest gap is {g['name'].lower()} "
                    f"({g['evidence'][0]})")
        if g.get("mitigation"):
            bits.append(g["mitigation"].rstrip(".").lower())
    if not bits:
        bits.append("no dimension is assessable yet — complete the company "
                    "profile and evidence library")
    return _p("Position: " + "; ".join(bits) + ".", *refs)


def _approach_paragraph(decision):
    summ = decision.get("summary") or {}
    rationale = (summ.get("rationale") or [""])[0]
    return _p(f"Recommended approach: {summ.get('recommendation', '—')} — "
              f"{rationale}", "Capture decision stack")


def _questions_paragraph(decision):
    unknowns = []
    for d in decision.get("dimensions") or []:
        for u in d.get("unknowns") or []:
            if u not in unknowns:
                unknowns.append(u)
    if not unknowns:
        return None
    return _p("Critical unresolved questions: "
              + "; ".join(unknowns[:4]) + ".", "Capture decision stack")


def build_executive_brief(opp: dict, dossier: dict | None, decision: dict,
                          forecasts: list[dict] | None = None,
                          oversight: list[dict] | None = None) -> list[dict]:
    """Ordered paragraphs, each with the dossier sections that back it."""
    if not dossier:
        return [_p("Dossier generation is pending — this brief will populate "
                   "after the next enrichment run. The decision stack below "
                   "already reflects everything known.",
                   "Capture decision stack")]
    paragraphs = [
        _need_paragraph(opp, dossier),
        _why_paragraph(dossier, forecasts, oversight),
        _history_paragraph(dossier),
        _buyer_paragraph(dossier),
        _position_paragraph(decision),
        _approach_paragraph(decision),
    ]
    q = _questions_paragraph(decision)
    if q:
        paragraphs.append(q)
    return paragraphs
