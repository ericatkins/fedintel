"""Confidence model. Every major assertion in a dossier carries a 0-100
confidence and a source basis. Bands are product language, not decoration."""

BANDS = (
    (90, "confirmed or near-confirmed"),
    (75, "strong signal"),
    (50, "moderate signal"),
    (25, "weak signal"),
    (0, "insufficient support"),
)

# Evidence tiers — the truthfulness rule in code form
CONFIRMED = "confirmed_fact"
STRONG = "strong_signal"
WEAK = "weak_signal"
INFERRED = "inferred_likelihood"
UNAVAILABLE = "unavailable_from_public_data"


def band(score: int) -> str:
    score = max(0, min(100, int(score)))
    for floor, label in BANDS:
        if score >= floor:
            return label
    return BANDS[-1][1]


def claim(text: str, confidence: int, basis: str, sources: list | None = None) -> dict:
    """Uniform shape for every assertion the product makes."""
    return {
        "claim": text,
        "confidence": max(0, min(100, int(confidence))),
        "confidence_band": band(confidence),
        "basis": basis,
        "sources": sources or [],
    }
