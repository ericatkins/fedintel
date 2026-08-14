"""Requirement deltas across lifecycle stages and amendments.

When a solicitation moves through its lineage (Sources Sought → draft → RFP →
amendment), the extracted requirement set changes. This module diffs the
deterministic requirement extractions of two notices in the same lineage so
the page can say exactly what an amendment added or removed — the changes
that most often invalidate a bid plan.

Honesty rule: extraction absence is not document absence. A "removed"
requirement means the rule no longer fires on the newer notice's documents —
which usually means the text changed, and always means "reread the document",
not "the obligation vanished". The UI copy carries that caveat.
"""


def _key(req: dict) -> tuple[str, str]:
    return (req.get("requirement_type") or "", (req.get("value") or "").lower())


def diff_requirements(older: list[dict], newer: list[dict]) -> dict:
    """Diff two extracted-requirement lists. Pure; order-insensitive."""
    old_map = {_key(r): r for r in older or []}
    new_map = {_key(r): r for r in newer or []}
    added = [new_map[k] for k in new_map.keys() - old_map.keys()]
    removed = [old_map[k] for k in old_map.keys() - new_map.keys()]
    added.sort(key=_key)
    removed.sort(key=_key)
    return {
        "added": added,
        "removed": removed,
        "unchanged_count": len(new_map.keys() & old_map.keys()),
        "comparable": bool(older) and bool(newer),
    }


def lineage_requirement_delta(current_opp_id: int, lineage_rows: list[dict],
                              requirements_by_opp: dict[int, list[dict]]) -> dict | None:
    """Compare the current notice's requirements against the nearest earlier
    lineage stage that has any extraction. Returns None when there is nothing
    defensible to compare."""
    earlier_ids = [row["opportunity_id"] for row in lineage_rows or []
                   if row.get("opportunity_id") != current_opp_id]
    current = requirements_by_opp.get(current_opp_id) or []
    if not current:
        return None
    for prior_id in reversed(earlier_ids):        # nearest earlier stage first
        prior = requirements_by_opp.get(prior_id) or []
        if prior:
            delta = diff_requirements(prior, current)
            delta["compared_against_opportunity_id"] = prior_id
            return delta
    return None
