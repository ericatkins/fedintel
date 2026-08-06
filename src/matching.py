"""Per-organization opportunity matching.

`classifications` stays global (one deterministic base score per opportunity).
`profile_opportunity_matches` is per organization: the same solicitation scores
differently for a software firm vs a fiber contractor, driven by each org's
web-edited company profile. Digest, dashboard, and tables read the per-org
score, falling back to the global score when no profile exists yet.
"""
from .classify import classify
from .log import log

POM_STATUSES = ("new", "saved", "watching", "researching", "pursuing",
                "submitted", "won", "lost", "ignored")


def load_active_company_profiles(cur) -> list[dict]:
    """One (org, profile) pair per organization — most recently updated wins."""
    cur.execute(
        """select distinct on (cp.organization_id)
                  cp.organization_id, cp.id, cp.profile
           from company_profiles cp
           join organizations o on o.id = cp.organization_id
           order by cp.organization_id, cp.updated_at desc""")
    return [{"org_id": r[0], "profile_id": r[1], "profile": r[2] or {}}
            for r in cur.fetchall()]


def score_opportunity_for_profile(opp: dict, profile: dict) -> dict:
    """Deterministic per-profile scoring. Reuses the classifier with the org's
    profile so base rules and profile boosts stay in one engine."""
    return classify(opp, profile or {})


def upsert_profile_opportunity_match(cur, org_id: int, profile_id: int | None,
                                     opportunity_id: int, base_score: int | None,
                                     result: dict):
    cur.execute(
        """insert into profile_opportunity_matches
             (organization_id, company_profile_id, opportunity_id,
              base_classification_score, profile_match_score, final_match_score,
              confidence, category, recommendation, match_reasons_json,
              score_components_json, updated_at)
           values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,now())
           on conflict (organization_id, opportunity_id) do update set
             company_profile_id=excluded.company_profile_id,
             base_classification_score=excluded.base_classification_score,
             profile_match_score=excluded.profile_match_score,
             final_match_score=excluded.final_match_score,
             confidence=excluded.confidence,
             category=excluded.category,
             recommendation=excluded.recommendation,
             match_reasons_json=excluded.match_reasons_json,
             score_components_json=excluded.score_components_json,
             updated_at=now()""",
        (org_id, profile_id, opportunity_id, base_score,
         result.get("score", 0), max(0, min(100, result.get("score", 0))),
         result.get("confidence"), result.get("category"),
         result.get("recommended_action"),
         _json(result.get("reasons", [])), _json(result.get("components", {}))))


def _json(value):
    import json
    return json.dumps(value)


_RECENT_OPPS_SQL = """
    select o.id, o.title, o.agency, o.office, o.notice_type, o.naics, o.set_aside,
           o.solicitation_number, o.response_deadline, o.place_of_performance,
           o.description_text, o.url, o.source_notice_id, c.score
    from opportunities o
    left join classifications c on c.opportunity_id = o.id
    where o.first_seen_at > now() - make_interval(days => %s)
    order by o.first_seen_at desc limit %s"""

_OPP_COLS = ("id", "title", "agency", "office", "notice_type", "naics", "set_aside",
             "solicitation_number", "response_deadline", "place_of_performance",
             "description_text", "url", "source_notice_id", "base_score")


def _load_requirements(cur, opportunity_ids: list[int]) -> dict[int, list[dict]]:
    """Extracted requirements for a batch of opportunities (global facts)."""
    if not opportunity_ids:
        return {}
    cur.execute(
        """select opportunity_id, requirement_type, value, confidence, method,
                  page, evidence_quote
           from document_requirements where opportunity_id = any(%s)""",
        (opportunity_ids,))
    out: dict[int, list[dict]] = {}
    for row in cur.fetchall():
        cols = ("opportunity_id", "requirement_type", "value", "confidence",
                "method", "page", "evidence_quote")
        req = dict(zip(cols, row, strict=True))
        out.setdefault(req["opportunity_id"], []).append(req)
    return out


def _apply_qualification(result: dict, requirements: list[dict],
                         profile: dict) -> dict:
    """Cap the score when documents show the org is barred or gated."""
    if not requirements:
        return result
    from .documents.qualification import apply_to_score, assess
    assessment = assess(requirements, profile)
    capped, notes = apply_to_score(result.get("score", 0), assessment)
    if not notes:
        return result
    result = dict(result)
    result["score"] = capped
    result["reasons"] = list(result.get("reasons", [])) + notes
    return result


def _load_weights(cur, org_id: int) -> dict[str, int]:
    cur.execute("select feature, weight from org_preference_weights "
                "where organization_id=%s", (org_id,))
    return dict(cur.fetchall())


def refresh_profile_matches_for_recent_opportunities(conn, lookback_days: int = 3,
                                                     limit: int = 500) -> int:
    """Nightly: score recent opportunities for every active org profile,
    applying that org's learned preference weights (bounded ±15)."""
    from .learning import apply_learning
    written = 0
    with conn.cursor() as cur:
        profiles = load_active_company_profiles(cur)
        cur.execute(_RECENT_OPPS_SQL, (lookback_days, limit))
        opps = [dict(zip(_OPP_COLS, r, strict=True)) for r in cur.fetchall()]
        requirements = _load_requirements(cur, [o["id"] for o in opps])
        for p in profiles:
            weights = _load_weights(cur, p["org_id"])
            for opp in opps:
                result = score_opportunity_for_profile(opp, p["profile"])
                result = apply_learning(result, {**opp,
                                                 "category": result.get("category")},
                                        weights)
                result = _apply_qualification(result, requirements.get(opp["id"]),
                                              p["profile"])
                upsert_profile_opportunity_match(
                    cur, p["org_id"], p["profile_id"], opp["id"],
                    opp.get("base_score"), result)
                written += 1
    conn.commit()
    log("profile_matches_refreshed", orgs=len(profiles), matches=written)
    return written


def refresh_profile_matches_for_org(conn, org_id: int, lookback_days: int = 14,
                                    limit: int = 1000) -> int:
    """On-demand: after an org edits its profile, rescore their recent view."""
    written = 0
    with conn.cursor() as cur:
        profiles = [p for p in load_active_company_profiles(cur) if p["org_id"] == org_id]
        if not profiles:
            return 0
        cur.execute(_RECENT_OPPS_SQL, (lookback_days, limit))
        opps = [dict(zip(_OPP_COLS, r, strict=True)) for r in cur.fetchall()]
        from .learning import apply_learning
        p = profiles[0]
        weights = _load_weights(cur, org_id)
        requirements = _load_requirements(cur, [o["id"] for o in opps])
        for opp in opps:
            result = score_opportunity_for_profile(opp, p["profile"])
            result = apply_learning(result, {**opp, "category": result.get("category")},
                                    weights)
            result = _apply_qualification(result, requirements.get(opp["id"]),
                                          p["profile"])
            upsert_profile_opportunity_match(cur, org_id, p["profile_id"], opp["id"],
                                             opp.get("base_score"), result)
            written += 1
    conn.commit()
    log("profile_matches_refreshed_org", org_id=org_id, matches=written)
    return written
