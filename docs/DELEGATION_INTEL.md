# Delegation Intelligence

Every opportunity's place of performance resolves to the elected officials who
represent it: both U.S. senators (state match, certain) and the U.S. House
member (district match, confidence-tiered), with committee seats filtered to
the ones that hold jurisdiction over the buying agency.

## Data sources — all public record
| Data | Source | Refresh |
|---|---|---|
| Members, contacts, committees, FEC IDs | unitedstates/congress-legislators (public domain) | `python -m src.enrich --refresh-legislators` (weekly) |
| Place → congressional district | US Census Geocoder (free, no key) | resolved during nightly enrichment, cached in `district_lookups` |
| Campaign funding aggregates | FEC API (`FEC_API_KEY`, free) | `python -m src.enrich --refresh-legislator-funding` (monthly) |
| Staff rosters | operator import ONLY (`--import-staff roster.csv`) | as sourced |

## Truthfulness rules (enforced in code and copy)
- **Corporations cannot contribute to federal candidates.** "Employer" rows are
  FEC aggregates of individual contributions by reported employer; PAC rows are
  committee receipts. The UI never says "Company X donated".
- **District confidence is explicit**: street address 90, city centroid 60
  (cities span districts — badge says "district estimated"), state-only shows
  senators alone. Never present a city-tier match as certain.
- **Staff names are never fabricated.** There is no free machine-readable staff
  directory; the House Statement of Disbursements and commercial directories
  (e.g. LegiStorm exports) are the usual sources for the CSV import, and every
  imported row carries its source and as-of date. Until imported, the UI shows
  the role playbook (MLA, appropriations LA, district director, grants
  coordinator, scheduler) — standard office roles to ask for by function.

## Legislative-branch tie-ins surfaced per member
- Committee jurisdiction badges (authorizers + the appropriations subcommittee
  that funds the buying agency; House/Senate Small Business always relevant).
- Calendar windows: appropriations & Community Project Funding request season,
  the NDAA cycle, federal Q4 obligation push, continuing-resolution risk (which
  also feeds the funding-context caveats).
- Engagement guardrails, stated on every page: offices may inquire and write
  support letters but cannot direct awards; during an active solicitation all
  questions go through the contracting officer (FAR 3.104); contributions are
  never linked to procurement.

## Roadmap
Bill/report-language tracking for named programs, congressional-record and
press-release mentions, incumbent-contract expirations by district, and
House-disbursements ingestion as a first-party staff source.
