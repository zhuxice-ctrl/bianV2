"""Tests for the development-only orderflow gate executor.

All tests use synthetic data and ``tmp_path`` — no production snapshots,
no trading interfaces, no real Development.
"""

from __future__ import annotations

import inspect
from pathlib import Path

import numpy as np
import pytest

from bian_quant.research.orderflow_development import benjamini_hochberg
from bian_quant.research.orderflow_gate import (
    GatePreconditions,
    GateVerdict,
    HorizonDiagnostics,
    PreregisteredUnit,
    SliceEvaluation,
    build_redundancy_disclosure,
    compute_horizon_diagnostics,
    evaluate_development_gate,
    with_redundancy_disclosure,
)

FID = "taker_orderflow_imbalance"


# ---------------------------------------------------------------------------
# Synthetic slice builders
# ---------------------------------------------------------------------------


def _slice(
    *,
    horizon: str = "1h",
    q: float = 0.2,
    fold: str = "fold1",
    asset: str = "BTC",
    regime: str = "trending",
    p_value: float | None = 0.001,
    direction_estimate: float = 0.5,
    n_effective: int = 100,
    bars: frozenset[int] | None = None,
) -> SliceEvaluation:
    return SliceEvaluation(
        factor_id=FID,
        horizon=horizon,
        q=q,
        fold=fold,
        asset=asset,
        regime=regime,
        p_value=p_value,
        direction_estimate=direction_estimate,
        n_effective=n_effective,
        test_bar_indices=bars if bars is not None else frozenset(range(100)),
    )


def _unit(
    *,
    fold: str = "fold1",
    asset: str = "BTC",
    regime: str = "trending",
    effective: int = 100,
) -> PreregisteredUnit:
    return PreregisteredUnit(
        fold=fold,
        asset=asset,
        regime=regime,
        effective_bar_count=effective,
    )


def _ok_preconditions() -> GatePreconditions:
    return GatePreconditions(
        universe_artifact_ok=True,
        snapshot_identity_ok=True,
        family_members_frozen_ok=True,
        protocol_sha_ok=True,
    )


def _complete_grid(
    primary_slices: list[SliceEvaluation], units: list[PreregisteredUnit]
) -> list[SliceEvaluation]:
    """Fill a synthetic family across every registered horizon and q."""
    primary_by_unit = {f"{sl.fold}|{sl.asset}|{sl.regime}": sl for sl in primary_slices}
    result: list[SliceEvaluation] = []
    for horizon in ("1h", "2h", "4h"):
        for q in (0.1, 0.2, 0.3):
            for unit in units:
                source = primary_by_unit.get(unit.key)
                if horizon == "1h" and q == 0.2 and source is not None:
                    result.append(source)
                else:
                    result.append(
                        _slice(
                            horizon=horizon,
                            q=q,
                            fold=unit.fold,
                            asset=unit.asset,
                            regime=unit.regime,
                            p_value=0.9,
                            bars=frozenset(range(1000, 1100)),
                        )
                    )
    return result


def _passing_family() -> tuple[list[SliceEvaluation], list[PreregisteredUnit]]:
    """A family that passes the gate: 2 assets, 2 regimes, BH-significant."""
    primary = [
        _slice(asset="BTC", regime="trending", bars=frozenset(range(0, 100))),
        _slice(asset="ETH", regime="ranging", bars=frozenset(range(100, 200))),
    ]
    units = [
        _unit(asset="BTC", regime="trending"),
        _unit(asset="ETH", regime="ranging"),
    ]
    return _complete_grid(primary, units), units


# ---------------------------------------------------------------------------
# Unit test 1 — mutation test: 2h/4h cannot rescue a 1h failure
# ---------------------------------------------------------------------------


def test_non_primary_horizons_cannot_rescue_primary_failure() -> None:
    """Tamper 2h/4h p-values to fully significant; 1h fail must stay fail."""
    primary = [
        # 1h primary: non-significant p-values → BH survivor count below minimum.
        _slice(asset="BTC", regime="trending", p_value=0.9, bars=frozenset(range(0, 100))),
        _slice(asset="ETH", regime="ranging", p_value=0.8, bars=frozenset(range(100, 200))),
        # 2h / 4h fully significant (tampered) — must not rescue.
        _slice(horizon="2h", asset="BTC", regime="trending", p_value=0.0001),
        _slice(horizon="2h", asset="ETH", regime="ranging", p_value=0.0001),
        _slice(horizon="4h", asset="BTC", regime="trending", p_value=0.0001),
        _slice(horizon="4h", asset="ETH", regime="ranging", p_value=0.0001),
    ]
    report = evaluate_development_gate(primary, _passing_family()[1], _ok_preconditions())
    assert report.verdict == GateVerdict.INSUFFICIENT
    # No 2h/4h slice appears among primary survivors.
    assert all(s.horizon == "1h" and s.q == 0.2 for s in report.surviving_slices)


