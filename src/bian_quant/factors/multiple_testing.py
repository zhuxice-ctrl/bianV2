"""Benjamini-Hochberg multiple testing correction."""

from __future__ import annotations


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
    m = len(p_values)
    if m == 0:
        return {}

    # Validate p-values
    for name, p in p_values.items():
        if not (0.0 <= p <= 1.0):
            raise ValueError(f"p-value for {name} is out of range [0, 1]: {p}")

    # Sort by p-value ascending
    sorted_items = sorted(p_values.items(), key=lambda x: x[1])

    # Find the largest k where p_(k) <= k/m * alpha
    max_k = 0
    for k, (_name, p) in enumerate(sorted_items, start=1):
        threshold = (k / m) * alpha
        if p <= threshold:
            max_k = k

    # Accept all factors with rank <= max_k
    accepted_names = {name for name, _ in sorted_items[:max_k]}
    return {name: (name in accepted_names) for name in p_values}
