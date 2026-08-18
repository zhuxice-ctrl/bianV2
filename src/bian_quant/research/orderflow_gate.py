"""Development-only gate executor for the ``microstructure_orderflow`` family.

This module is **isolated from evidence collection**: it only *consumes*
ledger records / synthetic slice evaluations and pre-registered coverage
metadata.  It never reads production snapshots, never runs a real
Development, and never accesses Holdout / Candidate / Paper / Live.

Design invariants (enforced by tests):

* ``GateVerdict`` is constructed **only** on the primary-horizon /
  primary-q path inside :func:`evaluate_development_gate`.
* ``HorizonDiagnostics`` (2h / 4h) has **no verdict field** and always
  serialises with ``diagnostic_only = True`` — there is no code path
  from diagnostics to the verdict.
* The verdict computation path never imports the redundancy module and
  never reads the RankIC redundancy matrix — redundancy is attached
  *after* the verdict is produced via :func:`with_redundancy_disclosure`.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

import numpy as np

from bian_quant.research.orderflow_development import benjamini_hochberg

#: Pre-registered single linear direction for the family.  Immutable.
REGISTERED_DIRECTION = "positive"

#: RankIC magnitude above which two factors are flagged as near-equivalent.
REDUNDANCY_RANKIC_THRESHOLD = 0.7


class GateVerdict(StrEnum):
    """Possible gate outcomes.

    ``pass`` and ``fail`` are *conclusive* (the evaluation happened and
    coverage was sufficient).  ``insufficient`` means the evaluation
    happened but coverage was too thin to judge — it must never be read
    as "almost pass".  ``blocked`` means an execution precondition failed
    and no evaluation took place.
    """

    PASS = "pass"
    FAIL = "fail"
    INSUFFICIENT = "insufficient"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class SliceEvaluation:
    """A single (factor, horizon, q, fold, asset, regime) evaluation slice.

    ``p_value`` is ``None`` or NaN when the statistic could not be
    computed (still counts in the BH denominator semantics: a missing
    p-value is *not* a free skip — see :func:`_family_bh`).
    """

    factor_id: str
    horizon: str
    q: float
    fold: str
    asset: str
    regime: str
    p_value: float | None
    direction_estimate: float
    n_effective: int
    test_bar_indices: frozenset[int]


@dataclass(frozen=True)
class PreregisteredUnit:
    """A pre-registered (fold, asset, regime) coverage unit."""

    fold: str
    asset: str
    regime: str
    effective_bar_count: int
    missing_next_bar_count: int = 0
    execution_infeasible_count: int = 0

    @property
    def key(self) -> str:
        return f"{self.fold}|{self.asset}|{self.regime}"

    @property
    def excluded_count(self) -> int:
        return self.missing_next_bar_count + self.execution_infeasible_count

    @property
    def total_attempted(self) -> int:
        return self.effective_bar_count + self.excluded_count


@dataclass(frozen=True)
class GatePreconditions:
    """Execution preconditions for the gate (all must hold)."""

    universe_artifact_ok: bool
    snapshot_identity_ok: bool
    family_members_frozen_ok: bool
    protocol_sha_ok: bool
    failure_reasons: tuple[str, ...] = ()

    @property
    def all_ok(self) -> bool:
        return (
            self.universe_artifact_ok
            and self.snapshot_identity_ok
            and self.family_members_frozen_ok
            and self.protocol_sha_ok
        )


@dataclass(frozen=True)
class GateConfig:
    """Pre-registered, frozen gate thresholds.

    Defaults reflect the ``microstructure_orderflow`` family freeze
    (Batch 0 / unified plan).  Any change requires a new family snapshot.
    """

    family_id: str = "microstructure_orderflow"
    primary_horizon: str = "1h"
    primary_q: float = 0.2
    sensitivity_qs: tuple[float, ...] = (0.1, 0.2, 0.3)
    bh_alpha: float = 0.05
    min_surviving_slices: int = 2
    min_assets: int = 2
    max_concentration: float = 0.5
    min_direction_consistency: float = 0.6
    min_n_effective: int = 30
    min_bh_denominator: int = 1
    max_exclusion_ratio: float = 0.5
    registered_direction: str = REGISTERED_DIRECTION
    registered_factor_ids: tuple[str, ...] = ("taker_orderflow_imbalance",)
    required_horizons: tuple[str, ...] = ("1h", "2h", "4h")


@dataclass(frozen=True)
class HorizonDiagnostics:
    """Diagnostic-only output for non-primary horizons.

    Deliberately has **no** ``verdict`` field: there is no path from
    diagnostics to the gate verdict.  Always serialises with
    ``diagnostic_only = True``.
    """

    horizon: str
    q: float
    adjusted_p_values: tuple[tuple[str, str, str, float], ...]
    diagnostic_only: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "horizon": self.horizon,
            "q": self.q,
            "diagnostic_only": True,
            "adjusted_p_values": [
                {"fold": f, "asset": a, "regime": r, "bh_adjusted": float(p)}
                for f, a, r, p in self.adjusted_p_values
            ],
        }


@dataclass(frozen=True)
class CoverageReport:
    """Coverage details attached to every gate report."""

    preregistered_unit_count: int
    zero_bar_unit_keys: tuple[str, ...]
    exclusion_ratio: float
    bh_denominator: int
    min_bh_denominator: int
    insufficient_cell_slice_keys: tuple[str, ...]
    missing_slice_keys: tuple[str, ...] = ()
    duplicate_slice_keys: tuple[str, ...] = ()
    unexpected_slice_keys: tuple[str, ...] = ()
    missing_p_value_slice_keys: tuple[str, ...] = ()


@dataclass(frozen=True)
class RedundancyEntry:
    """Informational RankIC redundancy disclosure (not consumed by verdict)."""

    other_factor_id: str
    rankic: float
    label: str  # "" or "statistically_near_equivalent"


@dataclass(frozen=True)
class GateReport:
    """Final gate report.

    ``verdict`` is written **only** by :func:`evaluate_development_gate`.
    ``redundancy_disclosure`` is informational and attached afterwards
    via :func:`with_redundancy_disclosure`; it never influences the
    verdict.
    """

    verdict: GateVerdict
    reason_codes: tuple[str, ...]
    config: GateConfig
    coverage: CoverageReport
    surviving_slices: tuple[SliceEvaluation, ...]
    bh_summary: dict[str, Any]
    diagnostics: tuple[HorizonDiagnostics, ...]
    redundancy_disclosure: tuple[RedundancyEntry, ...] = ()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _slice_key(sl: SliceEvaluation) -> str:
    return f"{sl.fold}|{sl.asset}|{sl.regime}"


def _full_slice_key(
    factor_id: str,
    horizon: str,
    q: float,
    fold: str,
    asset: str,
    regime: str,
) -> str:
    return f"{factor_id}|{horizon}|q={q:g}|{fold}|{asset}|{regime}"


def _registered_qs(config: GateConfig) -> tuple[float, ...]:
    return tuple(sorted({float(config.primary_q), *(float(q) for q in config.sensitivity_qs)}))


def _expected_slice_keys(units: Sequence[PreregisteredUnit], config: GateConfig) -> set[str]:
    return {
        _full_slice_key(factor_id, horizon, q, unit.fold, unit.asset, unit.regime)
        for factor_id in config.registered_factor_ids
        for horizon in config.required_horizons
        for q in _registered_qs(config)
        for unit in units
    }


def _effective_p_value(sl: SliceEvaluation) -> float:
    if sl.p_value is None:
        return float("nan")
    v = float(sl.p_value)
    return v if np.isfinite(v) else float("nan")


def _family_bh(slices: Sequence[SliceEvaluation]) -> tuple[np.ndarray, int]:
    """Run BH across the whole family (all horizons, all q).

    Denominator *m* = count of valid (non-NaN) p-values — NaN-aware, so
    a missing p-value does *not* inflate the family but is also not a
    free skip (it simply does not survive).
    """
    p_vals = np.array([_effective_p_value(sl) for sl in slices], dtype=float)
    adjusted = benjamini_hochberg(p_vals)
    denominator = int(np.isfinite(p_vals).sum())
    return adjusted, denominator


def _survival_passes_bh(
    sl: SliceEvaluation,
    adjusted: float,
    config: GateConfig,
) -> bool:
    """A primary slice survives BH iff its adjusted p < alpha."""
    return np.isfinite(adjusted) and adjusted < config.bh_alpha


def _independence_violations(
    primary_candidates: Sequence[SliceEvaluation],
) -> set[str]:
    """Return keys of slices that violate the independence assertion.

    Two same-asset slices whose ``test_bar_indices`` intersect are both
    dropped — cross-asset overlap is allowed (that is an asset-diversity
    concern handled by the concentration thresholds).
    """
    violated: set[str] = set()
    n = len(primary_candidates)
    for i in range(n):
        a = primary_candidates[i]
        for j in range(i + 1, n):
            b = primary_candidates[j]
            if a.asset != b.asset:
                continue
            if (
                a.test_bar_indices
                and b.test_bar_indices
                and a.test_bar_indices & b.test_bar_indices
            ):
                violated.add(_slice_key(a))
                violated.add(_slice_key(b))
    return violated


def _concentration(items: Sequence[str]) -> dict[str, float]:
    if not items:
        return {}
    counts: dict[str, int] = {}
    for it in items:
        counts[it] = counts.get(it, 0) + 1
    total = len(items)
    return {k: v / total for k, v in counts.items()}


def _direction_matches(sl: SliceEvaluation, config: GateConfig) -> bool:
    """Whether the slice's point-estimate sign matches the registered direction."""
    if config.registered_direction == "positive":
        return sl.direction_estimate > 0
    if config.registered_direction == "negative":
        return sl.direction_estimate < 0
    return False


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def build_redundancy_disclosure(
    rankic_with_existing: Mapping[str, float],
    *,
    threshold: float = REDUNDANCY_RANKIC_THRESHOLD,
) -> tuple[RedundancyEntry, ...]:
    """Build an informational RankIC redundancy disclosure.

    Pure disclosure — never consumed by the verdict path.  Entries with
    ``|RankIC| > threshold`` are labelled ``statistically_near_equivalent``.
    """
    entries: list[RedundancyEntry] = []
    for other_id, rankic in rankic_with_existing.items():
        rankic = float(rankic)
        label = (
            "statistically_near_equivalent"
            if np.isfinite(rankic) and abs(rankic) > threshold
            else ""
        )
        entries.append(RedundancyEntry(other_factor_id=other_id, rankic=rankic, label=label))
    return tuple(sorted(entries, key=lambda e: e.other_factor_id))