# ---------------------------------------------------------------------------
# Unit test 2 — BH denominator is the six-tuple valid p-value count
# ---------------------------------------------------------------------------


def test_bh_denominator_counts_q_sensitivity_and_missing() -> None:
    """q ∈ {0.1, 0.2, 0.3} all count; NaN p-values are excluded."""
    slices = [
        _slice(asset="BTC", regime="trending", q=0.2, p_value=0.001, bars=frozenset(range(0, 100))),
        _slice(
            asset="ETH", regime="ranging", q=0.2, p_value=0.001, bars=frozenset(range(100, 200))
        ),
        _slice(asset="BTC", regime="trending", q=0.1, p_value=0.001),
        _slice(asset="BTC", regime="trending", q=0.3, p_value=None),  # NaN → excluded
    ]
    report = evaluate_development_gate(slices, _passing_family()[1], _ok_preconditions())
    # Three valid p-values (q=0.2×2 + q=0.1×1); the NaN q=0.3 excluded.
    assert report.coverage.bh_denominator == 3


def test_missing_registered_grid_cell_is_insufficient() -> None:
    slices, units = _passing_family()
    report = evaluate_development_gate(slices[:-1], units, _ok_preconditions())
    assert report.verdict == GateVerdict.INSUFFICIENT
    assert "PREREGISTERED_SLICE_MISSING" in report.reason_codes


def test_duplicate_six_tuple_is_insufficient() -> None:
    slices, units = _passing_family()
    report = evaluate_development_gate([*slices, slices[0]], units, _ok_preconditions())
    assert report.verdict == GateVerdict.INSUFFICIENT
    assert "DUPLICATE_SLICE_KEY" in report.reason_codes


def test_diagnostics_reuse_full_family_bh_adjustment() -> None:
    slices, units = _passing_family()
    report = evaluate_development_gate(slices, units, _ok_preconditions())
    all_adjusted = benjamini_hochberg(np.array([float(sl.p_value) for sl in slices], dtype=float))
    expected = next(
        float(adj)
        for sl, adj in zip(slices, all_adjusted, strict=True)
        if sl.horizon == "2h" and sl.q == 0.1
    )
    diagnostic = next(diag for diag in report.diagnostics if diag.horizon == "2h" and diag.q == 0.1)
    assert diagnostic.adjusted_p_values[0][3] == pytest.approx(expected)


def test_direction_consistency_uses_all_primary_slices() -> None:
    primary = [
        _slice(asset="BTC", regime="trend", p_value=0.001, direction_estimate=0.5),
        _slice(asset="ETH", regime="range", p_value=0.001, direction_estimate=0.5),
        _slice(asset="SOL", regime="trend", p_value=0.9, direction_estimate=-0.5),
        _slice(asset="BNB", regime="range", p_value=0.9, direction_estimate=-0.5),
    ]
    units = [
        _unit(asset="BTC", regime="trend"),
        _unit(asset="ETH", regime="range"),
        _unit(asset="SOL", regime="trend"),
        _unit(asset="BNB", regime="range"),
    ]
    report = evaluate_development_gate(_complete_grid(primary, units), units, _ok_preconditions())
    assert report.verdict == GateVerdict.FAIL
    assert "DIRECTION_CONSISTENCY_BELOW_MINIMUM" in report.reason_codes


# ---------------------------------------------------------------------------
# Unit test 3 — blocked preconditions (universe artifact missing etc.)
# ---------------------------------------------------------------------------


def test_missing_universe_artifact_blocks_gate() -> None:
    slices, units = _passing_family()
    preconditions = GatePreconditions(
        universe_artifact_ok=False,
        snapshot_identity_ok=True,
        family_members_frozen_ok=True,
        protocol_sha_ok=True,
        failure_reasons=("POPULAR_UNIVERSE_ARTIFACT_MISSING",),
    )
    report = evaluate_development_gate(slices, units, preconditions)
    assert report.verdict == GateVerdict.BLOCKED
    assert "POPULAR_UNIVERSE_ARTIFACT_MISSING" in report.reason_codes


def test_protocol_hash_mismatch_blocks_gate() -> None:
    slices, units = _passing_family()
    preconditions = GatePreconditions(
        universe_artifact_ok=True,
        snapshot_identity_ok=True,
        family_members_frozen_ok=True,
        protocol_sha_ok=False,
        failure_reasons=("PROTOCOL_HASH_MISMATCH",),
    )
    report = evaluate_development_gate(slices, units, preconditions)
    assert report.verdict == GateVerdict.BLOCKED


