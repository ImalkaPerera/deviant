"""Statistics for Deviant: Wilson lower bound and the reporting filter.

Pure functions only. No I/O, no git, no detector code.
"""

from math import sqrt

Z_95 = 1.96
DEFAULT_MIN_ITEMS = 20
DEFAULT_MIN_CONFIDENCE = 0.80
MAX_EXCEPTIONS = 3


def wilson_lower_bound(s: int, n: int, z: float = Z_95) -> float:
    """Lower bound of the Wilson score interval for s successes out of n."""
    if n <= 0:
        raise ValueError("n must be positive")
    if not 0 <= s <= n:
        raise ValueError("s must be between 0 and n")
    p = s / n
    z2 = z * z
    centre = p + z2 / (2 * n)
    margin = z * sqrt(p * (1 - p) / n + z2 / (4 * n * n))
    return (centre - margin) / (1 + z2 / n)


def passes_filter(
    s: int,
    n: int,
    min_items: int = DEFAULT_MIN_ITEMS,
    min_confidence: float = DEFAULT_MIN_CONFIDENCE,
) -> bool:
    """True if a rule with s followers out of n items should be reported.

    Rules: n >= min_items, 1 <= v <= 3 where v = n - s, and the Wilson lower
    bound of s/n is at least min_confidence.
    """
    v = n - s
    if n < min_items:
        return False
    if not 1 <= v <= MAX_EXCEPTIONS:
        return False
    return wilson_lower_bound(s, n) >= min_confidence
