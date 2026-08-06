"""Deterministic requirement extraction from solicitation text.

Every rule is a named regex producing (type, normalized value, evidence quote,
page, confidence). No AI, no inference beyond the pattern — if a rule fires,
the source sentence is captured so the UI can show WHY. Rules are ordered from
most specific to least so 'TS/SCI' never degrades into a bare 'Secret' hit.

Confidence reflects how unambiguous the phrasing is, not how important it is.
"""
import re

# type, name, pattern, normalized value (None = use match group 1), confidence
RULES: list[tuple[str, str, str, str | None, int]] = [
    # ---- clearances (most specific first) ----
    ("clearance", "tssci", r"\bTS\s*/\s*SCI\b|\bTop\s+Secret\s*/\s*SCI\b", "TS/SCI", 95),
    ("clearance", "top_secret", r"\bTop\s+Secret\b(?!\s*/\s*SCI)", "Top Secret", 90),
    ("clearance", "secret", r"\bSecret\s+(?:security\s+)?clearance\b", "Secret", 90),
    ("clearance", "poly", r"\b(?:CI|counterintelligence|full[- ]scope|lifestyle)\s+poly",
     "Polygraph", 85),
    ("clearance", "public_trust", r"\bPublic\s+Trust\b", "Public Trust", 80),
    ("clearance", "facility_clearance",
     r"\bfacility\s+(?:security\s+)?clearance\b|\bFCL\b", "Facility Clearance (FCL)", 85),
    # ---- contract vehicles ----
    ("vehicle", "cio_sp", r"\bCIO[-\s]?SP\s?[34](?:\s?i)?\b", None, 95),
    ("vehicle", "sewp", r"\bSEWP\s?V?I?\b", "NASA SEWP", 90),
    ("vehicle", "oasis", r"\bOASIS(?:\+|\s?PLUS)?\b", "OASIS/OASIS+", 90),
    ("vehicle", "alliant", r"\bAlliant\s?[23]?\b", "GSA Alliant", 90),
    ("vehicle", "stars", r"\b8\(a\)\s?STARS\s?I{0,3}\b", "8(a) STARS", 90),
    ("vehicle", "gsa_mas", r"\bGSA\s+(?:MAS|Multiple\s+Award\s+Schedule|Schedule\b)",
     "GSA MAS", 85),
    ("vehicle", "gwac", r"\bGWAC\b", "GWAC (unspecified)", 70),
    ("vehicle", "idiq", r"\bID/?IQ\b|\bIndefinite[- ]Delivery\b", "IDIQ", 75),
    ("vehicle", "bpa", r"\bBlanket\s+Purchase\s+Agreement\b|\bBPA\b", "BPA", 75),
    # ---- set-aside / socioeconomic ----
    ("set_aside", "eight_a", r"\b8\(a\)\b", "8(a)", 90),
    ("set_aside", "hubzone", r"\bHUBZone\b", "HUBZone", 95),
    ("set_aside", "sdvosb", r"\bSDVOSB\b|\bService[- ]Disabled\s+Veteran", "SDVOSB", 95),
    ("set_aside", "wosb", r"\bWOSB\b|\bWomen[- ]Owned\s+Small\s+Business\b", "WOSB", 90),
    ("set_aside", "total_sb",
     r"\bTotal\s+Small\s+Business\s+Set[- ]Aside\b|\b100%\s+small\s+business\b",
     "Total Small Business", 90),
    # ---- certifications / compliance frameworks ----
    ("certification", "cmmc", r"\bCMMC\b[^.\n]{0,40}?\bLevel\s*([123])\b", None, 95),
    ("certification", "cmmc_bare", r"\bCMMC\b", "CMMC (level unstated)", 75),
    ("certification", "fedramp",
     r"\bFedRAMP\b\s*(High|Moderate|Low)?", "FedRAMP", 90),
    ("certification", "nist_800_171", r"\bNIST\s+SP\s?800[-\s]?171\b",
     "NIST SP 800-171", 90),
    ("certification", "iso9001", r"\bISO\s?9001\b", "ISO 9001", 90),
    ("certification", "cmmi", r"\bCMMI\b[^.\n]{0,30}?\bLevel\s*([1-5])\b", None, 85),
    ("certification", "section_508", r"\bSection\s+508\b", "Section 508", 80),
    # ---- labor / wage regimes ----
    ("wage", "sca", r"\bService\s+Contract\s+(?:Act|Labor\s+Standards)\b|\bSCA\b",
     "Service Contract Act", 85),
    ("wage", "davis_bacon", r"\bDavis[-\s]?Bacon\b", "Davis-Bacon", 90),
    # ---- evaluation approach ----
    ("evaluation", "lpta",
     r"\bLPTA\b|\bLowest\s+Price\s+Technically\s+Acceptable\b",
     "LPTA (lowest price technically acceptable)", 90),
    ("evaluation", "best_value",
     r"\bBest\s+Value\s+Trade[- ]?off\b|\btrade[- ]?off\s+process\b",
     "Best value tradeoff", 85),
    ("evaluation", "past_performance",
     r"\bpast\s+performance\b[^.\n]{0,60}\b(?:factor|evaluat|referenc)",
     "Past performance evaluated", 75),
    # ---- proposal mechanics ----
    ("submission", "page_limit",
     r"\b(?:not\s+exceed|limited\s+to|maximum\s+of)\s+(\d{1,3})\s+pages\b", None, 85),
    ("submission", "sam_registration",
     r"\bactive\s+registration\s+in\s+SAM\b|\bregistered\s+in\s+SAM\.gov\b",
     "Active SAM.gov registration", 85),
    ("submission", "oral_presentation", r"\boral\s+presentations?\b",
     "Oral presentation required", 80),
    # ---- personnel & performance ----
    ("personnel", "key_personnel", r"\bkey\s+personnel\b", "Key personnel required", 80),
    ("personnel", "citizenship",
     r"\bU\.?S\.?\s+citizen(?:ship)?\s+(?:is\s+)?(?:required|only)\b",
     "US citizenship required", 90),
    ("place", "on_site",
     r"\bon[-\s]?site\s+(?:work|presence|support)\s+(?:is\s+)?required\b",
     "On-site presence required", 85),
    # ---- deliverables ----
    ("deliverable", "cdrl", r"\bCDRLs?\b|\bContract\s+Data\s+Requirements\s+List\b",
     "CDRLs specified", 85),
    ("deliverable", "monthly_status",
     r"\bmonthly\s+(?:status|progress)\s+report", "Monthly status report", 80),
    # ---- bonding (construction) ----
    ("bonding", "performance_bond", r"\bperformance\s+bond\b", "Performance bond", 90),
    ("bonding", "bid_bond", r"\bbid\s+bond\b", "Bid bond", 90),
]

