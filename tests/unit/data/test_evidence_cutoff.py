from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from bian_quant.data.acquisition import (
    SourceDataset,
    SourceGranularity,
    SourceObject,
)
from bian_quant.data.evidence_cutoff import (
    canonical_plan_path,
    canonical_snapshot_id,
    clip_to_evidence_cutoff,
)
from bian_quant.data.hashing import dataframe_content_hash

AS_OF = datetime(2026, 7, 26, 19, 59, 59, 999000, tzinfo=UTC)


def _funding_source() -> SourceObject:
    return SourceObject(
        dataset=SourceDataset.FUNDING,
        asset="BTCUSDT",
        interval="native",
        granularity=SourceGranularity.MONTHLY,
        period_start=datetime(2026, 7, 1, tzinfo=UTC),
        url="https://example.test/BTCUSDT-fundingRate-2026-07.zip",
        relative_path=Path("funding/BTCUSDT/native/2026-07.zip"),
    )


def test_cutoff_requires_event_and_availability() -> None:
    frame = pd.DataFrame(
        {
            "asset": ["BTCUSDT"] * 3,
            "event_time": pd.to_datetime(
                [
                    "2026-07-26T16:00:00Z",
                    "2026-07-26T19:00:00Z",
                    "2026-07-27T00:00:00Z",
                ],
                utc=True,
            ),
            "available_time": pd.to_datetime(
                [
                    "2026-07-26T16:00:00Z",
                    "2026-07-26T20:00:00Z",
                    "2026-07-27T00:00:00Z",
                ],
                utc=True,
            ),
            "funding_rate": [0.1, 0.2, 0.3],
        }
    )
    result = clip_to_evidence_cutoff(_funding_source(), frame, as_of=AS_OF)
    assert list(result.eligible["funding_rate"]) == [0.1]
    assert result.evidence.eligible_rows == 1
    assert result.evidence.post_cutoff_rows_excluded == 2
    assert result.evidence.earliest_excluded_event_time == pd.Timestamp("2026-07-26T19:00:00Z")
    assert result.evidence.latest_excluded_available_time == pd.Timestamp("2026-07-27T00:00:00Z")


def test_post_cutoff_append_cannot_change_eligible_hash() -> None:
    base = pd.DataFrame(
        {
            "asset": ["BTCUSDT"],
            "event_time": pd.to_datetime(["2026-07-26T16:00:00Z"], utc=True),
            "available_time": pd.to_datetime(["2026-07-26T16:00:00Z"], utc=True),
            "funding_rate": [0.1],
        }
    )
    tail = pd.DataFrame(
        {
            "asset": ["BTCUSDT"],
            "event_time": pd.to_datetime(["2026-07-27T00:00:00Z"], utc=True),
            "available_time": pd.to_datetime(["2026-07-27T00:00:00Z"], utc=True),
            "funding_rate": [0.9],
        }
    )
    first = clip_to_evidence_cutoff(_funding_source(), base, as_of=AS_OF)
    second = clip_to_evidence_cutoff(
        _funding_source(), pd.concat([base, tail], ignore_index=True), as_of=AS_OF
    )
    assert dataframe_content_hash(
        first.eligible, sort_by=["asset", "event_time"]
    ) == dataframe_content_hash(second.eligible, sort_by=["asset", "event_time"])


def test_canonical_path_is_plan_namespaced() -> None:
    path = canonical_plan_path(
        Path("var/lake/canonical/binance-futures-um"),
        plan_hash="a" * 64,
        relative_path=Path("funding/BTCUSDT/native/2026-07.zip"),
    )
    assert path.as_posix().endswith("plan=aaaaaaaaaaaaaaaa/funding/BTCUSDT/native/2026-07.parquet")


def test_canonical_id_is_plan_namespaced() -> None:
    first = canonical_snapshot_id(_funding_source(), content_sha="b" * 64, plan_hash="a" * 64)
    second = canonical_snapshot_id(_funding_source(), content_sha="b" * 64, plan_hash="c" * 64)
    assert first.startswith("canonical-funding-bbbbbbbbbbbbbbbb-")
    assert first != second
