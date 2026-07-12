"""Shared statistics helper for order-flow features (absorption, exhaustion).
Not a feature itself -- keeps the z-score definition identical everywhere
it's used rather than three independent, silently-divergent copies.
"""
import statistics


def rolling_zscore(values: list, index: int, lookback: int) -> float:
    """Z-score of values[index] against the trailing `lookback` values
    strictly BEFORE index (excludes index itself, so a bar can't inflate
    its own baseline). Returns 0.0 on insufficient history or zero variance
    -- callers gate on a minimum z-score, so 0.0 always means "does not
    qualify," never a false positive.
    """
    start = index - lookback
    if start < 0:
        return 0.0
    window = values[start:index]
    if len(window) < 2:
        return 0.0
    mean = statistics.mean(window)
    stdev = statistics.pstdev(window)
    if stdev == 0:
        return 0.0
    return (values[index] - mean) / stdev
