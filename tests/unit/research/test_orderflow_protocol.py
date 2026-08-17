"""Tests for orderflow portfolio diagnostics."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from bian_quant.research.orderflow_protocol import (
    build_orderflow_targets,
    compute_fee,
    compute_turnover_l1,
    drift_weights_open_to_open,
)


def _signals_for(n: int, *, start: float = 1.0) -> pd.DataFrame:
    """Create *n* assets with distinct ascending signal values."""
    assets = [f"ASSET{i:03d}" for i in range(n)]
    signals = [start + i for i in range(n)]
    return pd.DataFrame({"asset": assets, "signal": signals})


# ---------------------------------------------------------------------------
# build_orderflow_targets — leg construction
# ---------------------------------------------------------------------------


def test_twelve_signals_form_three_by_three_neutral_legs() -> None:
    result = build_orderflow_targets(_signals_for(12))
    assert (result.long_count, result.short_count) == (3, 3)
    assert result.weights.sum() == pytest.approx(0.0)
    assert result.weights.abs().sum() == pytest.approx(1.0)


def test_five_signals_are_flat() -> None:
    result = build_orderflow_targets(_signals_for(5))
    assert result.reason == "PORTFOLIO_INSUFFICIENT_COVERAGE"
    assert result.long_count == 0
    assert result.short_count == 0
    assert (result.weights == 0.0).all()


def test_six_signals_at_boundary_form_three_by_three() -> None:
    result = build_orderflow_targets(_signals_for(6))
    assert (result.long_count, result.short_count) == (3, 3)
    assert result.reason == ""


def test_twenty_signals_form_four_by_four() -> None:
    result = build_orderflow_targets(_signals_for(20))
    assert (result.long_count, result.short_count) == (4, 4)
    assert result.weights.sum() == pytest.approx(0.0)
    assert result.weights.abs().sum() == pytest.approx(1.0)


def test_long_weights_equal_short_weights_magnitude() -> None:
    result = build_orderflow_targets(_signals_for(12))
    longs = result.weights[result.weights > 0]
    shorts = result.weights[result.weights < 0]
    assert len(longs) == 3
    assert len(shorts) == 3
    assert np.allclose(longs.values, 0.5 / 3)
    assert np.allclose(shorts.values, -0.5 / 3)


def test_no_single_leg_exposure() -> None:
    """Every successful result must be perfectly balanced."""
    for n in [6, 7, 8, 10, 12, 15, 20, 30]:
        result = build_orderflow_targets(_signals_for(n))
        assert result.reason == ""
        assert result.weights.sum() == pytest.approx(0.0, abs=1e-12)
        assert result.weights.abs().sum() == pytest.approx(1.0)


def test_deterministic_tie_break_by_asset_name() -> None:
    """When signals are tied, asset name alphabetical order breaks ties."""
    df = pd.DataFrame(
        {
            "asset": ["ZEBRA", "ALPHA", "MANGO", "DELTA", "BRAVO", "CHARLIE"],
            "signal": [1.0] * 6,
        },
    )
    result = build_orderflow_targets(df)
    assert result.long_count == 3
    # Sorted by signal desc, asset asc:
    # ALPHA, BRAVO, CHARLIE, DELTA, MANGO, ZEBRA
    # Top 3 → long: ALPHA, BRAVO, CHARLIE
    # Bottom 3 → short: DELTA, MANGO, ZEBRA
    assert result.weights.loc["ALPHA"] > 0
    assert result.weights.loc["BRAVO"] > 0
    assert result.weights.loc["CHARLIE"] > 0
    assert result.weights.loc["DELTA"] < 0
    assert result.weights.loc["MANGO"] < 0
    assert result.weights.loc["ZEBRA"] < 0


def test_highest_signal_is_long_lowest_is_short() -> None:
    df = _signals_for(10)
    result = build_orderflow_targets(df)
    # ASSET009 has highest signal → long
    assert result.weights.loc["ASSET009"] > 0
    # ASSET000 has lowest signal → short
    assert result.weights.loc["ASSET000"] < 0


def test_build_targets_is_deterministic() -> None:
    """Same input must always produce the same output."""
    df = _signals_for(12)
    r1 = build_orderflow_targets(df)
    r2 = build_orderflow_targets(df.sample(frac=1, random_state=99).reset_index(drop=True))
    # Sort both by asset for comparison
    w1 = r1.weights.sort_index()
    w2 = r2.weights.sort_index()
    assert np.allclose(w1.values, w2.values)
    assert r1.long_count == r2.long_count
    assert r1.short_count == r2.short_count


def test_q_does_not_leak_into_result() -> None:
    """q sensitivity is report-only; it must not appear in output data."""
    result = build_orderflow_targets(_signals_for(12), q=0.2)
    assert not hasattr(result, "q")
    assert "q" not in result.weights.name


def test_invalid_q_raises() -> None:
    with pytest.raises(ValueError, match="q must be in"):
        build_orderflow_targets(_signals_for(12), q=0.0)
    with pytest.raises(ValueError, match="q must be in"):
        build_orderflow_targets(_signals_for(12), q=1.0)


def test_missing_columns_raises() -> None:
    bad = pd.DataFrame({"asset": ["A", "B"], "value": [1.0, 2.0]})
    with pytest.raises(ValueError, match="missing required columns"):
        build_orderflow_targets(bad)


# ---------------------------------------------------------------------------
# compute_turnover_l1 — first entry, liquidation, universe exit
# ---------------------------------------------------------------------------


def test_first_entry_turnover_is_one() -> None:
    """Going from flat (all-zero held) to target gives L1 = 1."""
    result = build_orderflow_targets(_signals_for(12))
    held = pd.Series(0.0, index=result.weights.index)
    turnover = compute_turnover_l1(result.weights, held)
    assert turnover == pytest.approx(1.0)


def test_all_flat_liquidation_incurs_cost() -> None:
    """Going from existing position to all-flat gives real turnover."""
    result = build_orderflow_targets(_signals_for(12))
    held = result.weights.copy()
    target = pd.Series(0.0, index=result.weights.index)
    turnover = compute_turnover_l1(target, held)
    assert turnover == pytest.approx(1.0)


def test_universe_exit_turnover() -> None:
    """An asset leaving the universe contributes its held weight to turnover."""
    result = build_orderflow_targets(_signals_for(12))
    held = result.weights.copy()
    # Drop one asset from target (it exits the universe)
    target = result.weights.drop("ASSET009")
    turnover = compute_turnover_l1(target, held)
    # The exited asset's held weight was +0.5/3, so turnover includes that
    assert turnover == pytest.approx(0.5 / 3)


def test_no_trade_turnover_is_zero() -> None:
    result = build_orderflow_targets(_signals_for(12))
    turnover = compute_turnover_l1(result.weights, result.weights)
    assert turnover == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# compute_fee
# ---------------------------------------------------------------------------


def test_fee_formula() -> None:
    assert compute_fee(1.0, 10.0) == pytest.approx(10.0 / 10000)
    assert compute_fee(0.5, 20.0) == pytest.approx(0.5 * 20.0 / 10000)
    assert compute_fee(0.0, 50.0) == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# drift_weights_open_to_open
# ---------------------------------------------------------------------------


def test_drift_hand_calculated() -> None:
    """Hand-calculated drift with known inputs.

    target = {A: +0.5, B: -0.5}
    returns = {A: +0.1, B: -0.1}
    portfolio_return = 0.5*0.1 + (-0.5)*(-0.1) = 0.05 + 0.05 = 0.10
    denominator = 1.10

    drifted_A = 0.5 * 1.1 / 1.1 = 0.5
    drifted_B = -0.5 * 0.9 / 1.1 = -0.4090909...
    """
    target = pd.Series({"A": 0.5, "B": -0.5})
    open_returns = pd.Series({"A": 0.1, "B": -0.1})
    drifted = drift_weights_open_to_open(target, open_returns)
    assert drifted.loc["A"] == pytest.approx(0.5)
    assert drifted.loc["B"] == pytest.approx(-0.5 * 0.9 / 1.1)


def test_drift_sum_matches_formula() -> None:
    """Drifted weight sum equals portfolio_return / (1 + portfolio_return).

    The drift formula does NOT preserve zero-sum — that is by design.
    The drifted weights represent the portfolio *before* rebalancing.
    """
    result = build_orderflow_targets(_signals_for(12))
    open_returns = pd.Series(
        np.random.default_rng(42).uniform(-0.05, 0.05, len(result.weights)),
        index=result.weights.index,
    )
    portfolio_return = float((result.weights * open_returns).sum())
    drifted = drift_weights_open_to_open(result.weights, open_returns)
    expected_sum = portfolio_return / (1.0 + portfolio_return)
    assert drifted.sum() == pytest.approx(expected_sum, abs=1e-12)


def test_drift_zero_returns_unchanged() -> None:
    target = pd.Series({"A": 0.5, "B": -0.5})
    open_returns = pd.Series({"A": 0.0, "B": 0.0})
    drifted = drift_weights_open_to_open(target, open_returns)
    assert drifted.loc["A"] == pytest.approx(0.5)
    assert drifted.loc["B"] == pytest.approx(-0.5)


def test_drift_nonpositive_denominator_raises() -> None:
    """If portfolio return <= -1, denominator is nonpositive → raise."""
    target = pd.Series({"A": 0.5, "B": -0.5})
    open_returns = pd.Series({"A": -3.0, "B": 1.0})
    # portfolio_return = 0.5*(-3) + (-0.5)*1 = -1.5 - 0.5 = -2.0
    # denominator = 1 + (-2) = -1 → raises
    with pytest.raises(ValueError, match="nonpositive drift denominator"):
        drift_weights_open_to_open(target, open_returns)


def test_drift_handles_missing_assets() -> None:
    """Assets in target but not returns are treated as zero return."""
    target = pd.Series({"A": 0.5, "B": -0.5, "C": 0.0})
    open_returns = pd.Series({"A": 0.1, "B": -0.1})
    drifted = drift_weights_open_to_open(target, open_returns)
    # C has no return → treated as 0 → drifted_C = 0.0 * 1.0 / denom = 0.0
    assert drifted.loc["C"] == pytest.approx(0.0)


def test_drift_rejects_missing_return_for_active_asset() -> None:
    target = pd.Series({"A": 0.5, "B": -0.5})
    open_returns = pd.Series({"A": 0.1})
    with pytest.raises(ValueError, match="EXECUTION_BAR_INVALID"):
        drift_weights_open_to_open(target, open_returns)


def test_prefix_invariance_drift() -> None:
    """Adding a zero-weight asset should not change drifted weights."""
    target = pd.Series({"A": 0.5, "B": -0.5})
    open_returns = pd.Series({"A": 0.1, "B": -0.1})

    target_extra = pd.Series({"A": 0.5, "B": -0.5, "C": 0.0})
    open_returns_extra = pd.Series({"A": 0.1, "B": -0.1, "C": 0.05})

    d1 = drift_weights_open_to_open(target, open_returns)
    d2 = drift_weights_open_to_open(target_extra, open_returns_extra)

    assert d2.loc["A"] == pytest.approx(d1.loc["A"])
    assert d2.loc["B"] == pytest.approx(d1.loc["B"])
