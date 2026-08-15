"""Contract family, recompete clock, and incumbent vulnerability signals.

Reconstructs the family of prior contract actions behind an opportunity from
already-linked public award records, estimates the recompete window with its
assumptions stated, and derives an explicitly public-signal vulnerability
read. Confirmed links (shared solicitation/contract identifiers) are always
kept visually and semantically distinct from inferred links.

Pure functions over (opportunity, links, lineage rows). No fetching.
"""
from datetime import date, timedelta

from .confidence import band

CONFIRMED_LINK_TYPES = ("same_solicitation", "same_contract")

VULNERABILITY_LABELS = (
    "entrenched incumbent",
    "incumbent favored but requirement changing",
    "incumbent position uncertain",
    "credible displacement opportunity",
    "no defensible assessment",
)

_CHANGE_LANGUAGE = (
    "alternative approach", "alternative solutions", "restructur",
    "re-structur", "consolidat", "small business set-aside", "new acquisition",
    "industry feedback", "market research", "capability of small",
)


def _d(value):
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _member(ln, role):
    a = ln["award"]
    months = None
    ps, pe = _d(a.get("period_start")), _d(a.get("period_end"))
    if ps and pe:
        months = round((pe - ps).days / 30.4)
    return {
        "role": role,                        # predecessor | related | bridge
        "confirmed": ln["link_type"] in CONFIRMED_LINK_TYPES,
        "link_type": ln["link_type"],
        "similarity_score": ln["similarity_score"],
        "evidence": ln["evidence"],
        "piid": a.get("piid"),
        "parent_award_id": a.get("parent_award_id"),
        "source_award_id": a.get("source_award_id"),
        "vendor": a.get("recipient_name"),
        "title": a.get("award_title"),
        "award_date": str(a.get("award_date") or ""),
        "period_start": str(a.get("period_start") or ""),
        "period_end": str(a.get("period_end") or ""),
        "period_months": months,
        "obligated_amount": a.get("obligated_amount"),
        "total_obligated_amount": a.get("total_obligated_amount"),
        "potential_total_value": a.get("potential_total_value"),
        "award_type": a.get("award_type"),
        "contract_vehicle": a.get("contract_vehicle"),
    }


def _detect_bridges(members):
    """A bridge candidate: short award (≤ 12 months) to the same vendor
    starting within ~90 days of another family award's period end."""
    for m in members:
        if not m["period_months"] or m["period_months"] > 12:
            continue
        ms = _d(m["period_start"])
        if not ms:
            continue
        for other in members:
            if other is m or not other["vendor"]:
                continue
            oe = _d(other["period_end"])
            if (other["vendor"] == m["vendor"] and oe
                    and timedelta(days=-30) <= (ms - oe) <= timedelta(days=90)):
                m["role"] = "bridge"
                m["evidence"] = list(m["evidence"]) + [
                    f"short {m['period_months']}-month award to the same vendor "
                    f"starting at the end of {other['piid'] or 'a prior award'}"]
    return members


def _recompete_clock(members, today):
    """Estimate expiration and the recompete window, assumptions stated."""
    assumptions = [
        "Estimated from recorded period-of-performance end dates in public "
        "award data; unexercised options and unposted modifications may "
        "extend the true end date.",
        "USAspending reporting can lag contract actions by weeks to months.",
    ]
    base = next((m for m in members if m["confirmed"]), None) or \
        next((m for m in members if m["role"] == "predecessor"), None)
    pool = [base] if base else [m for m in members if m["role"] != "bridge"]
    ends = sorted((_d(m["period_end"]) for m in pool if m and _d(m["period_end"])),
                  reverse=True)
    if not ends:
        return {
            "estimated_expiration": None,
            "window": None,
            "confidence": 10,
            "confidence_band": band(10),
            "assumptions": assumptions,
            "caveats": ["No period-of-performance end dates available in the "
                        "linked award records."],
        }
    exp = ends[0]
    conf = 70 if base else 40
    if exp < today:
        conf -= 15
    caveats = []
    if exp < today:
        caveats.append("The recorded period end has already passed — the work "
                       "may be on a bridge, an option, or already recompeted.")
    return {
        "estimated_expiration": str(exp),
        "window": {
            "engage_from": str(exp - timedelta(days=365)),
            "solicitation_expected_by": str(exp - timedelta(days=120)),
        },
        "confidence": max(0, conf),
        "confidence_band": band(max(0, conf)),
        "assumptions": assumptions,
        "caveats": caveats,
    }


