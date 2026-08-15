"""Persistence for oversight findings (GAO/IG) and their opportunity links.

Findings arrive via provenance-enforced CSV import: GAO publishes CSV
downloads of open recommendations (gao.gov) and high-risk areas; agency IG
reports are indexed on oversight.gov. Every row must carry an identifier and
source URL or the file is rejected.
"""
import csv
import json

from .intel.oversight_link import link_findings
from .log import log

CSV_REQUIRED = ("source_record_id", "finding_type", "title", "source_url")
CSV_OPTIONAL = ("source", "agency", "subtier", "detail", "report_number",
                "published_date", "status")


class OversightImportError(RuntimeError):
    pass


def parse_oversight_csv(path: str):
    with open(path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for lineno, row in enumerate(reader, start=2):
            missing = [c for c in CSV_REQUIRED if not (row.get(c) or "").strip()]
            if missing:
                raise OversightImportError(
                    f"line {lineno}: missing {', '.join(missing)} — oversight "
                    "findings without provenance are rejected")
            ftype = row["finding_type"].strip().lower()
            if ftype not in ("recommendation", "high_risk", "ig_finding"):
                raise OversightImportError(
                    f"line {lineno}: finding_type must be recommendation, "
                    f"high_risk, or ig_finding (got {ftype!r})")
            status = (row.get("status") or "").strip().lower() or None
            if status and status not in ("open", "closed", "addressed",
                                         "unknown"):
                status = "unknown"
            yield {
                **{k: (row.get(k) or "").strip() or None
                   for k in CSV_REQUIRED + CSV_OPTIONAL},
                "source": (row.get("source") or "csv_import").strip(),
                "finding_type": ftype,
                "status": status,
                "published_date": (row.get("published_date") or "").strip()[:10]
                                  or None,
                "raw_json": dict(row),
            }


def upsert_finding(cur, rec: dict) -> int:
    cur.execute(
        """insert into oversight_findings
             (source, source_record_id, finding_type, agency, subtier, title,
              detail, report_number, published_date, status, source_url,
              raw_json)
           values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
           on conflict (source, source_record_id) do update set
             finding_type=excluded.finding_type, agency=excluded.agency,
             subtier=excluded.subtier, title=excluded.title,
             detail=excluded.detail, report_number=excluded.report_number,
             published_date=excluded.published_date, status=excluded.status,
             source_url=excluded.source_url, raw_json=excluded.raw_json
           returning id""",
        (rec.get("source"), rec["source_record_id"], rec["finding_type"],
         rec.get("agency"), rec.get("subtier"), rec["title"],
         rec.get("detail"), rec.get("report_number"),
         rec.get("published_date"), rec.get("status"), rec["source_url"],
         json.dumps(rec.get("raw_json") or {}, default=str)))
    return cur.fetchone()[0]


def import_oversight_csv(conn, path: str) -> int:
    written = 0
    with conn.cursor() as cur:
        for rec in parse_oversight_csv(path):
            upsert_finding(cur, rec)
            written += 1
    conn.commit()
    log("oversight_csv_imported", records=written, path=path)
    return written


def link_recent_opportunities(conn, lookback_days: int = 30,
                              limit: int = 500) -> int:
    written = 0
    with conn.cursor() as cur:
        cur.execute(
            """select id, source, source_record_id, finding_type, agency,
                      subtier, title, detail, report_number, published_date,
                      status, source_url
               from oversight_findings order by imported_at desc limit 2000""")
        cols = ("id", "source", "source_record_id", "finding_type", "agency",
                "subtier", "title", "detail", "report_number",
                "published_date", "status", "source_url")
        findings = [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]
        if not findings:
            return 0
        cur.execute(
            """select id, title, agency, office, description_text,
                      raw_json->>'fullParentPathName'
               from opportunities
               where first_seen_at > now() - make_interval(days => %s)
               order by first_seen_at desc limit %s""",
            (lookback_days, limit))
        opps = [dict(zip(("id", "title", "agency", "office",
                          "description_text", "agency_path"), r,
                         strict=True)) for r in cur.fetchall()]
        for opp in opps:
            for ln in link_findings(opp, findings)[:4]:
                cur.execute(
                    """insert into opportunity_oversight_links
                         (opportunity_id, finding_id, link_kind,
                          similarity_score, confidence, evidence_json)
                       values (%s,%s,%s,%s,%s,%s)
                       on conflict (opportunity_id, finding_id) do update set
                         link_kind=excluded.link_kind,
                         similarity_score=excluded.similarity_score,
                         confidence=excluded.confidence,
                         evidence_json=excluded.evidence_json""",
                    (opp["id"], ln["finding"]["id"], ln["link_kind"],
                     ln["similarity_score"], ln["confidence"],
                     json.dumps(ln["evidence"])))
                written += 1
    conn.commit()
    log("oversight_links_refreshed", links=written, findings=len(findings))
    return written
