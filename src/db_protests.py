"""Persistence for GAO bid-protest records.

Rows arrive via provenance-enforced CSV import (GAO decisions are public and
searchable at gao.gov; docket exports carry the B-number and a decision URL).
Protests matched to an opportunity's solicitation-number family become
incumbent-vulnerability signals; agency-level counts give office context.
"""
import csv
import json

from .log import log

CSV_REQUIRED = ("source_record_id", "agency", "source_url")
CSV_OPTIONAL = ("source", "protester", "solicitation_number", "filed_date",
                "decided_date", "outcome", "summary")

_OUTCOMES = ("sustained", "denied", "dismissed", "withdrawn",
             "corrective_action", "pending")


class ProtestImportError(RuntimeError):
    pass


def parse_protest_csv(path: str):
    with open(path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for lineno, row in enumerate(reader, start=2):
            missing = [c for c in CSV_REQUIRED if not (row.get(c) or "").strip()]
            if missing:
                raise ProtestImportError(
                    f"line {lineno}: missing {', '.join(missing)} — protest "
                    "records without provenance are rejected")
            outcome = (row.get("outcome") or "").strip().lower() or None
            if outcome and outcome not in _OUTCOMES:
                raise ProtestImportError(
                    f"line {lineno}: outcome must be one of "
                    f"{', '.join(_OUTCOMES)} (got {outcome!r})")
            yield {
                **{k: (row.get(k) or "").strip() or None
                   for k in CSV_REQUIRED + CSV_OPTIONAL},
                "source": (row.get("source") or "csv_import").strip(),
                "outcome": outcome,
                "filed_date": (row.get("filed_date") or "").strip()[:10] or None,
                "decided_date": (row.get("decided_date") or "").strip()[:10]
                                or None,
                "raw_json": dict(row),
            }


def upsert_protest(cur, rec: dict) -> int:
    cur.execute(
        """insert into protest_records
             (source, source_record_id, protester, agency,
              solicitation_number, filed_date, decided_date, outcome, summary,
              source_url, raw_json)
           values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
           on conflict (source, source_record_id) do update set
             protester=excluded.protester, agency=excluded.agency,
             solicitation_number=excluded.solicitation_number,
             filed_date=excluded.filed_date,
             decided_date=excluded.decided_date, outcome=excluded.outcome,
             summary=excluded.summary, source_url=excluded.source_url,
             raw_json=excluded.raw_json
           returning id""",
        (rec.get("source"), rec["source_record_id"], rec.get("protester"),
         rec.get("agency"), rec.get("solicitation_number"),
         rec.get("filed_date"), rec.get("decided_date"), rec.get("outcome"),
         rec.get("summary"), rec["source_url"],
         json.dumps(rec.get("raw_json") or {}, default=str)))
    return cur.fetchone()[0]


def import_protest_csv(conn, path: str) -> int:
    written = 0
    with conn.cursor() as cur:
        for rec in parse_protest_csv(path):
            upsert_protest(cur, rec)
            written += 1
    conn.commit()
    log("protest_csv_imported", records=written, path=path)
    return written


def protests_for_solicitation_family(cur, solicitation_number: str | None,
                                     limit: int = 10) -> list[dict]:
    """Protests whose solicitation number belongs to the same family
    (exact or shared >=8-char prefix, matching intel.similarity rules)."""
    if not solicitation_number:
        return []
    from .intel.similarity import solnum_family
    cur.execute(
        """select source_record_id, protester, agency, solicitation_number,
                  filed_date, decided_date, outcome, summary, source_url
           from protest_records where solicitation_number is not null
           order by filed_date desc nulls last limit 2000""")
    cols = ("source_record_id", "protester", "agency", "solicitation_number",
            "filed_date", "decided_date", "outcome", "summary", "source_url")
    rows = [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]
    return [r for r in rows
            if solnum_family(solicitation_number, r["solicitation_number"])
            ][:limit]