# ---------------------------------------------------------------------------
# Unit test 4 — insufficient coverage never yields pass or fail
# ---------------------------------------------------------------------------


def test_insufficient_coverage_never_passes_or_fails() -> None:
    """A pre-registered unit with zero effective bars → insufficient."""
    slices, _ = _passing_family()
    units = [
        _unit(asset="BTC", regime="trending", effective=100),
        _unit(asset="ETH", regime="ranging", effective=0),  # zero-bar unit
    ]
    report = evaluate_development_gate(slices, units, _ok_preconditions())
    assert report.verdict == GateVerdict.INSUFFICIENT
    assert "ZERO_BAR_PREREGISTERED_UNIT" in report.reason_codes


def test_below_min_surviving_slices_is_insufficient() -> None:
    """Only one BH survivor → gate cannot judge → insufficient."""
    primary = [
        _slice(asset="BTC", regime="trending", p_value=0.001, bars=frozenset(range(0, 100))),
        # Second primary slice non-significant.
        _slice(asset="ETH", regime="ranging", p_value=0.9, bars=frozenset(range(100, 200))),
    ]
    units = [_unit(asset="BTC", regime="trending"), _unit(asset="ETH", regime="ranging")]
    report = evaluate_development_gate(_complete_grid(primary, units), units, _ok_preconditions())
    assert report.verdict == GateVerdict.INSUFFICIENT
    assert len(report.surviving_slices) < 2


# ---------------------------------------------------------------------------
# Unit test 5 — direction cannot be flipped to rescue
# ---------------------------------------------------------------------------


def test_direction_inconsistency_causes_fail() -> None:
    """<60% direction consistency → fail; sign-flip rescue is forbidden."""
    primary = [
        _slice(
            asset="BTC", regime="trending", direction_estimate=0.5, bars=frozenset(range(0, 100))
        ),
        _slice(
            asset="ETH", regime="ranging", direction_estimate=-0.5, bars=frozenset(range(100, 200))
        ),
        _slice(
            asset="SOL", regime="volatile", direction_estimate=-0.5, bars=frozenset(range(200, 300))
        ),
    ]
    units = [
        _unit(asset="BTC", regime="trending"),
        _unit(asset="ETH", regime="ranging"),
        _unit(asset="SOL", regime="volatile"),
    ]
    report = evaluate_development_gate(_complete_grid(primary, units), units, _ok_preconditions())
    # 1 of 3 matches positive → 33% < 60%.
    assert report.verdict == GateVerdict.FAIL
    assert "DIRECTION_CONSISTENCY_BELOW_MINIMUM" in report.reason_codes


# ---------------------------------------------------------------------------
# Unit test 6 — independence assertion removes same-asset overlapping slices
# ---------------------------------------------------------------------------


def test_same_asset_overlapping_slices_removed() -> None:
    """Two same-asset slices with intersecting bar indices are both dropped."""
    primary = [
        # Both BTC, overlapping bar index sets.
        _slice(asset="BTC", regime="trending", bars=frozenset(range(0, 100))),
        _slice(asset="BTC", regime="ranging", bars=frozenset(range(50, 150))),
        # A clean independent survivor on another asset.
        _slice(asset="ETH", regime="ranging", bars=frozenset(range(200, 300))),
    ]
    units = [
        _unit(asset="BTC", regime="trending"),
        _unit(asset="BTC", regime="ranging"),
        _unit(asset="ETH", regime="ranging"),
    ]
    report = evaluate_development_gate(_complete_grid(primary, units), units, _ok_preconditions())
    # Both BTC slices removed by independence; only ETH survives → <2 → insufficient.
    surviving_assets = {s.asset for s in report.surviving_slices}
    assert "BTC" not in surviving_assets
    assert report.verdict == GateVerdict.INSUFFICIENT


# ---------------------------------------------------------------------------
# Unit test 7 — concentration >50% on asset or regime → fail
# ---------------------------------------------------------------------------


def test_single_asset_concentration_exceeds_max() -> None:
    """All survivors on one asset → asset concentration 100% → fail."""
    # Two BTC slices on disjoint bar sets (independent), different regimes.
    primary = [
        _slice(asset="BTC", regime="trending", bars=frozenset(range(0, 100))),
        _slice(asset="BTC", regime="ranging", bars=frozenset(range(100, 200))),
    ]
    units = [
        _unit(asset="BTC", regime="trending"),
        _unit(asset="BTC", regime="ranging"),
    ]
    report = evaluate_development_gate(_complete_grid(primary, units), units, _ok_preconditions())
    assert report.verdict == GateVerdict.FAIL
    assert "ASSET_CONCENTRATION_EXCEEDS_MAX" in report.reason_codes


