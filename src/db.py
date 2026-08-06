"""Postgres persistence (Supabase). Upserts, change detection, digest state.

Change detection is a pure function (diff_opportunity) so it's unit-testable
without a database.
"""
import json

import psycopg2

from .config import DATABASE_URL, require

# Fields updated on amendment, in stable order (used by both the diff and the UPDATE)
MUTABLE_FIELDS = (
    "title", "agency", "office", "office_location", "notice_type", "naics", "set_aside",
    "posted_date", "response_deadline", "place_of_performance",
    "description_text", "url",
)

# Static SQL, written out literally so no query is ever assembled from variables.
# The import-time assertions below keep these in lockstep with MUTABLE_FIELDS.
_SELECT_EXISTING_SQL = """
    select id, content_hash,
           title, agency, office, office_location, notice_type, naics, set_aside,
           posted_date, response_deadline, place_of_performance,
           description_text, url
    from opportunities where source=%s and source_notice_id=%s"""

_UPDATE_MUTABLE_SQL = """
    update opportunities set
           title=%s, agency=%s, office=%s, office_location=%s, notice_type=%s, naics=%s, set_aside=%s,
           posted_date=%s, response_deadline=%s, place_of_performance=%s,
           description_text=%s, url=%s,
           raw_json=%s, content_hash=%s, last_seen_at=now()
    where id=%s"""

for _f in MUTABLE_FIELDS:
    if _f not in _SELECT_EXISTING_SQL or f"{_f}=%s" not in _UPDATE_MUTABLE_SQL:
        raise RuntimeError(f"MUTABLE_FIELDS out of sync with static SQL: {_f}")

# field -> specific change event type (everything else folds into 'amended' detail)
EVENT_FOR_FIELD = {
    "response_deadline": "deadline_changed",
    "notice_type": "stage_changed",
    "url": "url_changed",
    "title": "title_changed",
}


def get_conn():
    return psycopg2.connect(DATABASE_URL or require("DATABASE_URL"))


def diff_opportunity(old: dict, new: dict) -> list[dict]:
    """Compare stored row vs normalized record. Returns change events:
    [{'event_type': ..., 'detail': {field, old, new}}, ...]. Pure function."""
    events = []
    for field in MUTABLE_FIELDS:
        ov, nv = old.get(field), new.get(field)
        if ov != nv:
            events.append({
                "event_type": EVENT_FOR_FIELD.get(field, "amended"),
                "detail": {"field": field, "old": _jsonable(ov), "new": _jsonable(nv)},
            })
    return events


def _jsonable(v):
    return v.isoformat() if hasattr(v, "isoformat") else v


def upsert_opportunity(cur, opp: dict) -> tuple[int, str, list[dict]]:
    """Insert or update. Returns (opportunity_id, status, change_events)
    where status is 'new' | 'amended' | 'unchanged'."""
    cur.execute(
        _SELECT_EXISTING_SQL,
        (opp["source"], opp["source_notice_id"]),
    )
    row = cur.fetchone()

    if row is None:
        cur.execute(
            """insert into opportunities
               (source, source_notice_id, solicitation_number, title, agency, office,
                office_location, jurisdiction, notice_type, naics, set_aside, posted_date,
                response_deadline, place_of_performance, description_text, url, raw_json,
                content_hash)
               values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
               returning id""",
            (
                opp["source"], opp["source_notice_id"], opp["solicitation_number"],
                opp["title"], opp["agency"], opp["office"], opp["office_location"],
                opp["jurisdiction"], opp["notice_type"], opp["naics"], opp["set_aside"],
                opp["posted_date"], opp["response_deadline"], opp["place_of_performance"],
                opp["description_text"], opp["url"], json.dumps(opp["raw_json"]),
                opp["content_hash"],
            ),
        )
        opp_id = cur.fetchone()[0]
        events = [{"event_type": "new", "detail": {}}]
        _record_events(cur, opp_id, events)
        _record_lineage(cur, opp, opp_id)
        return opp_id, "new", events

    opp_id, old_hash = row[0], row[1]
    old = dict(zip(MUTABLE_FIELDS, row[2:], strict=True))

    if old_hash == opp["content_hash"]:
        cur.execute("update opportunities set last_seen_at=now() where id=%s", (opp_id,))
        return opp_id, "unchanged", []

    events = diff_opportunity(old, opp) or [
        {"event_type": "amended", "detail": {"note": "content hash changed"}}
    ]
    old_rank = _stage_rank(old.get("notice_type"))
    new_rank = _stage_rank(opp.get("notice_type"))
    if new_rank > old_rank > 0:
        events.append({"event_type": "stage_transition",
                       "detail": {"solicitation_number": opp.get("solicitation_number"),
                                  "from": old.get("notice_type"),
                                  "to": opp.get("notice_type"), "via": "amendment"}})
    cur.execute(
        _UPDATE_MUTABLE_SQL,
        tuple(opp[f] for f in MUTABLE_FIELDS)
        + (json.dumps(opp["raw_json"]), opp["content_hash"], opp_id),
    )
    # If a tracked opportunity changed, add the high-value event too
    cur.execute("select 1 from tracked_opportunities where opportunity_id=%s limit 1", (opp_id,))
    if cur.fetchone():
        events.append({"event_type": "tracked_opportunity_changed",
                       "detail": {"changes": [e["event_type"] for e in events]}})
    _record_events(cur, opp_id, events)
    return opp_id, "amended", events


