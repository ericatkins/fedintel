"""Requirement-to-proof mapping: extracted document requirements × the
organization's recorded past projects.

Deterministic and conservative: a proof claim needs real token overlap
between the requirement's own text and a recorded project, and evidence
freshness matters — old proof is labeled stale, never silently counted.
Keyword overlap alone is labeled as the weak signal it is; it is NEVER
presented as demonstrated past performance.

Proof statuses:
- strong   : relevant project, recent (ended within 3 years), category match
- weak     : some relevant overlap, but partial or aging
- stale    : relevant project but ended more than 5 years ago
- missing  : no recorded project touches this requirement
- profile  : judged against profile fields (vehicles/clearances/certs),
             not project evidence — see the qualification column
"""
from datetime import date

PROFILE_TYPES = {"set_aside", "vehicle", "clearance", "certification"}

_STOP = {"shall", "must", "will", "with", "this", "that", "have", "from",
         "such", "been", "were", "their", "other", "than", "each", "which",
         "requirement", "contractor", "government", "services", "service",
         "support", "provide", "personnel", "years", "experience"}


def _tokens(*texts) -> set[str]:
    out = set()
    for t in texts:
        for w in str(t or "").lower().replace("/", " ").replace(",", " ").split():
            w = w.strip(".;:()[]\"'")
            if len(w) >= 4 and w not in _STOP:
                out.add(w)
    return out


def _years_since_end(project, today) -> float | None:
    end = project.get("period_end")
    if not end:
        return None
    try:
        end_d = date.fromisoformat(str(end)[:10])
    except ValueError:
        return None
    return (today - end_d).days / 365.25


def _best_project(req, projects, opp, today):
    req_tokens = _tokens(req.get("value"), req.get("evidence_quote"))
    if not req_tokens:
        return None, None, []
    best, best_score, best_why = None, 0, []
    naics4 = (opp.get("naics") or "")[:4]
    for p in projects:
        p_tokens = _tokens(p.get("title"), p.get("scope"), p.get("technologies"),
                           p.get("outcomes"))
        overlap = req_tokens & p_tokens
        if not overlap:
            continue
        score = len(overlap)
        why = [f"project text matches: {', '.join(sorted(overlap)[:4])}"]
        if naics4 and (p.get("naics") or "")[:4] == naics4:
            score += 2
            why.append(f"same NAICS family {naics4}xx")
        agency = (opp.get("agency") or "").lower()
        if agency and agency in (p.get("customer_agency") or "").lower():
            score += 2
            why.append("same customer agency")
        if score > best_score:
            best, best_score, best_why = p, score, why
    return best, best_score, best_why


def map_requirements_to_proof(assessment_rows: list[dict],
                              projects: list[dict], opp: dict,
                              today: date | None = None) -> dict:
    """Annotate qualification rows with proof fields and summarize coverage.

    Returns {"rows": annotated rows, "summary": {...}}. Rows keep their
    original order and keys."""
    today = today or date.today()
    rows, mappable, covered = [], 0, 0
    for req in assessment_rows or []:
        row = dict(req)
        if req.get("requirement_type") in PROFILE_TYPES:
            row["proof_status"] = "profile"
            row["proof_why"] = []
            rows.append(row)
            continue
        mappable += 1
        if not projects:
            row["proof_status"] = "missing"
            row["proof_why"] = ["no past projects recorded"]
            rows.append(row)
            continue
        best, score, why = _best_project(req, projects, opp, today)
        if not best:
            row["proof_status"] = "missing"
            row["proof_why"] = ["no recorded project matches this requirement"]
            rows.append(row)
            continue
        age = _years_since_end(best, today)
        if age is not None and age > 5:
            status = "stale"
            why = why + [f"project ended {age:.0f} years ago"]
        elif score >= 4 and (age is None or age <= 3):
            status = "strong"
        else:
            status = "weak"
            why = why + ["overlap is partial — verify before claiming as past "
                         "performance"]
        covered += 1
        row["proof_status"] = status
        row["proof_project_id"] = best.get("id")
        row["proof_project"] = best.get("title")
        row["proof_why"] = why
        rows.append(row)

    strong = sum(1 for r in rows if r.get("proof_status") == "strong")
    stale = sum(1 for r in rows if r.get("proof_status") == "stale")
    summary = {
        "mappable_requirements": mappable,
        "with_any_proof": covered,
        "strong_proof": strong,
        "stale_proof": stale,
        "coverage_pct": round(100 * covered / mappable) if mappable else None,
        "caveats": [
            "Proof mapping is token-based against your recorded projects — it "
            "finds candidates for a past-performance narrative; it does not "
            "certify relevance.",
        ],
    }
    if not projects:
        summary["caveats"].append(
            "No past projects recorded: every mappable requirement shows "
            "'missing'. Add projects on the profile page.")
    return {"rows": rows, "summary": summary}
