"""Unit tests for popular-universe membership lineage filtering."""

from __future__ import annotations

from datetime import timedelta

import pandas as pd
import pytest

from bian_quant.research.dual_horizon import _apply_membership_lineage


def _eligibility_row(asset: str, day: str, rank: int = 1) -> dict:
    return {
        "asset": asset,
        "selection_time": pd.Timestamp(day, tz="UTC"),
        "rank": rank,
    }


def _bar(asset: str, available: str) -> dict:
    return {
        "asset": asset,
        "available_time": pd.Timestamp(available, tz="UTC"),
        "event_time": pd.Timestamp(available, tz="UTC") - timedelta(hours=4),
        "close": 50000.0,
        "volume": 100.0,
        "open": 49900.0,
        "high": 50100.0,
        "low": 49800.0,
    }


class TestApplyMembershipLineage:
    """Tests for _apply_membership_lineage filtering logic."""

    def test_keeps_bars_with_matching_membership(self) -> None:
        development = pd.DataFrame(
            [
                _bar("BTCUSDT", "2026-07-01T04:00:00"),
                _bar("ETHUSDT", "2026-07-01T04:00:00"),
            ]
        )
        eligibility = pd.DataFrame(
            [
                _eligibility_row("BTCUSDT", "2026-07-01T00:00:00", rank=1),
                _eligibility_row("ETHUSDT", "2026-07-01T00:00:00", rank=2),
            ]
        )
        result = _apply_membership_lineage(development, eligibility)
        assert len(result) == 2
        assert set(result["asset"]) == {"BTCUSDT", "ETHUSDT"}

    def test_drops_bars_without_membership(self) -> None:
        development = pd.DataFrame(
            [
                _bar("BTCUSDT", "2026-07-01T04:00:00"),
                _bar("ADAUSDT", "2026-07-01T04:00:00"),
            ]
        )
        eligibility = pd.DataFrame(
            [
                _eligibility_row("BTCUSDT", "2026-07-01T00:00:00"),
            ]
        )
        result = _apply_membership_lineage(development, eligibility)
        assert len(result) == 1
        assert result["asset"].iloc[0] == "BTCUSDT"

    def test_drops_bars_where_selection_time_exceeds_available_time(self) -> None:
        development = pd.DataFrame(
            [
                _bar("BTCUSDT", "2026-07-01T04:00:00"),
            ]
        )
        # selection_time is AFTER the bar's available_time — should be dropped
        eligibility = pd.DataFrame(
            [
                _eligibility_row("BTCUSDT", "2026-07-01T08:00:00"),
            ]
        )
        result = _apply_membership_lineage(development, eligibility)
        assert result.empty

    def test_selection_time_equal_to_available_time_is_kept(self) -> None:
        development = pd.DataFrame(
            [
                _bar("BTCUSDT", "2026-07-01T00:00:00"),
            ]
        )
        eligibility = pd.DataFrame(
            [
                _eligibility_row("BTCUSDT", "2026-07-01T00:00:00"),
            ]
        )
        result = _apply_membership_lineage(development, eligibility)
        assert len(result) == 1

    def test_duplicate_membership_raises(self) -> None:
        development = pd.DataFrame(
            [
                _bar("BTCUSDT", "2026-07-01T04:00:00"),
            ]
        )
        eligibility = pd.DataFrame(
            [
                _eligibility_row("BTCUSDT", "2026-07-01T00:00:00"),
                _eligibility_row("BTCUSDT", "2026-07-01T00:00:00"),
            ]
        )
        with pytest.raises(RuntimeError, match="DUPLICATE_MEMBERSHIP"):
            _apply_membership_lineage(development, eligibility)

    def test_multiple_days_filter_correctly(self) -> None:
        development = pd.DataFrame(
            [
                _bar("BTCUSDT", "2026-07-01T04:00:00"),
                _bar("BTCUSDT", "2026-07-02T04:00:00"),
                _bar("BTCUSDT", "2026-07-03T04:00:00"),
            ]
        )
        eligibility = pd.DataFrame(
            [
                _eligibility_row("BTCUSDT", "2026-07-01T00:00:00"),
                _eligibility_row("BTCUSDT", "2026-07-03T00:00:00"),
            ]
        )
        result = _apply_membership_lineage(development, eligibility)
        assert len(result) == 2
        days = set(result["available_time"].dt.tz_convert("UTC").dt.date)
        assert days == {pd.Timestamp("2026-07-01").date(), pd.Timestamp("2026-07-03").date()}

    def test_missing_eligibility_columns_raises(self) -> None:
        development = pd.DataFrame([_bar("BTCUSDT", "2026-07-01T04:00:00")])
        eligibility = pd.DataFrame(
            [{"asset": "BTCUSDT", "selection_time": pd.Timestamp("2026-07-01", tz="UTC")}]
        )
        with pytest.raises(ValueError, match="missing columns"):
            _apply_membership_lineage(development, eligibility)

    def test_empty_development_returns_empty(self) -> None:
        development = pd.DataFrame(
            columns=["asset", "available_time", "event_time", "close", "volume"]
        )
        eligibility = pd.DataFrame([_eligibility_row("BTCUSDT", "2026-07-01T00:00:00")])
        result = _apply_membership_lineage(development, eligibility)
        assert result.empty

    def test_preserves_all_columns(self) -> None:
        development = pd.DataFrame(
            [
                _bar("BTCUSDT", "2026-07-01T04:00:00"),
            ]
        )
        eligibility = pd.DataFrame(
            [
                _eligibility_row("BTCUSDT", "2026-07-01T00:00:00"),
            ]
        )
        result = _apply_membership_lineage(development, eligibility)
        assert "close" in result.columns
        assert "volume" in result.columns
        assert "open" in result.columns
        # Should not have internal columns leaked
        assert "_bar_day" not in result.columns
        assert "_membership_day" not in result.columns