def _record_events(cur, opp_id: int, events: list[dict]):
    for ev in events:
        cur.execute(
            "insert into change_events (opportunity_id, event_type, detail) values (%s,%s,%s)",
            (opp_id, ev["event_type"], json.dumps(ev["detail"])),
        )


# Notice-type ordering for lifecycle transitions (higher = later stage)
STAGE_ORDER = {
    "sources sought": 1, "special notice": 1, "request for information": 1,
    "presolicitation": 2, "solicitation": 3, "combined synopsis/solicitation": 3,
    "award notice": 5, "justification": 5,
}


def _stage_rank(notice_type: str | None) -> int:
    nt = (notice_type or "").lower()
    for key, rank in STAGE_ORDER.items():
        if key in nt:
            return rank
    return 0


def _record_lineage(cur, opp: dict, opp_id: int):
    """Record lineage and detect stage transitions (the highest-value alert:
    'an opportunity you saw early just became real')."""
    solnum = opp.get("solicitation_number")
    if not solnum:
        return
    stage = opp.get("notice_type") or "unknown"
    cur.execute(
        """select stage from opportunity_lineage
           where solicitation_number=%s and opportunity_id<>%s
           order by linked_at desc limit 5""",
        (solnum, opp_id))
    prior_stages = [r[0] for r in cur.fetchall()]
    cur.execute(
        "insert into opportunity_lineage (solicitation_number, opportunity_id, stage) values (%s,%s,%s)",
        (solnum, opp_id, stage))
    new_rank = _stage_rank(stage)
    for prior in prior_stages:
        if new_rank > _stage_rank(prior) and _stage_rank(prior) > 0:
            _record_events(cur, opp_id, [{
                "event_type": "stage_transition",
                "detail": {"solicitation_number": solnum, "from": prior, "to": stage},
            }])
            break


def save_classification(cur, opp_id: int, result: dict):
    cur.execute(
        """insert into classifications
             (opportunity_id, category, score, confidence, reasons, keywords_matched, components,
              recommended_action)
           values (%s,%s,%s,'rules',%s,%s,%s,%s)
           on conflict (opportunity_id) do update
             set category=excluded.category, score=excluded.score,
                 reasons=excluded.reasons, keywords_matched=excluded.keywords_matched,
                 components=excluded.components, recommended_action=excluded.recommended_action,
                 classified_at=now()""",
        (
            opp_id, result["category"], result["score"],
            json.dumps(result["reasons"]), json.dumps(result["keywords_matched"]),
            json.dumps(result["components"]), result.get("recommended_action"),
        ),
    )


DIGEST_ROW_COLS = (
    "id", "title", "agency", "notice_type", "naics", "set_aside",
    "response_deadline", "url", "source_notice_id", "place_of_performance",
    "category", "score", "reasons", "components", "recommended_action", "first_seen_at",
    "similar_work", "incumbent_analysis", "recommendation",
)


PER_ORG_DIGEST_SQL = """
    select o.id, o.title, o.agency, o.notice_type, o.naics, o.set_aside,
           o.response_deadline, o.url, o.source_notice_id, o.place_of_performance,
           coalesce(m.category, c.category),
           coalesce(m.final_match_score, c.score, 0),
           coalesce(m.match_reasons_json, c.reasons, '[]'::jsonb),
           coalesce(m.score_components_json, c.components, '{}'::jsonb),
           coalesce(m.recommendation, c.recommended_action),
           o.first_seen_at,
           d.similar_work_json, d.incumbent_analysis_json, d.pursuit_recommendation_json
    from opportunities o
    left join classifications c on c.opportunity_id = o.id
    left join profile_opportunity_matches m
           on m.opportunity_id = o.id and m.organization_id = %s and not m.hidden
    left join opportunity_dossiers d on d.opportunity_id = o.id
    where (o.first_seen_at at time zone %s)::date = %s
      and coalesce(m.final_match_score, c.score, 0) >= %s
    order by coalesce(m.final_match_score, c.score, 0) desc
    limit 60"""


