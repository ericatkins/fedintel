"""Comparable-award value estimate: median + interquartile range with outlier
exclusion — honest about basis and never misled by one giant vehicle award."""
import statistics


def estimate(awards: list[dict]) -> dict | None:
    """awards: dossier last_10_relevant_awards. Returns None when there is no
    defensible basis (fewer than 2 usable amounts)."""
    amounts = sorted(float(a["obligated_amount"]) for a in awards or []
                     if a.get("obligated_amount"))
    if len(amounts) < 2:
        return None
    median = statistics.median(amounts)
    kept = [a for a in amounts if a <= 3 * median] or amounts
    excluded = len(amounts) - len(kept)
    kept_median = statistics.median(kept)
    q = statistics.quantiles(kept, n=4) if len(kept) >= 3 else [kept[0], kept_median,
                                                                kept[-1]]
    return {
        "low": q[0],
        "high": q[-1],
        "median": kept_median,
        "basis": len(kept),
        "outliers_excluded": excluded,
    }
