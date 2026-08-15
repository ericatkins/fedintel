"""Intelligence enrichment pipeline. Runs SEPARATELY from ingest — the daily
digest must never wait on award/budget APIs.

Run:  python -m src.enrich                           (process pending queue)
Run:  python -m src.enrich --refresh-awards           (weekly: USAspending history)
Run:  python -m src.enrich --refresh-sam-awards       (daily: SAM award notices)
Run:  python -m src.enrich --build-vendor-profiles    (weekly: materialize vendors)
Run:  python -m src.enrich --build-office-market-stats (weekly: materialize stats)
Cron: enrich hourly; refresh-sam-awards daily; the rest weekly.

Stages per opportunity (spec pipeline 1-14): resolve office -> load cached
award pools -> link -> incumbent -> work origin -> funding -> market ->
competition -> recommendation -> store dossier. Failures mark the row
'failed' and never poison the batch.
"""
import sys

from . import db, db_intel
from .adapters import usaspending
from .classify import classify
from .config import NAICS_TARGETS
from .intel.dossier import build_dossier
from .intel.linking import link_awards
from .intel.offices import office_identity_from_opportunity, office_key
from .log import log
from .profile import load_profile

_OPP_COLS = ("id", "title", "agency", "office", "notice_type", "naics", "set_aside",
             "solicitation_number", "response_deadline", "place_of_performance",
             "description_text", "url", "source_notice_id", "raw_json")


def _load_opportunity(cur, opp_id: int) -> dict | None:
    cur.execute(
        """select id, title, agency, office, notice_type, naics, set_aside,
                  solicitation_number, response_deadline, place_of_performance,
                  description_text, url, source_notice_id, raw_json
           from opportunities where id=%s""", (opp_id,))
    row = cur.fetchone()
    return dict(zip(_OPP_COLS, row, strict=True)) if row else None


def enrich_one(conn, opp_id: int, profile: dict) -> bool:
    cur = conn.cursor()
    try:
        opp = _load_opportunity(cur, opp_id)
        if not opp:
            return False
        db_intel.mark_enrichment(cur, opp_id, "running")
        conn.commit()

        identity = office_identity_from_opportunity(opp)
        _, conf, _ = office_key(identity)
        office_id = db_intel.upsert_buyer_office(cur, identity, conf)
        _enrich_office_from_hierarchy(cur, office_id, identity)

        awards_office, awards_subtier = db_intel.fetch_candidate_awards(
            cur, identity, opp.get("naics"))

        # Funding context inputs (cached tables only; live pulls happen in refresh jobs)
        accounts, budget_rows = _cached_funding(cur, opp)

        classification = classify(opp, profile)
        lineage_rows = []
        if opp.get("solicitation_number"):
            cur.execute(
                """select l.stage, l.opportunity_id, o.posted_date
                   from opportunity_lineage l
                   join opportunities o on o.id = l.opportunity_id
                   where l.solicitation_number=%s
                   order by l.stage_rank, o.posted_date""",
                (opp["solicitation_number"],))
            lineage_rows = [{"stage": r[0], "opportunity_id": r[1],
                             "posted_date": r[2]} for r in cur.fetchall()]
        dossier = build_dossier(opp, classification, awards_office, awards_subtier,
                                accounts, budget_rows, lineage_rows=lineage_rows)

        pool = awards_office or awards_subtier
        links = link_awards(opp, identity, pool)
        award_ids = _award_id_map(cur, [ln["award"].get("source_award_id") for ln in links])
        db_intel.save_links(cur, opp_id, links[:50], award_ids)
        db_intel.save_dossier(cur, opp_id, office_id, dossier)
        db_intel.mark_enrichment(cur, opp_id, "done")
        conn.commit()
        return True
    except Exception as exc:  # noqa: BLE001 — one failed dossier must not kill the batch
        conn.rollback()
        with conn.cursor() as c2:
            db_intel.mark_enrichment(c2, opp_id, "failed")
        conn.commit()
        log("enrich_failed", opportunity_id=opp_id, error=f"{type(exc).__name__}: {exc}")
        return False
    finally:
        cur.close()


