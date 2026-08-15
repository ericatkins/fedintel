"""Evidence and source ledger: everything the dossier's conclusions rest on,
in one auditable table.

Assembled at read time from records already stored — the ledger never
fetches. Each row: source, organization, identifier, retrieval time, which
conclusions use it, and known limitations. A user must be able to audit the
dossier from this table alone.
"""


def _row(title, org, identifier=None, url=None, retrieved=None, used_by=None,
         limitations=None):
    return {
        "source_title": title,
        "organization": org,
        "identifier": identifier,
        "url": url,
        "retrieved": str(retrieved) if retrieved else None,
        "used_by": used_by or [],
        "limitations": limitations,
    }


def build_evidence_ledger(opp: dict, dossier: dict | None,
                          documents: list[dict] | None,
                          delegation: list[dict] | None,
                          forecasts: list[dict] | None = None,
                          oversight: list[dict] | None = None) -> list[dict]:
    rows = [_row(
        "Opportunity notice", "SAM.gov (GSA)",
        identifier=opp.get("source_notice_id"), url=opp.get("url"),
        retrieved=opp.get("last_seen_at") or opp.get("first_seen_at"),
        used_by=["opportunity facts", "notice-language signals",
                 "work-origin assessment"],
        limitations="Notice metadata can conflict with attachments; the "
                    "documents govern.",
    )]

    for doc in documents or []:
        rows.append(_row(
            doc.get("filename") or "attachment", "SAM.gov attachment",
            identifier=(doc.get("sha256") or "")[:16] or None,
            url=doc.get("source_url"),
            retrieved=doc.get("fetched_at"),
            used_by=(["compliance matrix", "qualification verdict"]
                     if doc.get("fetch_status") == "extracted"
                     else [f"not yet usable (status: {doc.get('fetch_status')})"]),
            limitations=(
                f"OCR-extracted ({doc.get('ocr_pages')} of "
                f"{doc.get('page_count')} pages machine-read) — text "
                "reliability reduced; requirement confidence capped."
                if doc.get("extraction_method") == "ocr"
                else None if doc.get("fetch_status") == "extracted"
                else "Text not extracted — requirements from this file are "
                     "not in the matrix."),
        ))

    if dossier:
        n_awards = len(dossier.get("similar_work") or [])
        rows.append(_row(
            f"Historical contract awards ({n_awards} linked)",
            "USAspending.gov / SAM.gov award notices",
            retrieved=dossier.get("generated_at"),
            used_by=["incumbent analysis", "contract family", "Buyer DNA",
                     "value estimate", "competition landscape"],
            limitations="USAspending reporting lags actions by weeks to "
                        "months; subaward data is incomplete by design.",
        ))
        fc = dossier.get("funding_context") or {}
        if fc.get("label_key") not in (None, "none"):
            rows.append(_row(
                "Federal account / budgetary resources",
                "USAspending.gov federal accounts",
                retrieved=dossier.get("generated_at"),
                used_by=[f"funding context ({fc.get('label', 'label')})"],
                limitations="Account-level alignment is not evidence that this "
                            "specific opportunity is funded.",
            ))
        dna = dossier.get("buyer_dna") or {}
        if dna.get("status") == "ok":
            basis = dna.get("basis") or {}
            rows.append(_row(
                f"Peer-office award pool ({basis.get('peer_awards', 0)} awards)",
                "USAspending.gov",
                retrieved=dossier.get("generated_at"),
                used_by=["Buyer DNA peer baseline"],
                limitations="Peers share subtier and NAICS, not mission or "
                            "scale.",
            ))

    for fc in forecasts or []:
        rows.append(_row(
            f"Procurement forecast: {fc.get('title', '')[:80]}",
            {"dhs_apfs": "DHS Acquisition Planning Forecast System"}.get(
                fc.get("source"), "Agency forecast (operator import)"),
            identifier=fc.get("source_record_id"), url=fc.get("source_url"),
            retrieved=fc.get("last_seen_at"),
            used_by=["forecast lineage", "demand radar"],
            limitations="Forecasts are agency planning statements, not "
                        "commitments; dates and scope routinely change.",
        ))

    for f in oversight or []:
        rows.append(_row(
            f"Oversight finding: {(f.get('title') or '')[:80]}",
            {"gao": "Government Accountability Office"}.get(
                f.get("source"), "Oversight body (operator import)"),
            identifier=f.get("report_number"), url=f.get("source_url"),
            used_by=["why this requirement exists"],
            limitations=("The notice cites this report directly."
                         if f.get("link_kind") == "cited" else
                         "Inferred demand context only — not a confirmed "
                         "procurement driver."),
        ))

    if delegation:
        rows.append(_row(
            "Congressional delegation", "unitedstates/congress-legislators "
            "(public domain) + US Census geocoder",
            used_by=["delegation panel"],
            limitations="District from place of performance; city-level "
                        "geocodes are estimates.",
        ))
    return rows
