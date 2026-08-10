"""Local real-raw regression for popular universe availability."""

from __future__ import annotations

from pathlib import Path

import pytest

from bian_quant.data.acquisition import SourceDataset, SourceGranularity
from bian_quant.data.archive_availability import bootstrap_archive_availability

RAW_ROOT = Path("var/lake/raw/binance-futures-um-popular-v1")

POPULAR_ASSETS = (
    "ADAUSDT",
    "APTUSDT",
    "AVAXUSDT",
    "BCHUSDT",
    "BNBUSDT",
    "BTCUSDT",
    "DOGEUSDT",
    "ETHUSDT",
    "LINKUSDT",
    "LTCUSDT",
    "NEARUSDT",
    "SOLUSDT",
    "SUIUSDT",
    "TONUSDT",
    "TRXUSDT",
    "XRPUSDT",
)

REQUIRED_KEYS: set[tuple[str, SourceDataset, SourceGranularity]] = set()
for _asset in POPULAR_ASSETS:
    REQUIRED_KEYS.add((_asset, SourceDataset.OHLCV, SourceGranularity.MONTHLY))
    REQUIRED_KEYS.add((_asset, SourceDataset.OHLCV, SourceGranularity.DAILY))
    REQUIRED_KEYS.add((_asset, SourceDataset.FUNDING, SourceGranularity.MONTHLY))
    REQUIRED_KEYS.add((_asset, SourceDataset.METRICS_OI, SourceGranularity.DAILY))


@pytest.mark.skipif(not RAW_ROOT.exists(), reason="popular raw archive not available locally")
def test_bootstrap_has_all_required_keys() -> None:
    manifest = bootstrap_archive_availability(RAW_ROOT, assets=POPULAR_ASSETS)
    assert {
        (entry.asset, entry.dataset, entry.granularity) for entry in manifest.entries
    } == REQUIRED_KEYS
