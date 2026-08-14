# Known Limitations Register

Honest inventory of what the product does **not** do yet, and why. A roadmap
presented as shipped is its own kind of lie.

## Intelligence

- **Contract family links are mostly inferred.** Confirmed (identifier-match)
  links exist only when SAM/USAspending records share solicitation or contract
  numbers; most families rest on ≥55-similarity links, and the UI labels every
  such member `inferred`. Modifications and option exercises are not yet
  ingested as distinct actions (USAspending transaction feed — planned), so
  the recompete clock reads recorded period ends only.
- **Buyer DNA lacks cycle-time metrics** (forecast→RFI→solicitation→award,
  amendment/extension/cancellation/protest rates). These need solicitation-to-
  award joins and GAO protest ingestion that aren't built; the shipped metrics
  are the ones public award data supports cleanly.
- **Procurement forecasts cover one API plus operator imports.** The DHS APFS
  adapter is built and failure-isolated but its live API is unreachable from
  restricted networks (validated against a fixture only — verify field names
  on first production run). All other agencies arrive via the provenance-
  enforced CSV import; no other agency exposes a usable forecast API.
  Forecast signals do not yet feed the decision stack's dimensions — they
  render as forecast lineage and the radar page.
- **Funding ladder is account-level.** The four exclusive funding labels are
  enforced, but President's Budget lines, appropriations bill status, and NDAA
  section links are not ingested; the dossier never claims more than the data
  supports.
- **Competitor/teaming panel is buyer-history-only.** Ranked competitors and
  gap-filling teaming candidates ship (dossier v3), but they draw solely on
  prime awards at this buyer: no cross-buyer vendor search, no mentor-protégé
  or JV data, no vehicle-holder lookup. Size standing is inferred from
  set-aside award history, not SBA certification data — the panel says so.
- **Incumbent vulnerability signals are a starter set** (bridge, set-aside
  change, requirement-change language, obligation rate). Protest history, IG/
  GAO findings, and exclusions are not yet ingested.
- **Proof mapping is token-based.** It surfaces candidate projects for a
  past-performance narrative and labels partial overlap as weak; it does not
  do semantic matching, and says so on the page.

## Product

- **Grants remain unbuilt** as a vertical (Grants.gov/Assistance Listings
  adapters not present). Kept deliberately separate rather than shoehorned
  into contract logic.
- **OCR for scanned PDFs** is still missing; scanned attachments show
  `unsupported`/`failed` extraction status and are flagged in the evidence
  ledger.
- **Amendment intelligence covers notice fields**, not document-version
  diffing (added/removed requirement text between attachment versions).
- **No Stripe billing** — plans and server-side entitlements are enforced;
  payment collection is absent.
- **Win probability is intentionally absent** until real outcomes exist to
  calibrate it (the decision stack is the honest substitute).
- **Demo data**: `scripts/seed_demo.py` exercises every dossier section with
  realistic shapes, but golden-set evaluation against live SAM.gov records
  requires a `SAM_API_KEY` and has not been run inside this environment.

## Operational

- Dossiers regenerate wholesale (no per-section freshness yet); the strip's
  completeness % and generated-at date are the freshness signals.
- MemoryStore mirrors PgStore for tests; a handful of newer read paths
  (change history) return simplified shapes in memory.
