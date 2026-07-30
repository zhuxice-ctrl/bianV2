"""Unit tests for causal five-year Macro regime evidence (Task 7).

These tests use synthetic data to verify prefix invariance and causal
threshold fitting without requiring real Binance data.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from bian_quant.regimes.macro import (
    MacroRegimeEvidence,
    MacroState,
    classify_macro_history,
    summarize_comparable_episodes,
    write_macro_evidence,
)


def _make_synthetic_frame(n: int = 500, seed: int = 42) -> pd.DataFrame:
    """Create a synthetic frame with enough variation for regime classification."""
    rng = np.random.default_rng(seed)
    # Mix of trend and range regimes
    close = [100.0]
    volume = [1000.0]
    for i in range(1, n):
        ret = rng.normal(0.002, 0.01) if i % 100 < 50 else rng.normal(0.0, 0.005)
        close.append(close[-1] * (1 + ret))
        volume.append(rng.lognormal(6, 0.5))

    dates = pd.date_range("2020-01-01", periods=n, freq="4h", tz="UTC")
    return pd.DataFrame(
        {
            "event_time": dates,
            "open": close,
            "high": [c * 1.001 for c in close],
            "low": [c * 0.999 for c in close],
            "close": close,
            "volume": volume,
        }
    )


class TestClassifyMacroHistory:
    def test_returns_evidence_object(self):
        frame = _make_synthetic_frame(500)
        evidence = classify_macro_history(frame, initial_train=200, refit_every=50)
        assert isinstance(evidence, MacroRegimeEvidence)
        assert isinstance(evidence.current, MacroState)
        assert evidence.current.label in (
            "trend_low_vol",
            "trend_high_vol",
            "range_low_vol",
            "range_high_vol",
            "liquidity_stress",
        )

    def test_labels_length_matches_expected(self):
        frame = _make_synthetic_frame(500)
        evidence = classify_macro_history(frame, initial_train=200, refit_every=50)
        assert len(evidence.labels) == 500 - 200

    def test_prefix_invariance(self):
        """Appending bars must not change existing labels."""
        frame = _make_synthetic_frame(500)
        evidence_full = classify_macro_history(frame, initial_train=200, refit_every=50)
        evidence_prefix = classify_macro_history(
            frame.iloc[:450], initial_train=200, refit_every=50
        )
        # Labels for the first 250 bars should be identical
        prefix_labels = evidence_prefix.labels.values
        full_labels = evidence_full.labels.values[: len(prefix_labels)]
        np.testing.assert_array_equal(prefix_labels, full_labels)

    def test_thresholds_fitted_causally(self):
        """Threshold history should show expanding window."""
        frame = _make_synthetic_frame(500)
        evidence = classify_macro_history(frame, initial_train=200, refit_every=50)
        assert len(evidence.threshold_history) >= 2
        # First threshold fit at initial_train
        assert evidence.threshold_history[0]["fit_through_idx"] == 200
        # Subsequent thresholds use expanding window
        assert evidence.threshold_history[1]["fit_through_idx"] == 250

    def test_final_partial_block_reports_only_strictly_prior_thresholds(self):
        frame = _make_synthetic_frame(475)
        evidence = classify_macro_history(frame, initial_train=200, refit_every=50)

        assert evidence.threshold_history[-1]["fit_through_idx"] == 450
        assert evidence.current.thresholds_fitted_through < evidence.current.decision_time
        assert all(
            decision.thresholds_fitted_through < decision.decision_time
            for decision in evidence.decisions
        )

    def test_transitions_detected(self):
        frame = _make_synthetic_frame(500)
        evidence = classify_macro_history(frame, initial_train=200, refit_every=50)
        # Transitions is a list of tuples
        assert isinstance(evidence.transitions, list)
        for t in evidence.transitions:
            assert len(t) == 3  # (time, from, to)

    def test_current_state_has_duration(self):
        frame = _make_synthetic_frame(500)
        evidence = classify_macro_history(frame, initial_train=200, refit_every=50)
        assert evidence.current.duration_bars >= 1

    def test_current_state_has_threshold_values(self):
        frame = _make_synthetic_frame(500)
        evidence = classify_macro_history(frame, initial_train=200, refit_every=50)
        assert "vol_48_q75" in evidence.current.threshold_values
        assert "trend_q60" in evidence.current.threshold_values
        assert "illiquidity_q95" in evidence.current.threshold_values

    def test_insufficient_data_raises(self):
        frame = _make_synthetic_frame(100)
        with pytest.raises(ValueError, match="insufficient data"):
            classify_macro_history(frame, initial_train=200, refit_every=50)


class TestSummarizeComparableEpisodes:
    def test_sufficient_evidence(self):
        labeled = pd.DataFrame({"label": ["trend_low_vol"] * 50})
        result = summarize_comparable_episodes(labeled, minimum_rows=30)
        assert result["trend_low_vol"].status == "sufficient_evidence"
        assert result["trend_low_vol"].sample_count == 50

    def test_insufficient_evidence(self):
        labeled = pd.DataFrame({"label": ["liquidity_stress"] * 10})
        result = summarize_comparable_episodes(labeled, minimum_rows=30)
        assert result["liquidity_stress"].status == "insufficient_evidence"
        assert result["liquidity_stress"].sample_count == 10

    def test_all_labels_present(self):
        labeled = pd.DataFrame({"label": ["trend_low_vol"] * 50})
        result = summarize_comparable_episodes(labeled, minimum_rows=30)
        from bian_quant.regimes.classifier import REGIME_LABELS

        for label in REGIME_LABELS:
            assert label in result


class TestWriteMacroEvidence:
    def test_writes_json_and_markdown(self, tmp_path):
        frame = _make_synthetic_frame(500)
        evidence = classify_macro_history(frame, initial_train=200, refit_every=50)
        json_path, md_path = write_macro_evidence(evidence, tmp_path / "evidence")
        assert json_path.exists()
        assert md_path.exists()
        assert json_path.suffix == ".json"
        assert md_path.suffix == ".md"

    def test_json_has_current_state(self, tmp_path):
        frame = _make_synthetic_frame(500)
        evidence = classify_macro_history(frame, initial_train=200, refit_every=50)
        json_path, _ = write_macro_evidence(evidence, tmp_path / "evidence")
        import json

        data = json.loads(json_path.read_text())
        assert "current" in data
        assert "label" in data["current"]
        assert "transitions" in data
        assert "state_summaries" in data
        assert "decisions" in data
        assert "threshold_history" in data

    def test_markdown_has_current_state(self, tmp_path):
        frame = _make_synthetic_frame(500)
        evidence = classify_macro_history(frame, initial_train=200, refit_every=50)
        _, md_path = write_macro_evidence(evidence, tmp_path / "evidence")
        content = md_path.read_text(encoding="utf-8")
        assert "Macro Regime Evidence" in content
        assert evidence.current.label in content
        assert "State Summaries" in content
        assert "Reason codes" in content
        assert "Threshold History" in content
        assert "Transitions" in content
        assert "Trailing illiquidity" in content

    def test_existing_evidence_cannot_be_rewritten(self, tmp_path):
        frame = _make_synthetic_frame(500)
        evidence = classify_macro_history(frame, initial_train=200, refit_every=50)
        artifact_dir = tmp_path / "evidence"
        json_path, md_path = write_macro_evidence(evidence, artifact_dir)
        original_json = json_path.read_bytes()
        original_markdown = md_path.read_bytes()

        with pytest.raises(FileExistsError, match="already exists"):
            write_macro_evidence(evidence, artifact_dir)
        assert json_path.read_bytes() == original_json
        assert md_path.read_bytes() == original_markdown
