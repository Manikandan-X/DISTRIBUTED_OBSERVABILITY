"""Pure statistics helpers.

Percentile definition (used everywhere in the platform)
-------------------------------------------------------
We use the **nearest-rank** method: for N sorted values, the p-th percentile
is the value at 1-based rank ``ceil(p / 100 * N)`` (rank 1 for p == 0).
No interpolation is performed, so every reported percentile is a latency that
was really observed. Percentiles of different time buckets are never averaged
or merged; wider windows are recomputed from the raw samples.
"""

import math
from collections.abc import Iterable, Sequence


def percentile_nearest_rank(values: Sequence[float], percentile: float) -> float | None:
    if not 0 <= percentile <= 100:
        raise ValueError("percentile must be between 0 and 100")
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil(percentile / 100 * len(ordered)))
    return float(ordered[min(rank, len(ordered)) - 1])


def mean(values: Sequence[float]) -> float | None:
    return float(sum(values) / len(values)) if values else None


def error_rate_percent(error_count: int, request_count: int) -> float:
    return round(error_count / request_count * 100, 4) if request_count else 0.0


def throughput_per_second(request_count: int, window_seconds: float) -> float:
    return round(request_count / window_seconds, 6) if window_seconds > 0 else 0.0


def latency_summary(values: Iterable[float]) -> dict:
    data = [float(v) for v in values]
    return {
        "count": len(data),
        "average": mean(data),
        "minimum": min(data) if data else None,
        "maximum": max(data) if data else None,
        "p50": percentile_nearest_rank(data, 50),
        "p90": percentile_nearest_rank(data, 90),
        "p95": percentile_nearest_rank(data, 95),
        "p99": percentile_nearest_rank(data, 99),
    }
