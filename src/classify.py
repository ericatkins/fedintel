"""Deterministic classifier and lead scorer with explainable components.

Phase 1 (this file): cheap deterministic rules — no network, no AI.
Phase 2 (post-MVP): LLM second pass only on records above a floor.
The pipeline must produce a complete, useful digest even if Phase 2 never runs.

Output contract:
    {
      "category": str,
      "score": int 0-100,
      "components": {keyword, naics, stage, deadline, geography,
                     set_aside, profile_match, semantic, negative},
      "reasons": [str],
      "keywords_matched": [str],
      "recommended_action": str,
    }
Component scores are stored as JSON so any UI can explain the match.
"""
import re
from datetime import datetime, timedelta, timezone

SOFTWARE_NAICS = {"541511", "541512", "541513", "541519", "518210"}

KEYWORD_CATEGORIES = {
    "Custom Software / App Development": [
        "software development", "application development", "web application",
        "custom software", "software engineering", "agile development", "low code",
        "power platform", "sharepoint", "mobile application",
    ],
    "Database / Data Management": [
        "database", "data management", "data migration", "data warehouse",
        "data pipeline", "data governance", "etl",
    ],
    "Inventory / Asset / Logistics Tools": [
        "inventory management", "asset management", "logistics system",
        "supply chain system", "property management system", "tracking system",
    ],
    "Configuration Management / PLM / ALM": [
        "configuration management", "cmdb", "product lifecycle", "plm", "alm",
        "change management system", "baseline management",
    ],
    "DevSecOps / Cloud / Platform": [
        "devsecops", "devops", "cloud migration", "kubernetes", "containerization",
        "platform engineering", "ci/cd", "cloud native", "infrastructure as code",
    ],
    "Modeling / Simulation / Digital Engineering": [
        "modeling and simulation", "digital engineering", "mbse", "digital twin",
        "mosa", "model based",
    ],
    "AI / ML / Automation": [
        "artificial intelligence", "machine learning", "ai/ml", "automation",
        "workflow automation", "rpa", "predictive analytics", "llm",
    ],
    "Cyber Software Tools": [
        "cyber tool", "cybersecurity software", "security automation",
        "vulnerability management", "zero trust",
    ],
    "Enterprise IT": [
        "enterprise it", "help desk", "it support services", "system administration",
        "network operations",
    ],
}

NEGATIVE_PATTERNS = [
    (r"\baward notice\b|\bjustification\b", -25, "award/justification notice"),
    (r"\bstaff augmentation\b|\bbody shop\b|\bpersonnel services\b", -20, "staffing-only"),
    (r"\bhardware only\b|\bequipment purchase\b|\bfurniture\b|\bjanitorial\b|\bconstruction of\b",
     -20, "non-software effort"),
    (r"\bincumbent\b.{0,40}\brecompete\b", -15, "incumbent-favored recompete"),
]

SOFT_SIGNAL_PATTERNS = [
    (r"\bmodernization\b|\blegacy (system|application|software)\b", 15, "legacy modernization signal"),
    (r"\bworkflow\b|\bdashboard\b|\breporting tool\b|\buser interface\b", 10, "tooling/workflow problem"),
    (r"\bapi\b|\bintegration\b|\binteroperab", 8, "integration work"),
]

EARLY_STAGE_TYPES = ("sources sought", "special notice", "presolicitation")

_WORD = re.compile(r"[a-z0-9][a-z0-9/+.-]*")
_STOPWORDS = {
    "the", "and", "for", "with", "will", "shall", "this", "that", "are", "from",
    "any", "all", "into", "such", "not", "may", "its", "per", "via",
}


def _tokens(text: str) -> set[str]:
    return {t for t in _WORD.findall(text.lower()) if len(t) > 2 and t not in _STOPWORDS}


def _semantic_overlap(opp_text: str, profile: dict) -> float:
    """Cheap deterministic 'semantic' proxy: token overlap between the
    opportunity text and the profile's capabilities/technologies/industries.
    Returns 0..1. Replaced by embeddings in the AI second pass, same slot."""
    profile_text = " ".join(
        profile.get("capabilities", []) + profile.get("technologies", []) + profile.get("industries", [])
    )
    p, o = _tokens(profile_text), _tokens(opp_text)
    if not p or not o:
        return 0.0
    return len(p & o) / len(p)


def _recommended_action(notice_type: str, days_left, score: int) -> str:
    nt = (notice_type or "").lower()
    if "sources sought" in nt:
        return "Respond to shape the requirement and get on the agency's radar."
    if "presolicitation" in nt or "special notice" in nt:
        return "Monitor and prepare capability statement before the RFP drops."
    if days_left is not None and days_left <= 3:
        return "Deadline imminent — go/no-go decision today."
    if score >= 80:
        return "Strong fit — begin bid/no-bid review and draft outline."
    if score >= 60:
        return "Review requirements; decide whether to track."
    return "Low priority — skim only."


