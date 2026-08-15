"""Oversight-finding-to-opportunity linking: "why this requirement exists".

A GAO recommendation or IG finding is linked to an opportunity only as
INFERRED demand context — unless the notice itself cites the report number,
which upgrades the link to 'cited'. Deterministic, evidence-backed, and
conservative: agency alignment plus real text overlap, or no link at all.
"""
from .similarity import cosine

LINK_THRESHOLD = 45


def _same_org(haystack: str | None, needle: str | None) -> bool:
    """True when either org string contains the other (case-insensitive).
    The opportunity side may be a joined hierarchy path so subtier-level
    findings (DEPT OF THE ARMY) match department-labeled notices."""
    if not haystack or not needle:
        return False
    a, b = haystack.lower().strip(), needle.lower().strip()
    return a in b or b in a


def score_oversight_link(opp: dict, finding: dict) -> dict | None:
    opp_text = f"{opp.get('title', '')} {opp.get('description_text', '')}"
    report_no = (finding.get("report_number") or "").strip()
    if report_no and report_no.lower() in opp_text.lower():
        return {"link_kind": "cited", "similarity_score": 95, "confidence": 90,
                "evidence": [f"the notice text cites {report_no} directly"]}

    score, evidence = 0, []
    opp_orgs = " > ".join(str(v) for v in (opp.get("agency"),
                                           opp.get("agency_path"),
                                           opp.get("office")) if v)
    if _same_org(opp_orgs, finding.get("agency")) or \
            _same_org(opp_orgs, finding.get("subtier")):
        score += 20
        evidence.append("finding addresses the same agency")
    sim = cosine(opp_text,
                 f"{finding.get('title', '')} {finding.get('detail', '')}")
    score += round(50 * sim)
    if sim >= 0.25:
        evidence.append(f"subject-matter similarity {round(sim * 100)}%")
    if (finding.get("status") or "") == "open":
        score += 10
        evidence.append("the recommendation is still open")
    if score < LINK_THRESHOLD or len(evidence) < 2:
        return None
    return {"link_kind": "inferred", "similarity_score": min(100, score),
            "confidence": min(75, score),   # inferred links never look certain
            "evidence": evidence}


def link_findings(opp: dict, findings: list[dict]) -> list[dict]:
    links = []
    for f in findings:
        res = score_oversight_link(opp, f)
        if res:
            links.append({**res, "finding": f})
    links.sort(key=lambda x: (-1 if x["link_kind"] == "cited" else 0,
                              -x["similarity_score"]))
    return links
