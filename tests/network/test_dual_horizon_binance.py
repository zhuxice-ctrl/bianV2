"""Network smoke tests for fixed Binance source objects.

These tests download a small, fixed set of real Binance public archives
and verify checksums plus parser compatibility.  They never download the
full five-year/two-year matrix.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from bian_quant.data.acquisition import (
    DualHorizonAcquisition,
    SourceDataset,
    build_source_plan,
)
from bian_quant.data.adapters.binance_archive import download_verified
from bian_quant.data.canonicalize import (
    canonicalize_funding_zip,
    canonicalize_metrics_zip,
    canonicalize_ohlcv_zip,
)

CONFIG = Path("configs/experiments/dual_horizon_derivatives.yaml")


@pytest.mark.network
def test_fixed_binance_objects_verify_and_parse(tmp_path: Path) -> None:
    config = DualHorizonAcquisition.from_yaml(CONFIG)
    wanted = {
        ("ohlcv", "BTCUSDT", "4h", "2021-07"),
        ("funding", "ETHUSDT", "native", "2021-07"),
        ("metrics_oi", "BNBUSDT", "native", "2024-07-01"),
    }
    selected = [
        source
        for source in build_source_plan(config)
        if (
            source.dataset.value,
            source.asset,
            source.interval,
            source.raw_identity.source_period,
        )
        in wanted
    ]
    assert {
        (
            source.dataset.value,
            source.asset,
            source.interval,
            source.raw_identity.source_period,
        )
        for source in selected
    } == wanted

    for source in selected:
        result = download_verified(
            tmp_path / source.relative_path,
            url=source.url,
            identity=source.raw_identity,
            attempts=3,
        )
        if source.dataset == SourceDataset.OHLCV:
            frame = canonicalize_ohlcv_zip(
                result.path,
                asset=source.asset,
                interval=source.interval,
                ingested_at=datetime(2026, 7, 30, tzinfo=UTC),
            )
        elif source.dataset == SourceDataset.FUNDING:
            frame = canonicalize_funding_zip(
                result.path,
                asset=source.asset,
                ingested_at=datetime(2026, 7, 30, tzinfo=UTC),
            )
        else:
            frame = canonicalize_metrics_zip(
                result.path,
                ingested_at=datetime(2026, 7, 30, tzinfo=UTC),
                publication_delay=timedelta(minutes=5),
            )
        assert not frame.empty
        assert (frame["available_time"] >= frame["event_time"]).all()