def _enrich_office_from_hierarchy(cur, office_id, identity):
    """Use the federal hierarchy API to firm up office identity when an
    organization code exists. Best-effort: hierarchy may be incomplete, and a
    lookup failure must never fail enrichment (fallback identity logic stays)."""
    if not office_id or not identity.get("organization_code"):
        return
    try:
        from .adapters import fed_hierarchy
        h = fed_hierarchy.lookup(identity["organization_code"])
        if h:
            db_intel.update_office_from_hierarchy(cur, office_id, h)
    except Exception as exc:  # noqa: BLE001 — hierarchy is enrichment, not a dependency
        log("hierarchy_enrich_skipped", error=type(exc).__name__)


def _cached_funding(cur, opp):
    cur.execute(
        """select federal_account_code, federal_account_name, fiscal_year,
                  budgetary_resources, obligations, president_budget_amount,
                  source, raw_json
           from funding_accounts
           where agency_name=%s or agency_name is null
           order by fiscal_year desc nulls last limit 12""", (opp.get("agency"),))
    rows = [dict(zip(("federal_account_code", "federal_account_name", "fiscal_year",
                      "budgetary_resources", "obligations",
                      "president_budget_amount", "source", "raw_json"),
                     r, strict=True)) for r in cur.fetchall()]
    accounts = [r for r in rows if r.get("federal_account_code")]
    budget = [r for r in rows if r.get("budgetary_resources") is not None]
    return accounts, budget


def _award_id_map(cur, source_ids):
    ids = [s for s in source_ids if s]
    if not ids:
        return {}
    cur.execute("select source_award_id, id from contract_awards where source_award_id = any(%s)",
                (ids,))
    return dict(cur.fetchall())


def process_queue(limit: int = 50):
    profile = load_profile()
    conn = db.get_conn()
    conn.autocommit = False
    done = failed = 0
    try:
        with conn.cursor() as cur:
            pending = db_intel.pending_enrichment(cur, limit)
        for opp_id in pending:
            (done, failed) = (done + 1, failed) if enrich_one(conn, opp_id, profile) \
                else (done, failed + 1)
            _resolve_delegation_best_effort(conn, opp_id)
        log("enrich_complete", done=done, failed=failed, queued=len(pending))
    finally:
        conn.close()


def _resolve_delegation_best_effort(conn, opp_id: int):
    """Upgrade the opportunity's delegation using the Census geocoder (free)
    so the House match reaches city/address confidence. Never fails the job."""
    try:
        from .adapters.census_geocode import lookup_district
        from .db_civic import resolve_delegation
        resolve_delegation(conn, opp_id, geocode=lookup_district)
    except Exception as exc:  # noqa: BLE001 — delegation is additive intel
        conn.rollback()
        log("delegation_enrich_skipped", opportunity_id=opp_id,
            error=type(exc).__name__)


def refresh_awards(years_back: int = 5):
    """Weekly job: pull USAspending award history for target categories into
    contract_awards. Broad by NAICS; office attribution refines linking later."""
    conn = db.get_conn()
    conn.autocommit = False
    count = 0
    try:
        cur = conn.cursor()
        for naics in NAICS_TARGETS:
            try:
                for a in usaspending.search_awards(naics=[naics], years_back=years_back):
                    db_intel.upsert_award(cur, a)
                    count += 1
                    if count % 200 == 0:
                        conn.commit()
            except usaspending.UsaSpendingError as exc:
                conn.rollback()
                log("award_refresh_query_failed", naics=naics, error=str(exc))
        conn.commit()
        log("award_refresh_complete", upserted=count)
    finally:
        conn.close()


