"""Benjamini-Hochberg multiple testing correction."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BHDecision:
    """Auditable Benjamini-Hochberg decision for one hypothesis."""

    name: str
    raw_p_value: float
    adjusted_p_value: float
    critical_value: float
    rank: int
    rejected_null: bool


def benjamini_hochberg(p_values: dict[str, float], alpha: float = 0.05) -> dict[str, bool]:
    """Apply Benjamini-Hochberg correction to control FDR.

    Parameters
    ----------
    p_values
        Mapping of factor name to p-value.
    alpha
        Target false discovery rate.

    Returns
    -------
    Mapping of factor name to ``True`` if the factor is accepted
    (survives multiple testing), ``False`` otherwise.
    """
    return {
        name: decision.rejected_null
        for name, decision in benjamini_hochberg_details(p_values, alpha=alpha).items()
    }


def benjamini_hochberg_details(
    p_values: dict[str, float], alpha: float = 0.05
) -> dict[str, BHDecision]:
    """Return raw p-values, adjusted p-values, ranks, and BH decisions."""
    if not 0.0 < alpha < 1.0:
        raise ValueError("alpha must be between zero and one")

    m = len(p_values)
    if m == 0:
        return {}

    # Validate p-values
    for name, p in p_values.items():
        if not (0.0 <= p <= 1.0):
            raise ValueError(f"p-value for {name} is out of range [0, 1]: {p}")

    # Sort by p-value ascending
    sorted_items = sorted(p_values.items(), key=lambda item: (item[1], item[0]))

    # Find the largest k where p_(k) <= k/m * alpha
    max_k = 0
    for k, (_name, p) in enumerate(sorted_items, start=1):
        threshold = (k / m) * alpha
        if p <= threshold:
            max_k = k

    # Accept all factors with rank <= max_k
    accepted_names = {name for name, _ in sorted_items[:max_k]}

    adjusted_sorted = [0.0] * m
    running_min = 1.0
    for zero_based_rank in range(m - 1, -1, -1):
        rank = zero_based_rank + 1
        raw_p = sorted_items[zero_based_rank][1]
        running_min = min(running_min, raw_p * m / rank)
        adjusted_sorted[zero_based_rank] = min(running_min, 1.0)

    details: dict[str, BHDecision] = {}
    for zero_based_rank, (name, raw_p) in enumerate(sorted_items):
        rank = zero_based_rank + 1
        details[name] = BHDecision(
            name=name,
            raw_p_value=raw_p,
            adjusted_p_value=adjusted_sorted[zero_based_rank],
            critical_value=rank / m * alpha,
            rank=rank,
            rejected_null=name in accepted_names,
        )
    return {name: details[name] for name in p_values}
