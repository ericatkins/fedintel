# Document Intelligence

The important requirements live in the attachments, not the notice metadata.
Fedintel fetches solicitation documents, extracts their text, and mines them
with **deterministic rules** — every extracted requirement carries the sentence
it came from, the rule that fired, the page, and a confidence.

## Pipeline
```
notice raw_json.resourceLinks
  → queue_documents        (--queue-documents, hourly)
  → fetch_document         SSRF-guarded, 20 MB cap, streamed, no redirects
  → extract_text           pypdf, 400-page / 1.2M-char bounds
  → extract_requirements   ~45 named regex rules with evidence capture
  → document_requirements  (global facts about the notice)
  → qualification.assess() (per-org, at read time)
```
Run: `python -m src.enrich --queue-documents && python -m src.enrich --process-documents`
(the `documents-hourly` Railway service does both).

## Security boundary
Attachments are untrusted binaries from an external system:
- **SSRF**: only HTTPS SAM.gov hosts (reuses the `safe_sam_url` allowlist);
  credentials-in-URL, redirects, and non-SAM hosts are refused.
- **Resource limits**: 20 MB streamed cap enforced even when `content-length`
  lies, 45s timeout, 400-page and 1.2M-char extraction bounds.
- **Filenames** are sanitized (path traversal → underscores), never trusted.
- Fedintel stores extracted **text** plus a sha256. It never executes, renders,
  or re-serves the original binary. The SAM API key is never logged.

## What gets extracted
clearances (TS/SCI → Public Trust, polygraph, FCL) · contract vehicles
(CIO-SP4, SEWP, OASIS+, Alliant, STARS, GSA MAS, GWAC, IDIQ, BPA) · set-asides
(8(a), HUBZone, SDVOSB, WOSB, Total SB) · certifications (CMMC level, FedRAMP,
NIST SP 800-171, ISO 9001, CMMI, Section 508) · wage regimes (SCA, Davis-Bacon)
· evaluation approach (LPTA, best-value tradeoff, past performance) ·
submission mechanics (page limits, SAM registration, oral presentations) ·
personnel (key personnel, US citizenship) · place (on-site required) ·
deliverables (CDRLs, monthly reports) · bonding (bid/performance).

**Tier discipline**: a TS/SCI hit suppresses a bare "Secret" hit; "CMMC Level 3"
suppresses "CMMC (level unstated)". Evidence tiers are never blurred.

## Qualification verdicts (per organization)
| Verdict | Meaning | Score cap |
|---|---|---|
| not eligible to prime | set-aside status you don't hold | 15 |
| blocked unless teaming | vehicle/clearance gate — clearable via a teaming partner | 55 |
| qualified with gaps | obtainable/subcontractable gaps (e.g. a certification) | none |
| qualified — profile incomplete | profile doesn't list vehicles/clearances/certs | none |
| qualified | profile satisfies every extracted requirement | none |

Scores are **capped, not zeroed** — a barred opportunity stays visible because
teaming is a real strategy. Silence in a profile is never read as capability,
and silence in a document is never read as absence of a requirement.

Profile fields that drive this: `contract_vehicles`, `clearances`,
`certifications`, `set_aside_eligibility` (Company Profile page).

## Honest failure states
`too_large`, `unsupported` (scanned image PDFs with no embedded text — OCR is
not enabled), `failed`, `skipped` (URL off-allowlist). These are recorded and
shown on the opportunity, never silently swallowed.

## Roadmap
OCR for scanned PDFs; amendment diffing (what changed between versions);
Q&A-document mining for incumbent hints; CLIN/labor-category tables; proposal
workback schedule from extracted due dates; optional grounded AI summaries over
already-extracted text (never as the source of a requirement).
