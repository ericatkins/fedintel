"""Deterministic feedback learning — makes 'this improves your future matches'
TRUE, not marketing copy.

Design (bounded and explainable, per review):
- Feedback adjusts org-level weights on the features of that opportunity
  (naics:X, agency:Y, category:Z).
- Each feature weight is capped at ±10 (DB check constraint agrees).
- At scoring time the summed adjustment is capped at ±15 points.
- Every adjustment is visible on the profile page and resettable.
No opaque ML: an org can always see exactly why a score moved.
"""
FEEDBACK_DELTAS = {
    "good_match": +2, "track": +2, "save": +2, "watching": +2,
    "researching": +2, "pursuing": +3, "submitted": +3, "won": +3,
    "bad_match": -3, "ignore": -2, "ignored": -2, "lost": -1,
    "hide_similar": -8,
}
FEATURE_WEIGHT_CAP = 10      # per feature, per org
SCORE_ADJUSTMENT_CAP = 15    # total applied at scoring time


def features_for(opportunity: dict) -> list[str]:
    feats = []
    if opportunity.get("naics"):
        feats.append(f"naics:{opportunity['naics']}")
    if opportunity.get("agency"):
        feats.append(f"agency:{opportunity['agency']}")
    if opportunity.get("category"):
        feats.append(f"category:{opportunity['category']}")
    return feats


def clamp_weight(value: int) -> int:
    return max(-FEATURE_WEIGHT_CAP, min(FEATURE_WEIGHT_CAP, value))


def adjustment_for(features: list[str], weights: dict[str, int]) -> tuple[int, list[str]]:
    """(bounded score adjustment, human-readable reasons)."""
    total, reasons = 0, []
    for feat in features:
        w = weights.get(feat, 0)
        if w:
            total += w
            kind, _, value = feat.partition(":")
            direction = "boosted" if w > 0 else "lowered"
            reasons.append(f"learned preference: {kind} {value} {direction} ({w:+d})")
    total = max(-SCORE_ADJUSTMENT_CAP, min(SCORE_ADJUSTMENT_CAP, total))
    return total, reasons


def apply_learning(result: dict, opportunity: dict, weights: dict[str, int]) -> dict:
    """Adjust a classification result by org preferences; annotate reasons."""
    if not weights:
        return result
    adj, reasons = adjustment_for(features_for(opportunity), weights)
    if not adj:
        return result
    result = dict(result)
    result["score"] = max(0, min(100, result.get("score", 0) + adj))
    result["reasons"] = list(result.get("reasons", [])) + reasons
    return result
