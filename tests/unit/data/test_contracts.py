from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from bian_quant.data.contracts import (
    DatasetLayer,
    DatasetManifest,
    MarketRecord,
    QualitySeverity,
)


def test_market_record_requires_available_time_after_event_time() -> None:
    with pytest.raises(ValidationError):
        MarketRecord(
            asset="BTCUSDT",
            event_time=datetime(2026, 1, 1, 1, tzinfo=UTC),
            available_time=datetime(2026, 1, 1, 0, tzinfo=UTC),
            ingested_at=datetime(2026, 1, 2, tzinfo=UTC),
            source="legacy_csv",
        )


def test_contract_enums_are_stable() -> None:
    assert DatasetLayer.RAW.value == "raw"
    assert QualitySeverity.BLOCKING.value == "blocking"


def test_manifest_rejects_naive_evidence_range() -> None:
    with pytest.raises(ValidationError, match="timezone-aware"):
        DatasetManifest(
            snapshot_id="snapshot-1",
            layer=DatasetLayer.CANONICAL,
            name="ohlcv",
            content_sha256="a" * 64,
            row_count=1,
            min_event_time=datetime(2026, 1, 1),
            max_event_time=datetime(2026, 1, 1, tzinfo=UTC),
            parent_snapshot_ids=[],
            config_json="{}",
        )
