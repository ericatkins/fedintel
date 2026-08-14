"""Persistence for the grants vertical."""
import json

from .log import log

_COLS = ("source", "source_grant_id", "opportunity_number", "title",
         "agency_code", "agency_name", "opportunity_status", "posted_date",
         "close_date", "award_floor", "award_ceiling", "expected_awards",
         "total_funding", "funding_instrument", "category", "cost_sharing",
         "description_text", "source_url")


def upsert_grant(cur, rec: dict) -> int:
    cur.execute(
        """insert into grant_opportunities
             (source, source_grant_id, opportunity_number, title, agency_code,
              agency_name, opportunity_status, posted_date, close_date,
              award_floor, award_ceiling, expected_awards, total_funding,
              funding_instrument, category, cost_sharing, description_text,
              source_url, assistance_listings, eligible_applicants, raw_json,
              content_hash)
           values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                   %s,%s,%s,%s)
           on conflict (source, source_grant_id) do update set
             opportunity_number=excluded.opportunity_number,
             title=excluded.title, agency_code=excluded.agency_code,
             agency_name=excluded.agency_name,
             opportunity_status=excluded.opportunity_status,
             posted_date=excluded.posted_date, close_date=excluded.close_date,
             award_floor=excluded.award_floor,
             award_ceiling=excluded.award_ceiling,
             expected_awards=excluded.expected_awards,
             total_funding=excluded.total_funding,
             funding_instrument=excluded.funding_instrument,
             category=excluded.category, cost_sharing=excluded.cost_sharing,
             description_text=excluded.description_text,
             source_url=excluded.source_url,
             assistance_listings=excluded.assistance_listings,
             eligible_applicants=excluded.eligible_applicants,
             raw_json=excluded.raw_json, content_hash=excluded.content_hash,
             last_seen_at=now()
           returning id""",
        tuple(rec.get(c) or None for c in _COLS)
        + (json.dumps(rec.get("assistance_listings") or []),
           json.dumps(rec.get("eligible_applicants") or []),
           json.dumps(rec.get("raw_json") or {}, default=str),
           rec["content_hash"]))
    return cur.fetchone()[0]


def refresh_grants(conn, keyword: str | None = None, max_pages: int = 5) -> int:
    """Pull posted + forecasted grants. Failure-isolated: a blocked or changed
    API logs and returns 0 without touching existing rows."""
    from .adapters.grants_gov import GrantsGovError, search_grants
    written = 0
    try:
        with conn.cursor() as cur:
            for rec in search_grants(keyword=keyword,
                                     statuses="posted|forecasted",
                                     max_pages=max_pages):
                upsert_grant(cur, rec)
                written += 1
        conn.commit()
        log("grants_refreshed", records=written)
    except GrantsGovError as exc:
        conn.rollback()
        log("grants_refresh_skipped", error=str(exc))
    return written
