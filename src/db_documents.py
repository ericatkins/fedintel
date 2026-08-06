"""Persistence and pipeline for document intelligence."""
from .documents.extract import extract_text
from .documents.fetch import fetch_document, resource_links
from .documents.requirements import classify_document, extract_requirements
from .log import log

MAX_DOCS_PER_OPPORTUNITY = 12


def queue_documents(cur, opportunity_id: int, raw_json: dict) -> int:
    """Register attachment URLs from a stored notice as pending documents."""
    queued = 0
    for url in resource_links(raw_json)[:MAX_DOCS_PER_OPPORTUNITY]:
        cur.execute(
            """insert into opportunity_documents (opportunity_id, source_url)
               values (%s,%s) on conflict (opportunity_id, source_url) do nothing""",
            (opportunity_id, url))
        queued += cur.rowcount or 0
    return queued


def pending_documents(cur, limit: int = 25) -> list[tuple[int, int, str]]:
    cur.execute(
        """select d.id, d.opportunity_id, d.source_url
           from opportunity_documents d
           where d.fetch_status = 'pending'
           order by d.id limit %s""", (limit,))
    return cur.fetchall()


def store_requirements(cur, opportunity_id: int, document_id: int,
                       requirements: list[dict]) -> int:
    written = 0
    for req in requirements:
        cur.execute(
            """insert into document_requirements
                 (opportunity_id, document_id, requirement_type, value,
                  evidence_quote, page, method, confidence)
               values (%s,%s,%s,%s,%s,%s,%s,%s)
               on conflict (opportunity_id, requirement_type, value, doc_key)
               do update set evidence_quote=excluded.evidence_quote,
                             page=excluded.page, confidence=excluded.confidence""",
            (opportunity_id, document_id, req["requirement_type"], req["value"],
             req["evidence_quote"], req["page"], req["method"], req["confidence"]))
        written += 1
    return written


def process_document(conn, document_id: int, opportunity_id: int, url: str) -> bool:
    """Fetch → extract text → mine requirements. Records honest failure states
    (too_large, unsupported for scanned PDFs) rather than silent empties."""
    result = fetch_document(url)
    status = result["status"]
    if status != "fetched":
        with conn.cursor() as cur:
            cur.execute(
                """update opportunity_documents set fetch_status=%s, fetch_error=%s,
                     filename=coalesce(%s, filename), fetched_at=now()
                   where id=%s""",
                (status, (result.get("error") or "")[:300], result.get("filename"),
                 document_id))
        conn.commit()
        return False

    extracted = extract_text(result["content"], result.get("filename", ""))
    text = extracted.get("text", "")
    kind = classify_document(result.get("filename", ""), text)
    requirements = extract_requirements(extracted.get("pages") or [])
    with conn.cursor() as cur:
        cur.execute(
            """update opportunity_documents
                 set fetch_status=%s, filename=%s, content_type=%s, byte_size=%s,
                     sha256=%s, page_count=%s, text_chars=%s, doc_kind=%s,
                     extracted_text=%s, fetch_error=%s,
                     fetched_at=now(), extracted_at=now()
               where id=%s""",
            ("extracted" if extracted["status"] == "extracted" else extracted["status"],
             result.get("filename"), result.get("content_type"),
             result.get("byte_size"), result.get("sha256"),
             extracted.get("page_count"), len(text), kind, text,
             (extracted.get("note") or "")[:300] or None, document_id))
        if requirements:
            store_requirements(cur, opportunity_id, document_id, requirements)
    conn.commit()
    log("document_processed", document_id=document_id, kind=kind,
        pages=extracted.get("page_count"), requirements=len(requirements),
        status=extracted["status"])
    return extracted["status"] == "extracted"


def process_document_queue(conn, limit: int = 25) -> dict:
    with conn.cursor() as cur:
        pending = pending_documents(cur, limit)
    done = failed = 0
    for document_id, opportunity_id, url in pending:
        try:
            ok = process_document(conn, document_id, opportunity_id, url)
        except Exception as exc:  # noqa: BLE001 — one bad file must not stop the run
            conn.rollback()
            ok = False
            log("document_process_error", document_id=document_id,
                error=type(exc).__name__)
        done, failed = (done + 1, failed) if ok else (done, failed + 1)
    log("document_queue_complete", done=done, failed=failed, queued=len(pending))
    return {"done": done, "failed": failed, "queued": len(pending)}


def queue_documents_for_recent(conn, lookback_days: int = 7, limit: int = 200) -> int:
    """Register attachments for recently-seen opportunities."""
    queued = 0
    with conn.cursor() as cur:
        cur.execute(
            """select id, raw_json from opportunities
               where first_seen_at > now() - make_interval(days => %s)
               order by first_seen_at desc limit %s""", (lookback_days, limit))
        rows = cur.fetchall()
        for opportunity_id, raw_json in rows:
            queued += queue_documents(cur, opportunity_id, raw_json or {})
    conn.commit()
    log("documents_queued", opportunities=len(rows), documents=queued)
    return queued


def requirements_for(cur, opportunity_id: int) -> list[dict]:
    cur.execute(
        """select r.requirement_type, r.value, r.evidence_quote, r.page,
                  r.method, r.confidence, d.filename, d.doc_kind
           from document_requirements r
           left join opportunity_documents d on d.id = r.document_id
           where r.opportunity_id=%s
           order by r.requirement_type, r.confidence desc, r.value""",
        (opportunity_id,))
    cols = ("requirement_type", "value", "evidence_quote", "page", "method",
            "confidence", "filename", "doc_kind")
    return [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]


def documents_for(cur, opportunity_id: int) -> list[dict]:
    cur.execute(
        """select id, filename, doc_kind, page_count, byte_size, fetch_status,
                  fetch_error, source_url, extracted_at
           from opportunity_documents where opportunity_id=%s order by id""",
        (opportunity_id,))
    cols = ("id", "filename", "doc_kind", "page_count", "byte_size",
            "fetch_status", "fetch_error", "source_url", "extracted_at")
    return [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]
