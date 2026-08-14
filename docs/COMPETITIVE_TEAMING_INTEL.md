# Competitive and Teaming Intelligence

`src/intel/competitors.py` — built into every dossier (v3+) and rendered as
the "Competitive landscape & teaming candidates" panel.

## Competitors

Ranked from actual buyer history, never from NAICS membership: only vendors
with awards in the dossier's linked pool appear. Strength combines award
count at this buyer, recency (≤ 3 years), obligations, and incumbency (the
incumbent is always marked and cross-referenced to the incumbent analysis's
confidence tiers). Each row carries a plain-language read:

- *incumbent — the vendor to beat or to team with*
- *repeat performer at this buyer — likely competitor*
- *recent performer — possible competitor*
- *historical performer only — weaker competitive signal*

## Teaming candidates

Each candidate names the gap it fills, with evidence:

- On a set-aside notice, a repeat performer whose awards were mostly **not**
  set-aside is flagged as likely other-than-small: they cannot prime, which
  makes a displaced incumbent or large performer a strong subcontract or
  mentor-protégé candidate.
- A vendor with mostly set-aside awards and much-smaller award sizes is a
  set-aside-eligible partner with proven buyer access (potential prime or
  co-bid partner).

## Disclosed limitations (rendered on the panel)

- Public prime-award data does not show subcontract relationships or vehicle
  holdings — rows are candidates, never confirmed relationships.
- Small-business standing is inferred from set-aside award history, not SBA
  certification records.
- An empty pool yields `insufficient_data` and an empty panel — competitors
  are never invented.
