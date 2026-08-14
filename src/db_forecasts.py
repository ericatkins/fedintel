"""Persistence for procurement forecasts and forecast-opportunity links."""
import json

from .intel.forecast_link import link_forecasts
from .log import log

_COLS = ("source", "source_record_id", "agency", "subtier", "office", "title",
         "description", "naics", "psc", "estimated_value_low",
         "estimated_value_high", "action_type", "incumbent_name",
         "contract_vehicle", "set_aside", "anticipated_solicitation",
         "anticipated_award", "fiscal_year", "place_of_performance",
         "point_of_contact", "source_url")


def upsert_forecast(cur, rec: dict) -> int:
    cur.execute(
        """insert into procurement_forecasts
             (source, source_record_id, agency, subtier, office, title,
              description, naics, psc, estimated_value_low,
              estimated_value_high, action_type, incumbent_name,
              contract_vehicle, set_aside, anticipated_solicitation,
              anticipated_award, fiscal_year, place_of_performance,
              point_of_contact, source_url, raw_json, content_hash)
           values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                   %s,%s,%s,%s)
           on conflict (source, source_record_id) do update set
             agency=excluded.agency, subtier=excluded.subtier,
             office=excluded.office, title=excluded.title,
             description=excluded.description, naics=excluded.naics,
             psc=excluded.psc,
             estimated_value_low=excluded.estimated_value_low,
             estimated_value_high=excluded.estimated_value_high,
             action_type=excluded.action_type,
             incumbent_name=excluded.incumbent_name,
             contract_vehicle=excluded.contract_vehicle,
             set_aside=excluded.set_aside,
             anticipated_solicitation=excluded.anticipated_solicitation,
             anticipated_award=excluded.anticipated_award,
             fiscal_year=excluded.fiscal_year,
             place_of_performance=excluded.place_of_performance,
             point_of_contact=excluded.point_of_contact,
             source_url=excluded.source_url,
             raw_json=excluded.raw_json,
             content_hash=excluded.content_hash,
             last_seen_at=now()
           returning id""",
        tuple(rec.get(c) for c in _COLS)
        + (json.dumps(rec.get("raw_json") or {}, default=str),
           rec["content_hash"]))
    return cur.fetchone()[0]


def _load_active_forecasts(cur, limit: int = 2000) -> list[dict]:
    cur.execute(
        """select id, source, source_record_id, agency, subtier, office, title,
                  description, naics, psc, estimated_value_low,
                  estimated_value_high, action_type, incumbent_name,
                  contract_vehicle, set_aside, anticipated_solicitation,
                  anticipated_award, fiscal_year, place_of_performance,
                  point_of_contact, source_url
           from procurement_forecasts
           where status='active' order by last_seen_at desc limit %s""",
        (limit,))
    cols = ("id",) + _COLS
    return [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]


def link_recent_opportunities(conn, lookback_days: int = 30,
                              limit: int = 500) -> int:
    """Nightly pass: match recent opportunities against active forecasts and
    store above-threshold links with evidence."""
    written = 0
    with conn.cursor() as cur:
        forecasts = _load_active_forecasts(cur)
        if not forecasts:
            return 0
        cur.execute(
            """select id, title, agency, office, naics, posted_date,
                      description_text
               from opportunities
               where first_seen_at > now() - make_interval(days => %s)
               order by first_seen_at desc limit %s""",
            (lookback_days, limit))
        cols = ("id", "title", "agency", "office", "naics", "posted_date",
                "description_text")
        opps = [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]
        for opp in opps:
            for ln in link_forecasts(opp, forecasts)[:5]:
                cur.execute(
                    """insert into opportunity_forecast_links
                         (opportunity_id, forecast_id, similarity_score,
                          confidence, evidence_json)
                       values (%s,%s,%s,%s,%s)
                       on conflict (opportunity_id, forecast_id) do update set
                         similarity_score=excluded.similarity_score,
                         confidence=excluded.confidence,
                         evidence_json=excluded.evidence_json""",
                    (opp["id"], ln["forecast"]["id"], ln["similarity_score"],
                     ln["confidence"], json.dumps(ln["evidence"])))
                written += 1
    conn.commit()
    log("forecast_links_refreshed", links=written, forecasts=len(forecasts))
    return written


def refresh_apfs(conn, max_pages: int = 10) -> int:
    """Pull DHS APFS forecasts. Failure-isolated: a blocked or changed API
    logs and returns 0 without touching existing rows."""
    from .adapters.forecasts import ForecastError, fetch_apfs
    written = 0
    try:
        with conn.cursor() as cur:
            for rec in fetch_apfs(max_pages=max_pages):
                upsert_forecast(cur, rec)
                written += 1
        conn.commit()
        log("apfs_refreshed", records=written)
    except ForecastError as exc:
        conn.rollback()
        log("apfs_refresh_skipped", error=str(exc))
    return written


def import_forecast_csv(conn, path: str) -> int:
    """Operator CSV import; every row carries provenance or the file fails."""
    from .adapters.forecasts import parse_forecast_csv
    written = 0
    with conn.cursor() as cur:
        for rec in parse_forecast_csv(path):
            upsert_forecast(cur, rec)
            written += 1
    conn.commit()
    log("forecast_csv_imported", records=written, path=path)
    return written
