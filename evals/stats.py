"""Small statistics helpers (no third-party dependencies)."""
from __future__ import annotations

import math
from collections.abc import Sequence

Z95 = 1.959963984540054


def wilson(k: int, n: int, z: float = Z95) -> tuple[float, float]:
    """Wilson score interval for k successes in n trials (95% by default). n == 0 gives (0.0, 1.0): no information."""
    if n < 0 or k < 0 or k > n:
        raise ValueError(f"need 0 <= k <= n, got k={k}, n={n}")
    if n == 0:
        return 0.0, 1.0
    p = k / n
    z2 = z * z
    denom = 1 + z2 / n
    centre = (p + z2 / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


def fmt_kn(k: int, n: int) -> str:
    """'k/n (xx% [lo-hi])' with the Wilson 95% interval, in whole percent."""
    if n == 0:
        return "n/a (0 trials)"
    lo, hi = wilson(k, n)
    return f"{k}/{n} ({100 * k / n:.0f}%, 95% CI {100 * lo:.0f}-{100 * hi:.0f}%)"


def median(xs: Sequence[float]) -> float | None:
    return percentile(xs, 50)


def percentile(xs: Sequence[float], q: float) -> float | None:
    """Linear-interpolation percentile (the numpy default), q in [0, 100]. None for an empty list."""
    if not xs:
        return None
    if not 0 <= q <= 100:
        raise ValueError("q must be between 0 and 100")
    s = sorted(xs)
    pos = (len(s) - 1) * q / 100
    lo, hi = math.floor(pos), math.ceil(pos)
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)


def p95(xs: Sequence[float]) -> float | None:
    return percentile(xs, 95)