def classify(opp: dict, profile: dict | None = None) -> dict:
    """Score an opportunity. `profile` personalizes; None means neutral."""
    profile = profile or {}
    text = f"{opp.get('title', '')} {opp.get('description_text', '')}".lower()
    title = (opp.get("title") or "").lower()
    reasons: list[str] = []
    comp = {k: 0 for k in (
        "keyword", "naics", "stage", "deadline", "geography",
        "set_aside", "profile_match", "semantic", "negative",
    )}

    # --- keyword / category ---
    best_cat, best_hits = "Uncategorized", 0
    for cat, kws in KEYWORD_CATEGORIES.items():
        hits = sum(2 if kw in title else 1 for kw in kws if kw in text)
        if hits > best_hits:
            best_cat, best_hits = cat, hits
    title_kw = any(kw in title for kws in KEYWORD_CATEGORIES.values() for kw in kws)
    if title_kw:
        comp["keyword"] = 25
        reasons.append("software keywords in title")
    elif best_hits:
        comp["keyword"] = 12
        reasons.append("software keywords in description")
    matched = sorted({kw for kws in KEYWORD_CATEGORIES.values() for kw in kws if kw in text})
    category = best_cat if best_hits else "Uncategorized"

    # --- NAICS ---
    naics = (opp.get("naics") or "")[:6]
    if naics in SOFTWARE_NAICS:
        comp["naics"] = 20
        reasons.append(f"software NAICS {naics}")

    # --- notice stage ---
    ntype = (opp.get("notice_type") or "").lower()
    if any(t in ntype for t in EARLY_STAGE_TYPES):
        comp["stage"] = 10
        reasons.append("early-stage notice (shape the requirement)")

    # --- deadline / urgency ---
    days_left = None
    deadline = opp.get("response_deadline")
    if deadline is not None:
        now = datetime.now(timezone.utc)
        dl = deadline if deadline.tzinfo else deadline.replace(tzinfo=timezone.utc)
        days_left = (dl - now).days
        if dl - now > timedelta(days=7):
            comp["deadline"] = 5
            reasons.append("deadline >7 days out")

    # --- geography ---
    pop = (opp.get("place_of_performance") or "").lower()
    agency = (opp.get("agency") or "").lower()
    home_hit = any(loc in pop for loc in (profile.get("locations") or ["huntsville", "redstone"]))
    dod_hit = any(t in agency for t in ("army", "defense", "air force", "navy", "darpa"))
    if home_hit or dod_hit:
        comp["geography"] = 10
        reasons.append("geography/agency relevance")

    # --- set-aside ---
    set_aside = (opp.get("set_aside") or "").lower()
    eligibility = [e.lower() for e in profile.get("set_aside_eligibility", [])] or [
        "small business", "sba", "8(a)"
    ]
    if set_aside and any(e in set_aside for e in eligibility):
        comp["set_aside"] = 10
        reasons.append("set-aside matches eligibility")

    # --- explicit profile match ---
    pm = 0
    if naics and naics in set(profile.get("naics_codes", [])):
        pm += 6
        reasons.append("NAICS in company profile")
    if any(a.lower() in agency for a in profile.get("agencies_of_interest", [])):
        pm += 5
        reasons.append("agency of interest")
    boosts = [k for k in profile.get("keywords_boost", []) if k.lower() in text]
    if boosts:
        pm += min(6, 3 * len(boosts))
        reasons.append(f"profile boost keywords: {', '.join(boosts[:3])}")
    suppress = [k for k in profile.get("keywords_suppress", []) if k.lower() in text]
    if suppress:
        pm -= min(15, 8 * len(suppress))
        reasons.append(f"profile suppress keywords: {', '.join(suppress[:3])}")
    if category in set(profile.get("excluded_categories", [])):
        pm -= 25
        reasons.append(f"category excluded by profile: {category}")
    comp["profile_match"] = pm

    # --- semantic (deterministic proxy; AI pass will replace this slot) ---
    sem = round(10 * _semantic_overlap(text, profile))
    if sem:
        comp["semantic"] = sem
        reasons.append("overlaps company capabilities")

    # --- soft signals + negatives ---
    for pattern, delta, why in SOFT_SIGNAL_PATTERNS:
        if re.search(pattern, text):
            comp["keyword"] += delta
            reasons.append(why)
    for pattern, delta, why in NEGATIVE_PATTERNS:
        if re.search(pattern, text):
            comp["negative"] += delta
            reasons.append(why)

    score = max(0, min(100, sum(comp.values())))
    return {
        "category": category,
        "score": score,
        "components": comp,
        "reasons": reasons,
        "keywords_matched": matched,
        "recommended_action": _recommended_action(opp.get("notice_type"), days_left, score),
    }