def _vulnerability(members, opp, today, protests=None, oversight=None):
    """Public-signal-only vulnerability read. Every signal names its evidence;
    absence of signals is never presented as incumbent strength."""
    signals, caveats = [], [
        "Assessment uses public award and notice records only — it is NOT "
        "based on government performance evaluations (CPARS), which are not "
        "public.",
    ]
    incumbents = [m for m in members if m["role"] in ("predecessor", "bridge")
                  and m["vendor"]]
    if not incumbents:
        return {"assessment": "no defensible assessment", "signals": [],
                "caveats": caveats + ["No plausible predecessor award linked."]}

    for p in protests or []:
        outcome = p.get("outcome") or "pending"
        weight = ("a sustained protest or corrective action forced the agency "
                  "to revisit the award"
                  if outcome in ("sustained", "corrective_action") else
                  "even unsuccessful protests signal a contested competition")
        decided = (f", decided {p['decided_date']}"
                   if p.get("decided_date") else "")
        signals.append({
            "signal": "bid protest in this solicitation family",
            "evidence": f"{p.get('protester') or 'A protester'} filed "
                        f"{p.get('source_record_id')} "
                        f"({outcome.replace('_', ' ')}{decided}) — {weight}."})
    for f in oversight or []:
        if (f.get("status") or "") != "open":
            continue
        signals.append({
            "signal": "open oversight finding",
            "evidence": f"{f.get('report_number') or 'An oversight report'}: "
                        f"{(f.get('title') or '')[:120]} — an open GAO/IG "
                        "finding against the program area pressures the "
                        "status quo (inferred context, "
                        f"{f.get('link_kind', 'inferred')} link)."})

    bridges = [m for m in members if m["role"] == "bridge"]
    for b in bridges:
        signals.append({
            "signal": "bridge extension",
            "evidence": f"{b['vendor']} received a short "
                        f"{b['period_months']}-month award "
                        f"({b['piid'] or b['source_award_id']}) — bridges often "
                        "mean a delayed or contested recompete."})

    text = f"{opp.get('title', '')} {opp.get('description_text', '')}".lower()
    change_hits = [w for w in _CHANGE_LANGUAGE if w in text]
    if change_hits:
        signals.append({
            "signal": "requirement-change language",
            "evidence": "The notice uses language associated with restructuring "
                        f"the requirement: {', '.join(change_hits[:3])}."})

    new_set_aside = (opp.get("set_aside") or "").strip()
    if new_set_aside and incumbents:
        signals.append({
            "signal": "set-aside on the new notice",
            "evidence": f"The new notice is set aside ({new_set_aside}); if the "
                        "predecessor was full-and-open, the incumbent may be "
                        "excluded or forced to team."})

    for m in incumbents:
        pot = float(m.get("potential_total_value") or 0)
        obl = float(m.get("total_obligated_amount") or
                    m.get("obligated_amount") or 0)
        if pot > 0 and obl > 0 and obl / pot < 0.5:
            end = _d(m["period_end"])
            if end and end <= today + timedelta(days=365):
                signals.append({
                    "signal": "low obligation rate near end of period",
                    "evidence": f"{m['vendor']}: ${obl:,.0f} obligated of "
                                f"${pot:,.0f} potential with the period ending "
                                f"{m['period_end']} — may indicate reduced "
                                "scope, though ceilings are often not fully "
                                "used."})
            break

    tenure_awards = len([m for m in members
                         if m["vendor"] == incumbents[0]["vendor"]])
    if len(signals) >= 2:
        assessment = "credible displacement opportunity"
    elif signals and change_hits:
        assessment = "incumbent favored but requirement changing"
    elif signals:
        assessment = "incumbent position uncertain"
    elif tenure_awards >= 2:
        assessment = "entrenched incumbent"
        caveats.append(f"{incumbents[0]['vendor']} holds {tenure_awards} awards "
                       "in this family with no public weakness signal found — "
                       "absence of signals is not proof of strength.")
    else:
        assessment = "incumbent position uncertain"
    return {"assessment": assessment, "signals": signals, "caveats": caveats}


def build_contract_family(opp: dict, links: list[dict],
                          lineage_rows: list[dict] | None = None,
                          today: date | None = None,
                          protests: list[dict] | None = None,
                          oversight: list[dict] | None = None) -> dict:
    """Assemble the contract family view for the dossier."""
    today = today or date.today()
    members = []
    seen = set()
    for ln in links:
        key = ln["award"].get("source_award_id")
        if key in seen:
            continue
        if ln["link_type"] in CONFIRMED_LINK_TYPES:
            members.append(_member(ln, "predecessor"))
            seen.add(key)
        elif ln["similarity_score"] >= 55:
            members.append(_member(ln, "related"))
            seen.add(key)
    # highest-similarity related member is the presumed predecessor when no
    # confirmed member exists
    if members and not any(m["confirmed"] for m in members):
        members[0]["role"] = "predecessor"
    members = _detect_bridges(members)
    members.sort(key=lambda m: m["award_date"] or "0000")

    timeline = []
    for row in lineage_rows or []:
        timeline.append({
            "date": str(row.get("posted_date") or ""),
            "kind": "notice",
            "label": row.get("stage") or "notice",
            "confirmed": True,
            "opportunity_id": row.get("opportunity_id"),
        })
    for m in members:
        timeline.append({
            "date": m["award_date"] or m["period_start"],
            "kind": "bridge" if m["role"] == "bridge" else "award",
            "label": (f"{'Bridge' if m['role'] == 'bridge' else 'Award'} — "
                      f"{m['vendor'] or 'unknown vendor'}"),
            "confirmed": m["confirmed"],
            "source_award_id": m["source_award_id"],
        })
    recompete = _recompete_clock(members, today)
    if recompete.get("estimated_expiration"):
        timeline.append({
            "date": recompete["estimated_expiration"],
            "kind": "recompete_estimate",
            "label": "Estimated predecessor expiration",
            "confirmed": False,
        })
    timeline = [t for t in timeline if t["date"]]
    timeline.sort(key=lambda t: t["date"])

    for p in protests or []:
        if p.get("filed_date"):
            timeline.append({
                "date": str(p["filed_date"]),
                "kind": "protest",
                "label": f"Protest {p.get('source_record_id')} "
                         f"({(p.get('outcome') or 'pending').replace('_', ' ')})",
                "confirmed": True,
            })
    timeline.sort(key=lambda t: t["date"])
    return {
        "members": members,
        "timeline": timeline,
        "recompete": recompete,
        "vulnerability": _vulnerability(members, opp, today,
                                        protests=protests,
                                        oversight=oversight),
        "protests": [
            {"b_number": p.get("source_record_id"),
             "protester": p.get("protester"),
             "outcome": p.get("outcome"),
             "filed_date": str(p.get("filed_date") or ""),
             "source_url": p.get("source_url")}
            for p in (protests or [])[:5]],
        "member_count": len(members),
        "confirmed_count": sum(1 for m in members if m["confirmed"]),
    }
