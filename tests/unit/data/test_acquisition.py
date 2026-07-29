from datetime import UTC, datetime
from pathlib import Path

import pytest

from bian_quant.data.acquisition import (
    DiskBudget,
    DualHorizonAcquisition,
    calendar_days,
    calendar_months,
    check_disk_budget,
)


def test_locked_windows_are_explicit_and_timezone_aware() -> None:
    config = DualHorizonAcquisition.from_yaml(
        Path("configs/experiments/dual_horizon_derivatives.yaml")
    )
    assert config.assets == ("BTCUSDT", "ETHUSDT", "BNBUSDT")
    assert config.macro_start == datetime(2021, 7, 1, tzinfo=UTC)
    assert config.micro_start == datetime(2024, 7, 1, tzinfo=UTC)
    assert config.as_of == datetime(2026, 7, 26, 19, 59, 59, 999000, tzinfo=UTC)
    assert config.oi_delay_minutes == (5, 10, 15)
    assert config.parent_snapshot_ids == ()
    assert config.factor_protocol.development_end_exclusive == datetime(
        2026, 1, 1, tzinfo=UTC
    )
    assert config.factor_protocol.holdout_start == datetime(
        2026, 1, 26, 20, tzinfo=UTC
    )


def test_calendar_months_do_not_include_partial_end_month() -> None:
    result = calendar_months(
        datetime(2026, 5, 1, tzinfo=UTC),
        datetime(2026, 7, 26, tzinfo=UTC),
    )
    assert result == ((2026, 5), (2026, 6))


def test_calendar_days_are_cutoff_bounded() -> None:
    result = calendar_days(
        datetime(2026, 7, 1, tzinfo=UTC),
        datetime(2026, 7, 3, 12, tzinfo=UTC),
    )
    assert [item.isoformat() for item in result] == [
        "2026-07-01T00:00:00+00:00",
        "2026-07-02T00:00:00+00:00",
        "2026-07-03T00:00:00+00:00",
    ]


def test_disk_budget_warns_below_ten_gb_and_blocks_below_five() -> None:
    budget = DiskBudget(warn_bytes=10 * 1024**3, block_bytes=5 * 1024**3)
    assert check_disk_budget(Path("var"), budget, free_bytes=11 * 1024**3).value == "ok"
    assert check_disk_budget(Path("var"), budget, free_bytes=8 * 1024**3).value == "warning"
    assert check_disk_budget(Path("var"), budget, free_bytes=4 * 1024**3).value == "blocked"


def test_naive_or_inverted_window_is_rejected() -> None:
    payload = DualHorizonAcquisition.from_yaml(
        Path("configs/experiments/dual_horizon_derivatives.yaml")
    ).model_dump()
    payload["macro_start"] = "2021-07-01T00:00:00"
    with pytest.raises(ValueError, match="timezone-aware"):
        DualHorizonAcquisition.model_validate(payload)
