"""Explainable heuristic evidence score, deliberately not a probability."""
import math


def confidence(candidate: dict, verification: dict, minimum_overlap: float = 1.0) -> tuple[float, str]:
    if not verification.get("verified"):
        return 0.0, verification.get("reason", "unverified")
    support = candidate["support"]
    span = candidate["span_seconds"]
    overlap = verification["overlap_seconds"]
    alternative = candidate["alternative_support"]
    separation = max(0.0, 1-alternative/max(1, support))
    components = {
        "landmarks": 25 * min(1, support/20),
        "coverage": 20 * min(1, max(span/max(0.1, overlap), verification["verification_coverage"])*1.25),
        "correlation": 25 * min(1, verification["correlation"]/0.25),
        "consistency": 15 * math.exp(-verification["offset_spread_seconds"]/0.015),
        "uniqueness": 15 * separation,
    }
    score = round(min(100, sum(components.values())), 2)
    verification["score_components"] = components
    if support < 8 or span < min(0.7, minimum_overlap) or overlap < minimum_overlap:
        return min(score, 49), "insufficient_evidence"
    if alternative >= support * 0.8:
        return min(score, 49), "ambiguous_repeated_content"
    return score, "verified"