_COMPILED = [(rtype, name, re.compile(pattern, re.IGNORECASE), value, conf)
             for rtype, name, pattern, value, conf in RULES]

_MORE_SPECIFIC = {           # if the key fired, drop the listed weaker hits
    "TS/SCI": {"Top Secret", "Secret"},
    "Top Secret": {"Secret"},
}


def _quote(text: str, start: int, end: int, width: int = 160) -> str:
    """A short, single-line excerpt around the match (the evidence)."""
    left = max(0, start - width // 2)
    right = min(len(text), end + width // 2)
    excerpt = text[left:right].replace("\n", " ").replace("\r", " ")
    return re.sub(r"\s+", " ", excerpt).strip()


def extract_requirements(pages: list[tuple[int, str]]) -> list[dict]:
    """pages: [(page_number, text)]. Returns deduped requirement dicts."""
    found: dict[tuple[str, str], dict] = {}
    for page_no, page_text in pages or []:
        if not page_text:
            continue
        for rtype, name, pattern, value, confidence in _COMPILED:
            for match in pattern.finditer(page_text):
                if value is None:
                    group = match.group(1) if match.groups() else match.group(0)
                    normalized = _normalize(name, group, match.group(0))
                else:
                    normalized = value
                key = (rtype, normalized)
                if key in found:
                    continue
                found[key] = {
                    "requirement_type": rtype,
                    "value": normalized,
                    "evidence_quote": _quote(page_text, match.start(), match.end()),
                    "page": page_no,
                    "method": name,
                    "confidence": confidence,
                }
                break            # first hit per rule per page is enough
    return _suppress_weaker(list(found.values()))


def _normalize(rule: str, group: str, whole: str) -> str:
    group = (group or "").strip()
    if rule == "cmmc":
        return f"CMMC Level {group}"
    if rule == "cmmi":
        return f"CMMI Level {group}"
    if rule == "page_limit":
        return f"{group}-page limit"
    if rule == "cio_sp":
        return re.sub(r"\s+", "", whole.upper()).replace("CIOSP", "CIO-SP")
    return whole.strip()


def _suppress_weaker(rows: list[dict]) -> list[dict]:
    """Keep the strongest clearance/cert claim; never show a blurred tier."""
    values = {r["value"] for r in rows}
    drop = set()
    for strong, weaker in _MORE_SPECIFIC.items():
        if strong in values:
            drop |= weaker
    if any(v.startswith("CMMC Level") for v in values):
        drop.add("CMMC (level unstated)")
    return sorted((r for r in rows if r["value"] not in drop),
                  key=lambda r: (r["requirement_type"], -r["confidence"], r["value"]))


def classify_document(filename: str, text: str) -> str:
    """Best-effort document kind from filename and opening text."""
    name = (filename or "").lower()
    head = (text or "")[:2000].lower()
    for token, kind in (("pws", "pws"), ("sow", "sow"), ("statement of work", "sow"),
                        ("performance work statement", "pws"), ("amendment", "amendment"),
                        ("q&a", "qa"), ("questions", "qa"), ("pricing", "pricing"),
                        ("schedule b", "pricing"), ("rfp", "rfp"), ("rfq", "rfp"),
                        ("solicitation", "rfp")):
        if token in name or token in head:
            return kind
    return "other"
