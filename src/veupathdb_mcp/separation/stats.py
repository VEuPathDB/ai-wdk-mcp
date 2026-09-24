"""The one exact tail a separation reads its controls by."""

import math


def _log_binomial(a: int, b: int) -> float:
    """Log of the binomial coefficient C(a, b), for 0 <= b <= a."""
    return math.lgamma(a + 1) - math.lgamma(b + 1) - math.lgamma(a - b + 1)


def hypergeometric_log_sf(x: int, n: int, k: int, m: int) -> float:
    """Log of the exact upper tail P(X >= x) for Hypergeometric(n, k, m).

    ``n`` is the population, ``k`` the successes it holds, ``m`` the draws.
    """
    if n < 1 or not 0 <= k <= n or not 0 <= m <= n:
        msg = f"not a hypergeometric distribution: n={n}, k={k}, m={m}"
        raise ValueError(msg)

    lowest = max(0, m + k - n)
    highest = min(k, m)
    if x <= lowest:
        return 0.0
    if x > highest:
        return -math.inf

    log_total = _log_binomial(n, m)
    log_terms = [
        _log_binomial(k, i) + _log_binomial(n - k, m - i) - log_total
        for i in range(x, highest + 1)
    ]
    peak = max(log_terms)
    return peak + math.log(math.fsum(math.exp(t - peak) for t in log_terms))