def fetch_digest_rows_for_org(cur, org_id: int, tz_name: str, for_date, min_score: int):
    """Digest rows scored for ONE organization: per-org match when it exists,
    global classification as the fallback."""
    cur.execute(PER_ORG_DIGEST_SQL, (org_id, tz_name, for_date, min_score))
    return [dict(zip(DIGEST_ROW_COLS, row, strict=True)) for row in cur.fetchall()]


def fetch_digest_rows(cur, digest_date, min_score: int, tz):
    cur.execute(
        """select o.id, o.title, o.agency, o.notice_type, o.naics, o.set_aside,
                  o.response_deadline, o.url, o.source_notice_id, o.place_of_performance,
                  c.category, c.score, c.reasons, c.components, c.recommended_action, o.first_seen_at,
                  d.similar_work_json, d.incumbent_analysis_json, d.pursuit_recommendation_json
           from opportunities o
           join classifications c on c.opportunity_id = o.id
           left join opportunity_dossiers d on d.opportunity_id = o.id
           where (o.first_seen_at at time zone %s)::date = %s and c.score >= %s
           order by c.score desc
           limit 60""",
        (str(tz), digest_date, min_score),
    )
    return [dict(zip(DIGEST_ROW_COLS, r, strict=True)) for r in cur.fetchall()]


def fetch_tracked_amendments(cur, digest_date, tz):
    """Tracked opportunities that changed today, with their change events."""
    cur.execute(
        """select o.id, o.title, o.agency, o.notice_type, o.naics, o.set_aside,
                  o.response_deadline, o.url, o.source_notice_id, o.place_of_performance,
                  coalesce(c.category,'—'), coalesce(c.score,0), coalesce(c.reasons,'[]'::jsonb),
                  coalesce(c.components,'{}'::jsonb), c.recommended_action, o.first_seen_at,
                  jsonb_agg(jsonb_build_object('event_type', e.event_type, 'detail', e.detail))
           from change_events e
           join opportunities o on o.id = e.opportunity_id
           join tracked_opportunities t on t.opportunity_id = o.id
           left join classifications c on c.opportunity_id = o.id
           where (e.created_at at time zone %s)::date = %s
             and e.event_type <> 'new'
           group by o.id, c.category, c.score, c.reasons, c.components, c.recommended_action
           order by max(e.created_at) desc
           limit 20""",
        (str(tz), digest_date),
    )
    cols = DIGEST_ROW_COLS + ("changes",)
    return [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]


# --- digest send-state (only sent_at means the provider confirmed) ---

def digest_already_sent(cur, digest_date) -> bool:
    cur.execute("select sent_at from email_digests where digest_date=%s", (digest_date,))
    row = cur.fetchone()
    return bool(row and row[0])


def record_digest_generated(cur, digest_date, count: int, top_score, html: str) -> int:
    cur.execute(
        """insert into email_digests (digest_date, generated_at, opportunity_count, top_score, html_body)
           values (%s, now(), %s, %s, %s)
           on conflict (digest_date) do update
             set generated_at=now(), opportunity_count=excluded.opportunity_count,
                 top_score=excluded.top_score, html_body=excluded.html_body
           returning id""",
        (digest_date, count, top_score, html),
    )
    return cur.fetchone()[0]


def record_send_result(cur, digest_id: int, ok: bool, provider_message_id: str | None,
                       error: str | None):
    if ok:
        cur.execute(
            """update email_digests set send_attempted_at=now(), sent_at=now(),
               send_status='sent', send_error=null, provider_message_id=%s where id=%s""",
            (provider_message_id, digest_id),
        )
    else:
        cur.execute(
            """update email_digests set send_attempted_at=now(),
               send_status='failed', send_error=%s where id=%s""",
            (error, digest_id),
        )
    cur.execute(
        """insert into digest_delivery_events (digest_id, status, provider_message_id, error)
           values (%s,%s,%s,%s)""",
        (digest_id, "sent" if ok else "failed", provider_message_id, error),
    )


def save_feedback(cur, opportunity_id: int, action: str, user_email: str | None = None):
    cur.execute(
        """insert into opportunity_feedback (opportunity_id, action, user_email)
           values (%s,%s,%s)""",
        (opportunity_id, action, user_email),
    )
