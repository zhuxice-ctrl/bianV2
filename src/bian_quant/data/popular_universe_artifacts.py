"""Popular-universe artifact builder extracted for reuse by local snapshot recovery."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pandas as pd

from bian_quant.data.acquisition import DualHorizonAcquisition
from bian_quant.data.popular_universe import (
    _selector_config_hash,
    build_popular_universe,
)


def _derive_listing_metadata(ohlcv: pd.DataFrame) -> pd.DataFrame:
    """Derive listing metadata from the earliest OHLCV event per asset."""
    rows = []
    for asset, group in ohlcv.groupby("asset", sort=True):
        first = group.sort_values("event_time").iloc[0]
        rows.append(
            {
                "asset": asset,
                "listing_time": first["event_time"],
                "listing_available_time": first["available_time"],
            }
        )
    return pd.DataFrame(rows)


@dataclass(frozen=True)
class PopularUniverseBuildResult:
    artifacts: list[dict[str, object]]
    shortages: list[dict[str, str]]
    start: datetime
    warmup_start: datetime
    warmup_end: datetime | None


def has_funding_days_shortage(artifact: dict[str, object], partial_assets: list[str]) -> bool:
    """Whether a popular-universe artifact excludes a partially available asset."""
    exclusions = artifact.get("exclusions")
    if not isinstance(exclusions, list):
        return False
    return any(
        isinstance(row, dict)
        and str(row.get("asset")) in partial_assets
        and str(row.get("reason")) == "FUNDING_DAYS_INSUFFICIENT"
        for row in exclusions
    )


def _load_popular_artifact_checkpoint(
    path: Path, selection_time: datetime, selector_config_hash: str
) -> dict[str, object] | None:
    """Load a completed daily artifact only when its selector config matches."""
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    if payload.get("selection_time") != selection_time.isoformat():
        return None
    if payload.get("selector_config_hash") != selector_config_hash:
        return None
    required = {"artifact_id", "members", "exclusions", "source_hashes"}
    if not required.issubset(payload):
        return None
    return {
        "artifact_id": payload["artifact_id"],
        "selection_time": payload["selection_time"],
        "selector_config_hash": payload["selector_config_hash"],
        "member_assets": [
            str(member["asset"])
            for member in payload["members"]
            if isinstance(member, dict) and "asset" in member
        ],
        "exclusions": payload["exclusions"],
    }


def build_popular_universe_artifacts(
    config: DualHorizonAcquisition,
    ohlcv: pd.DataFrame,
    funding: pd.DataFrame,
    metrics: pd.DataFrame,
) -> PopularUniverseBuildResult:
    """Build one popular-universe artifact per UTC daily boundary.

    Returns a PopularUniverseBuildResult with artifacts and any daily
    shortages (below min_selected) as hard blockers.
    """
    policy = config.universe_policy
    assert policy is not None

    listing = _derive_listing_metadata(ohlcv)

    # Include every configured daily selector boundary, beginning at the
    # publishable popular-universe start.  Earlier micro rows remain available
    # as rolling-window warmup evidence.
    start = pd.Timestamp(config.popular_universe_start or config.micro_start).tz_convert("UTC")
    end = pd.Timestamp(config.as_of).tz_convert("UTC")
    selector_config_hash = _selector_config_hash(policy)

    artifacts_dir = config.artifact_root / "popular-universe"
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    results: list[dict[str, object]] = []
    shortages: list[dict[str, str]] = []
    current = start
    processed = 0
    while current <= end:
        selection_time = current.to_pydatetime()
        artifact_path = artifacts_dir / f"{selection_time:%Y-%m-%dT%H-%M-%S}.json"
        checkpoint = _load_popular_artifact_checkpoint(
            artifact_path, selection_time, selector_config_hash
        )
        if checkpoint is not None:
            results.append(checkpoint)
            processed += 1
            if processed == 1 or processed % 25 == 0:
                print(
                    f"[popular-universe] resumed {processed} daily artifacts "
                    f"through {selection_time:%Y-%m-%d}",
                    flush=True,
                )
            current = current + pd.Timedelta(days=1)
            continue
        try:
            artifact = build_popular_universe(
                selection_time=selection_time,
                listing_metadata=listing,
                ohlcv=ohlcv,
                funding=funding,
                metrics=metrics,
                policy=policy,
            )
        except RuntimeError as exc:
            if str(exc).startswith("POPULAR_UNIVERSE_INSUFFICIENT:"):
                shortages.append(
                    {
                        "identity_key": f"popular-universe|{selection_time:%Y-%m-%d}",
                        "message": str(exc),
                    }
                )
                current = current + pd.Timedelta(days=1)
                continue
            raise

        payload = {
            "artifact_id": artifact.artifact_id,
            "selection_time": selection_time.isoformat(),
            "selector_config_hash": artifact.selector_config_hash,
            "members": [
                {
                    "asset": m.asset,
                    "rank": m.rank,
                    "median_quote_volume": m.median_quote_volume,
                    "median_oi_value": m.median_oi_value,
                }
                for m in artifact.members
            ],
            "exclusions": [{"asset": e.asset, "reason": e.reason} for e in artifact.exclusions],
            "source_hashes": artifact.source_hashes,
        }
        temporary_path = artifact_path.with_suffix(".json.tmp")
        with temporary_path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True, default=str)
        temporary_path.replace(artifact_path)

        results.append(
            {
                "artifact_id": artifact.artifact_id,
                "selection_time": selection_time.isoformat(),
                "selector_config_hash": artifact.selector_config_hash,
                "member_assets": list(artifact.member_assets),
                "exclusions": [{"asset": e.asset, "reason": e.reason} for e in artifact.exclusions],
            }
        )
        processed += 1
        if processed == 1 or processed % 25 == 0:
            print(
                f"[popular-universe] computed {processed} daily artifacts "
                f"through {selection_time:%Y-%m-%d}",
                flush=True,
            )
        current = current + pd.Timedelta(days=1)

    warmup_start = pd.Timestamp(config.micro_start).tz_convert("UTC").to_pydatetime()
    warmup_end = None
    if start.to_pydatetime() > warmup_start:
        warmup_end = (start - pd.Timedelta(days=1)).to_pydatetime()
    return PopularUniverseBuildResult(
        artifacts=results,
        shortages=shortages,
        start=start.to_pydatetime(),
        warmup_start=warmup_start,
        warmup_end=warmup_end,
    )
