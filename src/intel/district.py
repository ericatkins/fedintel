"""District intelligence: federal money into a congressional district, and an
EXPLAINABLE electoral context for its representative.

Truthfulness rules, stated on every surface:
- Inflows describe the PLACE. Only congressionally-directed spending
  (CPF/earmarks) is attributable to a member. We rank districts and show who
  represents them; we never say a member "brought in" general awards.
- There is no reliable machine-readable voter-sentiment feed, and we will not
  fabricate one. In its place: a partisan lean COMPUTED from imported election
  results, margin trend, and FEC-observable facts (incumbency, cash on hand,
  challenger filings). The output is context with reasons — not a forecast.
"""
ATTRIBUTION_NOTE = (
    "Inflow figures aggregate federal obligations by place of performance in "
    "the district (USAspending). They describe where money is spent, not who "
    "caused it — appropriations are institutional. Only congressionally "
    "directed spending (Community Project Funding / earmarks) is attributable "
    "to a requesting member, and those items are labeled separately."
)

SENTIMENT_NOTE = (
    "Fedintel does not scrape or estimate voter sentiment — no reliable public "
    "feed exists and synthetic sentiment would be fabrication. Shown instead: "
    "partisan lean computed from imported election results, the margin trend, "
    "and FEC-observable campaign facts. Treat the outlook as context for "
    "relationship planning, not an election forecast."
)


def partisan_lean(results: list[dict]) -> dict | None:
    """Average winning two-party margin over recent GENERAL results for the
    seat. Positive = leans toward the current winners' party."""
    generals = [r for r in results
                if r.get("stage") == "general" and r.get("vote_share") is not None]
    by_cycle: dict[int, list[dict]] = {}
    for r in generals:
        by_cycle.setdefault(r["cycle"], []).append(r)
    margins = []
    for cycle in sorted(by_cycle, reverse=True)[:3]:
        rows = sorted(by_cycle[cycle], key=lambda r: -float(r["vote_share"]))
        if not rows:
            continue
        winner = rows[0]
        runner_up = float(rows[1]["vote_share"]) if len(rows) > 1 else 0.0
        margins.append({"cycle": cycle, "party": winner.get("party"),
                        "margin": round(float(winner["vote_share"]) - runner_up, 1)})
    if not margins:
        return None
    avg = round(sum(m["margin"] for m in margins) / len(margins), 1)
    trend = None
    if len(margins) >= 2:
        delta = margins[0]["margin"] - margins[-1]["margin"]
        trend = ("widening" if delta > 3 else
                 "narrowing" if delta < -3 else "stable")
    return {"lean_margin": avg, "party": margins[0]["party"],
            "cycles": [m["cycle"] for m in margins], "per_cycle": margins,
            "trend": trend,
            "basis": f"winning margins across {len(margins)} general election(s)"}


def primary_history(results: list[dict], member_name: str) -> list[dict]:
    """The member's own primary performances (answering 'how have they fared
    in primaries' from imported, sourced results)."""
    name_lower = (member_name or "").lower()
    rows = [r for r in results if r.get("stage") == "primary"
            and name_lower and name_lower.split()[-1] in
            (r.get("candidate_name") or "").lower()]
    out = []
    for r in sorted(rows, key=lambda r: -r["cycle"]):
        out.append({"cycle": r["cycle"],
                    "vote_share": (float(r["vote_share"])
                                   if r.get("vote_share") is not None else None),
                    "won": r.get("won"), "source": r.get("source")})
    return out


def seat_outlook(lean: dict | None, last_margin: float | None,
                 is_incumbent_running: bool | None,
                 incumbent_cash: float | None,
                 best_challenger_receipts: float | None) -> dict:
    """Deterministic, bounded, fully-reasoned outlook label. Context only."""
    reasons, score = [], 0
    if last_margin is not None:
        if last_margin >= 20:
            score += 3
            reasons.append(f"won last general by {last_margin:.0f} points")
        elif last_margin >= 10:
            score += 2
            reasons.append(f"won last general by {last_margin:.0f} points")
        elif last_margin >= 5:
            score += 1
            reasons.append(f"modest last margin ({last_margin:.0f} points)")
        else:
            reasons.append(f"narrow last margin ({last_margin:.0f} points)")
    if lean and lean.get("lean_margin") is not None:
        if lean["lean_margin"] >= 15:
            score += 2
            reasons.append(f"seat leans {lean['lean_margin']:.0f} pts over "
                           f"{len(lean['cycles'])} cycles")
        elif lean["lean_margin"] >= 7:
            score += 1
            reasons.append(f"seat leans {lean['lean_margin']:.0f} pts")
        if lean.get("trend") == "narrowing":
            score -= 1
            reasons.append("margins narrowing across recent cycles")
    if is_incumbent_running is False:
        score -= 2
        reasons.append("open seat — no incumbent on the ballot")
    elif is_incumbent_running:
        score += 1
        reasons.append("incumbent running")
    if incumbent_cash is not None and best_challenger_receipts is not None:
        if best_challenger_receipts > incumbent_cash:
            score -= 2
            reasons.append("a challenger has out-raised the incumbent's cash "
                           "on hand (FEC)")
        elif best_challenger_receipts > 0.5 * incumbent_cash:
            score -= 1
            reasons.append("well-funded challenger filed (FEC)")
        else:
            reasons.append("no comparably funded challenger on file (FEC)")
    label = ("safe-context" if score >= 5 else
             "likely-context" if score >= 3 else
             "lean-context" if score >= 1 else
             "competitive-context")
    return {"label": label, "score": score, "reasons": reasons,
            "note": "context, not a forecast",
            "inputs_seen": {"last_margin": last_margin is not None,
                            "lean": lean is not None,
                            "incumbency": is_incumbent_running is not None,
                            "fec_finance": incumbent_cash is not None}}


def rank_note(agency: str | None) -> str:
    what = f"{agency} obligations" if agency else "all federal obligations"
    return (f"Districts ranked by {what} performed there — a fact about the "
            "place, shown with who represents it. Member attribution applies "
            "only to congressionally directed spending.")
