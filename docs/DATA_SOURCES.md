# Data Sources Registry

Every source Fedintel touches, its access method, cadence, and known
limitations. Before adding a source: check terms of service, prefer official
APIs/bulk files over scraping, and give the adapter rate limiting, retries,
caching, idempotent writes, raw-record retention, and failure isolation.

## Automated live APIs

| Source | Adapter | Access | Cadence | Known limitations |
|---|---|---|---|---|
| SAM.gov Opportunities | `adapters/sam_gov.py` | API key (`SAM_API_KEY`) | daily | metadata can conflict with attachments |
| SAM.gov Award Notices | `adapters/sam_awards.py` | same key, `ptype=a` | weekly | award notices lag actual awards |
| SAM.gov Attachments | `documents/fetch.py` | resource links, allowlisted HTTPS | hourly | scanned PDFs unsupported until OCR ships |
| SAM.gov Federal Hierarchy | `adapters/fed_hierarchy.py` | API key | on enrichment | hierarchy incomplete for some offices |
| USAspending | `adapters/usaspending.py` | public, no key | daily/weekly/monthly | reporting lags weeks–months; subawards incomplete |
| USAspending Geography | `adapters/usaspending_geo.py` | public | weekly | place-of-performance attribution only |
| congress-legislators | `adapters/legislators_dataset.py` | public domain dataset | weekly | — |
| US Census Geocoder | `adapters/census_geocode.py` | public, no key | on enrichment | city centroids span districts |
| FEC | `adapters/fec.py` | API key | monthly | employer rows are individual aggregates |
| DHS APFS forecasts | `adapters/forecasts.py` | public JSON API, no key | weekly (`--refresh-forecasts`) | **live validation pending**: restricted network environments (including the one this adapter was built in) block apfs-cloud.dhs.gov; the adapter is failure-isolated and validated against a fixture mirroring the documented record shape. Verify field names on first production run. |

## Operator-imported sources (no reliable machine feed exists)

Every row must carry provenance (source identifiers + URL) or the import
rejects the file.

| Source | Import command | Notes |
|---|---|---|
| Agency procurement forecasts (XLSX/CSV) | `python -m src.enrich --import-forecasts file.csv` | Most agencies publish forecast spreadsheets on OSDBU pages; acquisition.gov keeps the directory. Required columns: `source_record_id, agency, title, source_url`; optional: subtier, office, description, naics, psc, estimated_value_low/high, action_type (new_requirement/recompete/option/unknown), incumbent_name, contract_vehicle, set_aside, anticipated_solicitation, anticipated_award, fiscal_year, place_of_performance, point_of_contact. |
| Congressional staff rosters | `--import-staff` | House Statement of Disbursements, commercial directories |
| Election results | `--import-election-results` | MIT Election Lab, state SoS |
| Directed spending (CPF/earmarks) | `--import-directed-spending` | appropriations committee disclosures |
| GAO bid protests | `python -m src.enrich --import-protests file.csv` | GAO decisions are public at gao.gov (searchable by agency/solicitation). Required columns: `source_record_id (B-number), agency, source_url`; optional: protester, solicitation_number, filed_date, decided_date, outcome (sustained/denied/dismissed/withdrawn/corrective_action/pending), summary. Protests in an opportunity's solicitation-number family become incumbent-vulnerability signals and timeline entries. |
| Oversight findings (GAO/IG) | `python -m src.enrich --import-oversight file.csv` | GAO publishes CSV downloads of open recommendations and high-risk areas; IG reports indexed on oversight.gov. Required columns: `source_record_id, finding_type (recommendation/high_risk/ig_finding), title, source_url`; optional: source, agency, subtier, detail, report_number, published_date, status. Linked to opportunities as INFERRED context unless the notice cites the report number ('cited'). |

## Forecast → opportunity linking

`src/intel/forecast_link.py` scores agency + NAICS + title/description
similarity + timing (posted within 270 days of the anticipated solicitation
date). Links need score ≥ 45 **and** at least two independent evidence
signals; evidence is stored per link and shown in the UI. Forecasts are
planning statements, not commitments — the UI says so wherever they appear.

## Researched but not yet integrated

- Acquisition.gov forecast directory (index of per-agency forecast pages —
  drives the CSV import workflow; no unified API).
- Grants.gov / Simpler.Grants.gov, SAM Assistance Listings (grants vertical).
- GAO bid-protest live API/scrape (the CSV import above covers docket rows;
  office-level protest-rate metrics for Buyer DNA still need volume data).
- Federal Register / Unified Agenda / Regulations.gov (regulatory demand).
- Congress.gov / GovInfo (funding ladder deepening).