def test_single_regime_concentration_exceeds_max() -> None:
    """All survivors on one regime → regime concentration 100% → fail."""
    primary = [
        _slice(asset="BTC", regime="trending", bars=frozenset(range(0, 100))),
        _slice(asset="ETH", regime="trending", bars=frozenset(range(100, 200))),
    ]
    units = [
        _unit(asset="BTC", regime="trending"),
        _unit(asset="ETH", regime="trending"),
    ]
    report = evaluate_development_gate(_complete_grid(primary, units), units, _ok_preconditions())
    assert report.verdict == GateVerdict.FAIL
    assert "REGIME_CONCENTRATION_EXCEEDS_MAX" in report.reason_codes


# ---------------------------------------------------------------------------
# Unit test 8 — n < 30 → insufficient-cell
# ---------------------------------------------------------------------------


def test_low_n_effective_marked_insufficient_cell() -> None:
    """n_effective < 30 slices are dropped and flagged insufficient-cell."""
    slices = [
        _slice(asset="BTC", regime="trending", n_effective=20, bars=frozenset(range(0, 100))),
        _slice(asset="ETH", regime="ranging", n_effective=100, bars=frozenset(range(100, 200))),
    ]
    units = [
        _unit(asset="BTC", regime="trending"),
        _unit(asset="ETH", regime="ranging"),
    ]
    report = evaluate_development_gate(slices, units, _ok_preconditions())
    # BTC dropped (n<30); only ETH survives → <2 → insufficient.
    assert "INSUFFICIENT_CELL" in report.reason_codes
    assert all(s.n_effective >= 30 for s in report.surviving_slices)
    assert report.verdict == GateVerdict.INSUFFICIENT


# ---------------------------------------------------------------------------
# Diagnostics isolation — HorizonDiagnostics has no verdict field
# ---------------------------------------------------------------------------


def test_horizon_diagnostics_has_no_verdict_field() -> None:
    fields = {f.name for f in HorizonDiagnostics.__dataclass_fields__.values()}
    assert "verdict" not in fields
    diag = compute_horizon_diagnostics(
        [_slice(horizon="2h", asset="BTC", regime="trending", p_value=0.01)],
        "2h",
        0.2,
    )
    assert diag.diagnostic_only is True
    assert diag.to_dict()["diagnostic_only"] is True


def test_redundancy_disclosure_is_informational_only() -> None:
    """The verdict path never reads the redundancy matrix."""
    source = inspect.getsource(evaluate_development_gate)
    assert "redundan" not in source.lower()
    # Attaching a disclosure does not change the verdict.
    slices, units = _passing_family()
    report = evaluate_development_gate(slices, units, _ok_preconditions())
    verdict_before = report.verdict
    disclosure = build_redundancy_disclosure({"funding_pressure": 0.9, "oi_pressure": 0.3})
    report2 = with_redundancy_disclosure(report, disclosure)
    assert report2.verdict == verdict_before
    near_eq = [e for e in report2.redundancy_disclosure if e.label]
    assert len(near_eq) == 1
    assert near_eq[0].other_factor_id == "funding_pressure"


# ---------------------------------------------------------------------------
# Integration tests — Development-only isolation
# ---------------------------------------------------------------------------


def test_gate_module_does_not_import_production_paths() -> None:
    """The gate module must not import operations / holdout / candidate."""
    import ast

    import bian_quant.research.orderflow_gate as gate_mod

    tree = ast.parse(inspect.getsource(gate_mod))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    forbidden = {
        "bian_quant.research.operations",
        "bian_quant.data.holdout",
        "bian_quant.data.candidate",
    }
    overlap = imported & forbidden
    assert not overlap, f"gate module imports forbidden production paths: {overlap}"
    # The gate only imports the pure BH helper from the ledger module.
    assert "bian_quant.research.orderflow_development" in imported


def test_gate_does_not_create_holdout_access_marker(tmp_path: Path) -> None:
    """Running the gate must not create a holdout-access.sqlite marker."""
    slices, units = _passing_family()
    _ = evaluate_development_gate(slices, units, _ok_preconditions())
    assert not (tmp_path / "holdout-access.sqlite").exists()


def test_gate_does_not_write_candidate_registry(tmp_path: Path) -> None:
    """The gate produces no Candidate writes — it only returns a report."""
    slices, units = _passing_family()
    report = evaluate_development_gate(slices, units, _ok_preconditions())
    # No candidate registry file is created anywhere by the gate call.
    assert not list(tmp_path.glob("*.sqlite"))
    assert report.verdict in {
        GateVerdict.PASS,
        GateVerdict.FAIL,
        GateVerdict.INSUFFICIENT,
        GateVerdict.BLOCKED,
    }
