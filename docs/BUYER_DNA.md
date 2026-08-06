# Buyer DNA

`src/intel/buyer_dna.py` — a peer-normalized behavioral profile of the buying
office, built into every dossier (v2+) and rendered on the opportunity page.

## Why peer-normalized

"This office retained incumbents 68% of the time" is a statistic. The
intelligence is: *materially higher than comparable offices purchasing the
same category*. Every comparison shows both numbers and the delta.

## Definitions

- **Office pool**: awards attributed to the buying office (the dossier's
  office-level pool from USAspending / SAM award records).
- **Peer pool**: awards from *other* offices in the same subtier purchasing
  the same NAICS, with this office's own awards excluded.

## Metrics compared

incumbent retention (repeat-vendor share of awards) · competition rate ·
set-aside share · Q4 (Jul–Sep) award concentration · top-vendor obligation
concentration. Office metrics additionally include median award, unique
vendors, and top vehicles.

## Discipline rules

- Comparison requires **≥ 8 awards on each side** (`MIN_POOL`); below that the
  panel says "insufficient data" and shows **no labels** — a confident profile
  from a handful of awards would be noise.
- A behavioral label (`incumbent-favoring`, `competition-limited`,
  `small-business accessible`, `Q4-driven`, `vendor-concentrated`) fires only
  on a **material** delta (≥ 15 percentage points).
- Every label carries its evidence (`office X% vs peer baseline Y% (+Zpp)`)
  and a "what this means for this pursuit" implication.
- Stated caveat: peer pools share subtier and NAICS, not mission or scale —
  deltas are behavioral signals, not verdicts.

## Known limitations

- `extent_competed` and `set_aside` strings from USAspending are heterogeneous;
  classification is deterministic (`_is_competed`) but conservative.
- Cycle-time metrics (forecast→RFI→solicitation→award) require solicitation-to-
  award joins that public data supports only partially; deliberately deferred
  rather than estimated badly.