def with_redundancy_disclosure(
    report: GateReport,
    disclosure: tuple[RedundancyEntry, ...],
) -> GateReport:
    """Attach an informational redundancy disclosure to a finished report.

    The verdict is **not** recomputed and the disclosure never feeds back
    into it.
    """
    return dataclasses.replace(report, redundancy_disclosure=disclosure)


def compute_horizon_diagnostics(
    slices: Sequence[SliceEvaluation],
    horizon: str,
    q: float,
) -> HorizonDiagnostics:
    """Compute diagnostic-only output for a non-primary horizon/q.

    Returns :class:`HorizonDiagnostics` which has **no** verdict field.
    """
    adjusted, _ = _family_bh(list(slices))
    rows: list[tuple[str, str, str, float]] = []
    for sl, adj in zip(slices, adjusted, strict=True):
        adj_val = float(adj) if np.isfinite(adj) else float("nan")
        rows.append((sl.fold, sl.asset, sl.regime, adj_val))
    return HorizonDiagnostics(horizon=horizon, q=q, adjusted_p_values=tuple(rows))


def evaluate_development_gate(
    slices: Sequence[SliceEvaluation],
    preregistered_units: Sequence[PreregisteredUnit],
    preconditions: GatePreconditions,
    *,
    config: GateConfig | None = None,
) -> GateReport:
    """Evaluate the development gate for the orderflow family.

    The verdict is produced **only** from the primary horizon / primary q
    path.  Non-primary horizons are returned as diagnostics via
    :func:`compute_horizon_diagnostics` (called by the caller); this
    function still emits a ``diagnostics`` slot populated for any
    non-primary slices present, but those diagnostics never affect the
    verdict.

    Parameters
    ----------
    slices
        All family slice evaluations (every horizon, every q).
    preregistered_units
        Pre-registered (fold, asset, regime) coverage units.
    preconditions
        Execution preconditions; if any fail the verdict is ``blocked``.
    config
        Frozen gate thresholds.  Defaults to the family freeze.
    """
    cfg = config or GateConfig()

    # --- 0. Blocked precondition check (no evaluation takes place) ---
    if not preconditions.all_ok:
        coverage = CoverageReport(
            preregistered_unit_count=len(preregistered_units),
            zero_bar_unit_keys=tuple(
                u.key for u in preregistered_units if u.effective_bar_count == 0
            ),
            exclusion_ratio=0.0,
            bh_denominator=0,
            min_bh_denominator=cfg.min_bh_denominator,
            insufficient_cell_slice_keys=(),
        )
        return GateReport(
            verdict=GateVerdict.BLOCKED,
            reason_codes=preconditions.failure_reasons or ("PRECONDITION_FAILED",),
            config=cfg,
            coverage=coverage,
            surviving_slices=(),
            bh_summary={"denominator": 0, "alpha": cfg.bh_alpha},
            diagnostics=(),
        )

    # --- 1. Validate the complete pre-registered slice grid ---
    unit_counts: dict[str, int] = {}
    for unit in preregistered_units:
        unit_counts[unit.key] = unit_counts.get(unit.key, 0) + 1
    duplicate_unit_keys = tuple(sorted(key for key, count in unit_counts.items() if count > 1))

    observed_counts: dict[str, int] = {}
    for sl in slices:
        key = _full_slice_key(sl.factor_id, sl.horizon, sl.q, sl.fold, sl.asset, sl.regime)
        observed_counts[key] = observed_counts.get(key, 0) + 1
    expected_keys = _expected_slice_keys(preregistered_units, cfg)
    observed_keys = set(observed_counts)
    missing_slice_keys = tuple(sorted(expected_keys - observed_keys))
    duplicate_slice_keys = tuple(sorted(key for key, count in observed_counts.items() if count > 1))
    unexpected_slice_keys = tuple(sorted(observed_keys - expected_keys))
    missing_p_value_slice_keys = tuple(
        sorted(
            _full_slice_key(sl.factor_id, sl.horizon, sl.q, sl.fold, sl.asset, sl.regime)
            for sl in slices
            if not np.isfinite(_effective_p_value(sl))
        )
    )

    # --- 2. Family BH across all slices (six-tuple, NaN-aware denominator) ---
    adjusted, denominator = _family_bh(list(slices))
    adj_by_key: dict[tuple[str, str, float, str, str, str], float] = {}
    for sl, adj in zip(slices, adjusted, strict=True):
        adj_by_key[(sl.factor_id, sl.horizon, sl.q, sl.fold, sl.asset, sl.regime)] = (
            float(adj) if np.isfinite(adj) else float("nan")
        )

    # --- 2. Coverage report ---
    zero_bar_units = tuple(u.key for u in preregistered_units if u.effective_bar_count == 0)
    total_excluded = sum(u.excluded_count for u in preregistered_units)
    total_attempted = sum(u.total_attempted for u in preregistered_units)
    exclusion_ratio = (total_excluded / total_attempted) if total_attempted else 0.0

    # --- 3. Primary slice candidates (primary horizon + primary q) ---
    primary_candidates = [
        sl for sl in slices if sl.horizon == cfg.primary_horizon and sl.q == cfg.primary_q
    ]

    # n < threshold slices are marked insufficient-cell and removed from survival
    insufficient_cells = tuple(
        _slice_key(sl) for sl in primary_candidates if sl.n_effective < cfg.min_n_effective
    )
    bh_survivors = [
        sl
        for sl in primary_candidates
        if sl.n_effective >= cfg.min_n_effective
        and _survival_passes_bh(
            sl,
            adj_by_key[(sl.factor_id, sl.horizon, sl.q, sl.fold, sl.asset, sl.regime)],
            cfg,
        )
    ]

    # --- 4. Independence assertion (same-asset overlapping index sets) ---
    independence_violations = _independence_violations(bh_survivors)
    survivors = [sl for sl in bh_survivors if _slice_key(sl) not in independence_violations]

    coverage = CoverageReport(
        preregistered_unit_count=len(preregistered_units),
        zero_bar_unit_keys=zero_bar_units,
        exclusion_ratio=exclusion_ratio,
        bh_denominator=denominator,
        min_bh_denominator=cfg.min_bh_denominator,
        insufficient_cell_slice_keys=insufficient_cells,
        missing_slice_keys=missing_slice_keys,
        duplicate_slice_keys=duplicate_slice_keys,
        unexpected_slice_keys=unexpected_slice_keys,
        missing_p_value_slice_keys=missing_p_value_slice_keys,
    )

    # --- 5. Diagnostics use the same full-family BH adjustment as the verdict. ---
    diagnostics: list[HorizonDiagnostics] = []
    non_primary_groups: dict[tuple[str, float], list[SliceEvaluation]] = {}
    adjusted_by_group: dict[tuple[str, float], list[tuple[str, str, str, float]]] = {}
    for sl in slices:
        if sl.horizon == cfg.primary_horizon and sl.q == cfg.primary_q:
            continue
        non_primary_groups.setdefault((sl.horizon, sl.q), []).append(sl)
    for sl, adjusted_value in zip(slices, adjusted, strict=True):
        if sl.horizon == cfg.primary_horizon and sl.q == cfg.primary_q:
            continue
        adjusted_by_group.setdefault((sl.horizon, sl.q), []).append(
            (
                sl.fold,
                sl.asset,
                sl.regime,
                float(adjusted_value) if np.isfinite(adjusted_value) else float("nan"),
            )
        )
    for (horizon, q), _group in sorted(non_primary_groups.items()):
        diagnostics.append(
            HorizonDiagnostics(
                horizon=horizon,
                q=q,
                adjusted_p_values=tuple(adjusted_by_group[(horizon, q)]),
            )
        )

    # --- 6. Verdict decision ---
    reason_codes: list[str] = []

    # 6a. Coverage-insufficient conditions → INSUFFICIENT (no pass/fail).
    #     These are hard triggers: incomplete coverage means the gate
    #     cannot issue a conclusive verdict regardless of survivor count.
    if zero_bar_units:
        reason_codes.append("ZERO_BAR_PREREGISTERED_UNIT")
    if denominator < cfg.min_bh_denominator:
        reason_codes.append("BH_DENOMINATOR_BELOW_MINIMUM")
    if total_attempted and exclusion_ratio > cfg.max_exclusion_ratio:
        reason_codes.append("EXCLUSION_RATIO_EXCEEDS_TOLERANCE")
    if insufficient_cells:
        reason_codes.append("INSUFFICIENT_CELL")
    if duplicate_unit_keys:
        reason_codes.append("DUPLICATE_PREREGISTERED_UNIT")
    if missing_slice_keys:
        reason_codes.append("PREREGISTERED_SLICE_MISSING")
    if duplicate_slice_keys:
        reason_codes.append("DUPLICATE_SLICE_KEY")
    if unexpected_slice_keys:
        reason_codes.append("UNREGISTERED_SLICE")
    if missing_p_value_slice_keys:
        reason_codes.append("MISSING_P_VALUE")
    if any(not np.isfinite(sl.direction_estimate) for sl in slices):
        reason_codes.append("MISSING_DIRECTION_ESTIMATE")

    coverage_blocking = (
        bool(zero_bar_units)
        or denominator < cfg.min_bh_denominator
        or (total_attempted and exclusion_ratio > cfg.max_exclusion_ratio)
        or bool(insufficient_cells)
        or bool(duplicate_unit_keys)
        or bool(missing_slice_keys)
        or bool(duplicate_slice_keys)
        or bool(unexpected_slice_keys)
        or bool(missing_p_value_slice_keys)
        or any(not np.isfinite(sl.direction_estimate) for sl in slices)
    )
    if coverage_blocking:
        return GateReport(
            verdict=GateVerdict.INSUFFICIENT,
            reason_codes=tuple(reason_codes),
            config=cfg,
            coverage=coverage,
            surviving_slices=tuple(survivors),
            bh_summary={
                "denominator": denominator,
                "alpha": cfg.bh_alpha,
                "primary_survivor_count": len(survivors),
            },
            diagnostics=tuple(diagnostics),
        )

    # 6b. Fewer than min surviving slices → gate cannot judge → insufficient.
    if len(survivors) < cfg.min_surviving_slices:
        if not reason_codes:
            reason_codes.append("SURVIVING_SLICES_BELOW_MINIMUM")
        return GateReport(
            verdict=GateVerdict.INSUFFICIENT,
            reason_codes=tuple(reason_codes),
            config=cfg,
            coverage=coverage,
            surviving_slices=tuple(survivors),
            bh_summary={
                "denominator": denominator,
                "alpha": cfg.bh_alpha,
                "primary_survivor_count": len(survivors),
            },
            diagnostics=tuple(diagnostics),
        )

    # 6c. Diversity thresholds → FAIL
    survivor_assets = [sl.asset for sl in survivors]
    survivor_regimes = [sl.regime for sl in survivors]
    asset_concentration = _concentration(survivor_assets)
    regime_concentration = _concentration(survivor_regimes)
    distinct_assets = len(set(survivor_assets))

    fail_reasons: list[str] = []
    if distinct_assets < cfg.min_assets:
        fail_reasons.append("ASSET_DIVERSITY_BELOW_MINIMUM")
    if asset_concentration and max(asset_concentration.values()) > cfg.max_concentration:
        fail_reasons.append("ASSET_CONCENTRATION_EXCEEDS_MAX")
    if regime_concentration and max(regime_concentration.values()) > cfg.max_concentration:
        fail_reasons.append("REGIME_CONCENTRATION_EXCEEDS_MAX")

    # 6d. Direction consistency → FAIL. The denominator is all valid primary
    # slices, not only BH survivors; otherwise opposite, non-significant
    # slices could be silently omitted from the registered-direction check.
    eligible_primary = [
        sl
        for sl in primary_candidates
        if sl.n_effective >= cfg.min_n_effective and np.isfinite(sl.direction_estimate)
    ]
    direction_matches = sum(1 for sl in eligible_primary if _direction_matches(sl, cfg))
    direction_consistency = direction_matches / len(eligible_primary) if eligible_primary else 0.0
    if direction_consistency < cfg.min_direction_consistency:
        fail_reasons.append("DIRECTION_CONSISTENCY_BELOW_MINIMUM")

    if fail_reasons:
        return GateReport(
            verdict=GateVerdict.FAIL,
            reason_codes=tuple(reason_codes + fail_reasons),
            config=cfg,
            coverage=coverage,
            surviving_slices=tuple(survivors),
            bh_summary={
                "denominator": denominator,
                "alpha": cfg.bh_alpha,
                "primary_survivor_count": len(survivors),
                "direction_consistency": direction_consistency,
                "asset_concentration": asset_concentration,
                "regime_concentration": regime_concentration,
            },
            diagnostics=tuple(diagnostics),
        )

    return GateReport(
        verdict=GateVerdict.PASS,
        reason_codes=tuple(reason_codes),
        config=cfg,
        coverage=coverage,
        surviving_slices=tuple(survivors),
        bh_summary={
            "denominator": denominator,
            "alpha": cfg.bh_alpha,
            "primary_survivor_count": len(survivors),
            "direction_consistency": direction_consistency,
            "asset_concentration": asset_concentration,
            "regime_concentration": regime_concentration,
        },
        diagnostics=tuple(diagnostics),
    )