def refresh_sam_awards():
    """Daily job: pull SAM.gov award notices, upsert into contract_awards,
    and requeue enrichment for opportunities sharing a solicitation number —
    award notices are the strongest public incumbent evidence."""
    from .adapters import sam_awards

    conn = db.get_conn()
    conn.autocommit = False
    count, solnums = 0, set()
    try:
        cur = conn.cursor()
        for naics in NAICS_TARGETS:
            try:
                for a in sam_awards.fetch_award_notices(naics=naics):
                    db_intel.upsert_award(cur, a)
                    if a.get("solicitation_number"):
                        solnums.add(a["solicitation_number"])
                    count += 1
                    if count % 200 == 0:
                        conn.commit()
            except Exception as exc:  # noqa: BLE001 — one NAICS failing must not kill the job
                conn.rollback()
                log("sam_award_query_failed", naics=naics, error=f"{type(exc).__name__}: {exc}")
        requeue = db_intel.opportunities_for_solnums(cur, sorted(solnums))
        db_intel.requeue_enrichment(cur, requeue)
        conn.commit()
        log("sam_award_refresh_complete", upserted=count, requeued=len(requeue))
    finally:
        conn.close()


def build_vendor_profiles():
    """Weekly job: materialize vendor_profiles from contract_awards."""
    from .intel.materialize import vendor_profiles

    conn = db.get_conn()
    conn.autocommit = False
    try:
        cur = conn.cursor()
        awards = db_intel.fetch_all_awards(cur)
        profiles = vendor_profiles(awards)
        for p in profiles:
            db_intel.upsert_vendor_profile(cur, p)
        conn.commit()
        log("vendor_profiles_built", vendors=len(profiles), awards=len(awards))
    finally:
        conn.close()


def build_office_market_stats():
    """Weekly job: materialize office_market_stats from contract_awards."""
    from .intel.materialize import office_market_stats

    conn = db.get_conn()
    conn.autocommit = False
    try:
        cur = conn.cursor()
        awards = db_intel.fetch_all_awards(cur)
        rows = office_market_stats(awards)
        written = 0
        for row in rows:
            _, conf, _ = office_key(row["identity"])
            office_id = db_intel.upsert_buyer_office(cur, row["identity"], conf)
            if office_id:
                db_intel.upsert_office_market_stat(cur, office_id, row)
                written += 1
        conn.commit()
        log("office_market_stats_built", rows=written, awards=len(awards))
    finally:
        conn.close()


def refresh_legislators_job():
    from . import db, db_civic
    conn = db.get_conn()
    conn.autocommit = False
    try:
        from .jobs import record_job
        with record_job(conn, "refresh_legislators") as stats:
            stats["fetched"] = db_civic.refresh_legislators(conn)
    finally:
        conn.close()


def refresh_legislator_funding_job():
    import datetime

    from . import db, db_civic
    cycle = datetime.date.today().year
    cycle += cycle % 2                      # FEC two-year cycles end in even years
    conn = db.get_conn()
    conn.autocommit = False
    try:
        from .jobs import record_job
        with record_job(conn, "refresh_legislator_funding") as stats:
            stats["fetched"] = db_civic.refresh_legislator_funding(conn, cycle)
    finally:
        conn.close()


def import_staff_job(path: str):
    from . import db, db_civic
    conn = db.get_conn()
    conn.autocommit = False
    try:
        db_civic.import_staff_csv(conn, path)
    finally:
        conn.close()


def _district_spending_run(conn):
    import datetime

    from . import db_civic
    today = datetime.date.today()
    current_fy = today.year + (1 if today.month >= 10 else 0)
    years = list(range(current_fy - 4, current_fy + 1))     # 5-year history
    return db_civic.refresh_district_spending(conn, years)


def _candidate_finance_run(conn):
    import datetime

    from . import db_civic
    cycle = datetime.date.today().year
    cycle += cycle % 2
    return db_civic.refresh_candidate_finance(conn, cycle)


def _queue_documents_run(conn):
    from .db_documents import queue_documents_for_recent
    return queue_documents_for_recent(conn)


