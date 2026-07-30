"""Content-addressed snapshot publishing for Macro and Micro research views.

Snapshot IDs are deterministic:
    snapshot_id = f"{spec.name}-{content_sha256[:16]}-{config_sha256[:12]}"

All outputs are registered through DatasetCatalog.  Existing ID reuse with
different path or lineage is rejected.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

from bian_quant.data.catalog import DatasetCatalog
from bian_quant.data.contracts import DatasetLayer, DatasetManifest
from bian_quant.data.hashing import dataframe_content_hash


@dataclass(frozen=True)
class SnapshotSpec:
    """Immutable specification for a research snapshot."""

    name: str
    layer: DatasetLayer
    interval: str
    horizon: str  # "macro" or "micro"
    parent_snapshot_ids: tuple[str, ...] = ()
    config_json: str = "{}"


def _compute_config_sha256(spec: SnapshotSpec) -> str:
    payload = json.dumps(
        {
            "name": spec.name,
            "layer": spec.layer.value,
            "interval": spec.interval,
            "horizon": spec.horizon,
            "parent_snapshot_ids": list(spec.parent_snapshot_ids),
            "config_json": spec.config_json,
        },
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def publish_snapshot(
    frame: pd.DataFrame,
    spec: SnapshotSpec,
    root: Path,
    catalog: DatasetCatalog,
) -> DatasetManifest:
    """Publish a content-addressed snapshot and register it in the catalog.

    The frame is written as Zstd Parquet.  The snapshot ID is deterministic
    from content and config.  Re-publishing the same content is idempotent.
    """
    stable_frame = frame.drop(columns=["ingested_at"], errors="ignore")
    content_sha = dataframe_content_hash(stable_frame, sort_by=["asset", "event_time"])
    config_sha = _compute_config_sha256(spec)
    snapshot_id = f"{spec.name}-{content_sha[:16]}-{config_sha[:12]}"

    min_event = frame["event_time"].min() if not frame.empty else None
    max_event = frame["event_time"].max() if not frame.empty else None
    min_avail = frame["available_time"].min() if not frame.empty else None
    max_avail = frame["available_time"].max() if not frame.empty else None

    manifest = DatasetManifest(
        snapshot_id=snapshot_id,
        layer=spec.layer,
        name=spec.name,
        content_sha256=content_sha,
        row_count=len(frame),
        min_event_time=min_event if isinstance(min_event, datetime) else None,
        max_event_time=max_event if isinstance(max_event, datetime) else None,
        parent_snapshot_ids=list(spec.parent_snapshot_ids),
        config_json=spec.config_json,
        min_available_time=min_avail if isinstance(min_avail, datetime) else None,
        max_available_time=max_avail if isinstance(max_avail, datetime) else None,
    )

    output_path = root / f"{snapshot_id}.parquet"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists():
        existing = pd.read_parquet(output_path)
        existing_stable = existing.drop(columns=["ingested_at"], errors="ignore")
        existing_hash = dataframe_content_hash(existing_stable, sort_by=["asset", "event_time"])
        if existing_hash != content_sha:
            raise ValueError("SNAPSHOT_CONTENT_CONFLICT: existing snapshot content differs")
    else:
        frame.to_parquet(output_path, engine="pyarrow", compression="zstd", index=False)

    catalog.register(manifest, path=output_path)
    return manifest


def build_macro_snapshots(
    ohlcv: pd.DataFrame,
    funding: pd.DataFrame | None,
    *,
    intervals: tuple[str, ...],
    root: Path,
    catalog: DatasetCatalog,
    parent_snapshot_ids: tuple[str, ...] = (),
    config_json: str = "{}",
) -> tuple[DatasetManifest, ...]:
    """Build Macro research snapshots (1d, 4h) from OHLCV and Funding."""
    results: list[DatasetManifest] = []
    for interval in intervals:
        bars = ohlcv.loc[ohlcv["interval"] == interval].copy()
        if bars.empty:
            raise ValueError(f"SNAPSHOT_INPUT_MISSING: no OHLCV rows for macro {interval}")
        resampled = _join_derivatives(bars, funding=funding, metrics=None)
        spec = SnapshotSpec(
            name=f"macro-{interval}",
            layer=DatasetLayer.RESEARCH,
            interval=interval,
            horizon="macro",
            parent_snapshot_ids=parent_snapshot_ids,
            config_json=config_json,
        )
        results.append(publish_snapshot(resampled, spec, root, catalog))
    return tuple(results)


def build_micro_snapshots(
    ohlcv: pd.DataFrame,
    funding: pd.DataFrame | None,
    metrics: pd.DataFrame | None,
    *,
    intervals: tuple[str, ...],
    root: Path,
    catalog: DatasetCatalog,
    parent_snapshot_ids: tuple[str, ...] = (),
    config_json: str = "{}",
) -> tuple[DatasetManifest, ...]:
    """Build Micro research snapshots (1h, 4h) from OHLCV, Funding, and OI."""
    results: list[DatasetManifest] = []
    for interval in intervals:
        bars = ohlcv.loc[ohlcv["interval"] == interval].copy()
        if bars.empty:
            raise ValueError(f"SNAPSHOT_INPUT_MISSING: no OHLCV rows for micro {interval}")
        resampled = _join_derivatives(bars, funding=funding, metrics=metrics)
        spec = SnapshotSpec(
            name=f"micro-{interval}",
            layer=DatasetLayer.RESEARCH,
            interval=interval,
            horizon="micro",
            parent_snapshot_ids=parent_snapshot_ids,
            config_json=config_json,
        )
        results.append(publish_snapshot(resampled, spec, root, catalog))
    return tuple(results)


def _join_derivatives(
    bars: pd.DataFrame,
    *,
    funding: pd.DataFrame | None,
    metrics: pd.DataFrame | None,
) -> pd.DataFrame:
    """Join only information available by each bar decision, isolated by asset."""
    results: list[pd.DataFrame] = []
    for asset, asset_bars in bars.groupby("asset", sort=True):
        joined = asset_bars.sort_values("available_time").copy()
        if funding is not None:
            asset_funding = funding.loc[funding["asset"] == asset].sort_values("available_time")
            if not asset_funding.empty:
                funding_columns = [
                    "available_time",
                    "funding_rate",
                    "funding_interval_hours",
                ]
                joined = pd.merge_asof(
                    joined,
                    asset_funding[funding_columns].rename(
                        columns={"available_time": "funding_available_time"}
                    ),
                    left_on="available_time",
                    right_on="funding_available_time",
                    direction="backward",
                    allow_exact_matches=True,
                )
        if metrics is not None:
            asset_metrics = metrics.loc[metrics["asset"] == asset].sort_values("available_time")
            if not asset_metrics.empty:
                metric_columns = [
                    "available_time",
                    "sum_open_interest",
                    "sum_open_interest_value",
                    "availability_assumption",
                ]
                joined = pd.merge_asof(
                    joined,
                    asset_metrics[metric_columns].rename(
                        columns={"available_time": "oi_available_time"}
                    ),
                    left_on="available_time",
                    right_on="oi_available_time",
                    direction="backward",
                    allow_exact_matches=True,
                )
        results.append(joined)
    return pd.concat(results, ignore_index=True).sort_values(["asset", "event_time"])


def build_delay_views(
    metrics: pd.DataFrame,
    *,
    delays: tuple[int, ...],
    root: Path,
    parent_snapshot_ids: tuple[str, ...],
) -> dict[int, str]:
    """Build separate delay-scenario views for OI publication delay.

    Each delay creates a distinct snapshot with its own available_time.
    Returns a mapping from delay minutes to snapshot ID.
    """
    catalog = DatasetCatalog(root / "delay_catalog.sqlite")
    result: dict[int, str] = {}
    for delay_minutes in delays:
        delayed = metrics.copy()
        delay_td = timedelta(minutes=delay_minutes)
        delayed["available_time"] = delayed["event_time"] + delay_td
        delayed["availability_assumption"] = f"BINANCE_METRICS_DELAY_{delay_minutes}M"

        spec = SnapshotSpec(
            name=f"metrics-oi-delay-{delay_minutes}m",
            layer=DatasetLayer.RESEARCH,
            interval="1h",
            horizon="micro",
            parent_snapshot_ids=parent_snapshot_ids,
            config_json=json.dumps({"delay_minutes": delay_minutes}),
        )
        manifest = publish_snapshot(delayed, spec, root, catalog)
        result[delay_minutes] = manifest.snapshot_id

    return result
