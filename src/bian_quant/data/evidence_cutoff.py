"""Cutoff projection, cutoff evidence, and plan-namespaced canonical paths."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pandas as pd
from pydantic import BaseModel, ConfigDict

from bian_quant.data.acquisition import SourceObject


class CutoffEvidence(BaseModel):
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    identity_key: str
    dataset: str
    eligible_rows: int
    post_cutoff_rows_excluded: int
    earliest_excluded_event_time: datetime | None
    latest_excluded_event_time: datetime | None
    earliest_excluded_available_time: datetime | None
    latest_excluded_available_time: datetime | None


@dataclass(frozen=True)
class CutoffSlice:
    eligible: pd.DataFrame
    evidence: CutoffEvidence


def _optional_time(frame: pd.DataFrame, column: str, operation: str) -> datetime | None:
    if frame.empty:
        return None
    values = pd.to_datetime(frame[column], utc=True)
    value = values.min() if operation == "min" else values.max()
    return pd.Timestamp(value).to_pydatetime()


def clip_to_evidence_cutoff(
    source: SourceObject,
    frame: pd.DataFrame,
    *,
    as_of: datetime,
) -> CutoffSlice:
    event_time = pd.to_datetime(frame["event_time"], utc=True)
    available_time = pd.to_datetime(frame["available_time"], utc=True)
    eligible_mask = (event_time <= as_of) & (available_time <= as_of)
    eligible = frame.loc[eligible_mask].copy().reset_index(drop=True)
    excluded = frame.loc[~eligible_mask].copy().reset_index(drop=True)
    evidence = CutoffEvidence(
        identity_key=source.identity_key,
        dataset=source.dataset.value,
        eligible_rows=len(eligible),
        post_cutoff_rows_excluded=len(excluded),
        earliest_excluded_event_time=_optional_time(excluded, "event_time", "min"),
        latest_excluded_event_time=_optional_time(excluded, "event_time", "max"),
        earliest_excluded_available_time=_optional_time(excluded, "available_time", "min"),
        latest_excluded_available_time=_optional_time(excluded, "available_time", "max"),
    )
    return CutoffSlice(eligible=eligible, evidence=evidence)


def canonical_plan_path(
    root: Path,
    *,
    plan_hash: str,
    relative_path: Path,
) -> Path:
    return root / f"plan={plan_hash[:16]}" / relative_path.with_suffix(".parquet")


def canonical_snapshot_id(
    source: SourceObject,
    *,
    content_sha: str,
    plan_hash: str,
) -> str:
    identity = hashlib.sha256(f"{source.identity_key}|{plan_hash}".encode()).hexdigest()[:12]
    return f"canonical-{source.dataset.value}-{content_sha[:16]}-{identity}"