def _process_documents_run(conn):
    from .db_documents import process_document_queue
    return process_document_queue(conn, limit=50)["done"]


def _refresh_forecasts_run(conn):
    from .db_forecasts import link_recent_opportunities, refresh_apfs
    fetched = refresh_apfs(conn)
    link_recent_opportunities(conn)
    return fetched


def _link_forecasts_run(conn):
    from .db_forecasts import link_recent_opportunities
    return link_recent_opportunities(conn)


def _refresh_grants_run(conn):
    from .db_grants import refresh_grants
    return refresh_grants(conn)


def _civic_job(job_name, fn):
    from . import db
    from .jobs import record_job
    conn = db.get_conn()
    conn.autocommit = False
    try:
        with record_job(conn, job_name) as stats:
            stats["fetched"] = fn(conn)
    finally:
        conn.close()


def _civic_import(fn_name, path):
    from . import db, db_civic
    conn = db.get_conn()
    conn.autocommit = False
    try:
        getattr(db_civic, fn_name)(conn, path)
    finally:
        conn.close()


if __name__ == "__main__":
    if "--refresh-awards" in sys.argv:
        refresh_awards()
    elif "--refresh-sam-awards" in sys.argv:
        refresh_sam_awards()
    elif "--build-vendor-profiles" in sys.argv:
        build_vendor_profiles()
    elif "--build-office-market-stats" in sys.argv:
        build_office_market_stats()
    elif "--refresh-legislators" in sys.argv:
        refresh_legislators_job()
    elif "--refresh-legislator-funding" in sys.argv:
        refresh_legislator_funding_job()
    elif "--import-staff" in sys.argv:
        import_staff_job(sys.argv[sys.argv.index("--import-staff") + 1])
    elif "--refresh-district-spending" in sys.argv:
        _civic_job("refresh_district_spending", _district_spending_run)
    elif "--refresh-candidate-finance" in sys.argv:
        _civic_job("refresh_candidate_finance", _candidate_finance_run)
    elif "--import-election-results" in sys.argv:
        _civic_import("import_election_results_csv",
                      sys.argv[sys.argv.index("--import-election-results") + 1])
    elif "--queue-documents" in sys.argv:
        _civic_job("queue_documents", _queue_documents_run)
    elif "--process-documents" in sys.argv:
        _civic_job("process_documents", _process_documents_run)
    elif "--import-directed-spending" in sys.argv:
        _civic_import("import_directed_spending_csv",
                      sys.argv[sys.argv.index("--import-directed-spending") + 1])
    elif "--refresh-forecasts" in sys.argv:
        _civic_job("refresh_forecasts", _refresh_forecasts_run)
    elif "--refresh-grants" in sys.argv:
        _civic_job("refresh_grants", _refresh_grants_run)
    elif "--import-oversight" in sys.argv:
        from . import db
        from .db_oversight import import_oversight_csv
        from .db_oversight import link_recent_opportunities as _link_oversight
        _conn = db.get_conn()
        _conn.autocommit = False
        try:
            import_oversight_csv(
                _conn, sys.argv[sys.argv.index("--import-oversight") + 1])
            _link_oversight(_conn)
        finally:
            _conn.close()
    elif "--link-oversight" in sys.argv:
        def _link_oversight_run(conn):
            from .db_oversight import link_recent_opportunities
            return link_recent_opportunities(conn)
        _civic_job("link_oversight", _link_oversight_run)
    elif "--link-forecasts" in sys.argv:
        _civic_job("link_forecasts", _link_forecasts_run)
    elif "--import-forecasts" in sys.argv:
        from . import db
        from .db_forecasts import import_forecast_csv, link_recent_opportunities
        _conn = db.get_conn()
        _conn.autocommit = False
        try:
            import_forecast_csv(
                _conn, sys.argv[sys.argv.index("--import-forecasts") + 1])
            link_recent_opportunities(_conn)
        finally:
            _conn.close()
    else:
        process_queue()
