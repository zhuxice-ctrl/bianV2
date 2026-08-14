"""Market-cycle confidence from daily popular-universe artifacts.

This module is intentionally narrow: it turns already published, point-in-time
popular-universe artifacts into a read-only market environment estimate.  It
does not produce symbol entries, exits, or exchange orders.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

import pandas as pd

from bian_quant.data.funding_alignment import (
    FundingAlignmentRecord,
    latest_alignment_through,
)

_MIN_FUNDING_COVERAGE_RATIO = 0.5
_MAX_FUNDING_CONTRIBUTION = 0.10


class MarketCycleLabel(StrEnum):
    BULL = "bull"
    NEUTRAL = "neutral"
    RISK_OFF = "risk_off"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


@dataclass(frozen=True)
class MarketCycleState:
    label: MarketCycleLabel
    confidence: float
    probabilities: dict[str, float]
    decision_time: datetime | None
    sample_count: int
    evidence: dict[str, float | int | str | None]
    evidence_sha256: str


def load_popular_universe_records(artifacts_dir: Path) -> pd.DataFrame:
    """Load daily popular-universe artifacts into one causal evidence frame."""
    rows: list[dict[str, Any]] = []
    if not artifacts_dir.is_dir():
        return pd.DataFrame()
    for path in sorted(artifacts_dir.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        selection_time = payload.get("selection_time")
        members = payload.get("members") or []
        if not selection_time or not isinstance(members, list):
            continue
        quote_volume = [
            float(m["median_quote_volume"])
            for m in members
            if isinstance(m, dict) and "median_quote_volume" in m
        ]
        oi_value = [
            float(m["median_oi_value"])
            for m in members
            if isinstance(m, dict) and "median_oi_value" in m
        ]
        rows.append(
            {
                "selection_time": pd.Timestamp(selection_time).to_pydatetime(),
                "member_count": len(members),
                "median_quote_volume": _median(quote_volume),
                "median_oi_value": _median(oi_value),
                "top3_share": _top_n_share(quote_volume, 3),
            }
        )
    if not rows:
        return pd.DataFrame()
    frame = pd.DataFrame(rows).sort_values("selection_time").reset_index(drop=True)
    return frame


def classify_market_cycle(
    records: pd.DataFrame,
    *,
    funding_alignment: tuple[FundingAlignmentRecord, ...] | None = None,
    min_observations: int = 30,
    lookback_days: int = 30,
) -> MarketCycleState:
    """Classify the latest causal market cycle from records through date t."""
    if records.empty or len(records) < min_observations:
        return _insufficient(len(records) if not records.empty else 0)

    work = records.copy().sort_values("selection_time").reset_index(drop=True)
    latest = work.iloc[-1]
    trailing = work.tail(min(lookback_days, len(work)))
    prior = work.iloc[: -len(trailing)]
    baseline = (
        prior.tail(lookback_days) if len(prior) >= lookback_days else work.head(lookback_days)
    )

    breadth = float(trailing["member_count"].mean() / 12.0)
    breadth = _clamp(breadth, 0.0, 1.0)
    volume_momentum = _relative_change(
        float(trailing["median_quote_volume"].median()),
        float(baseline["median_quote_volume"].median()),
    )
    oi_momentum = _relative_change(
        float(trailing["median_oi_value"].median()),
        float(baseline["median_oi_value"].median()),
    )
    concentration = float(trailing["top3_share"].median())

    volume_score = _sigmoid(volume_momentum * 3.0)
    oi_score = _sigmoid(oi_momentum * 3.0)
    breadth_score = breadth
    concentration_penalty = _clamp((concentration - 0.55) / 0.35, 0.0, 1.0)

    bull_score = (
        0.40 * breadth_score
        + 0.30 * volume_score
        + 0.25 * oi_score
        + 0.05 * (1.0 - concentration_penalty)
    )
    risk_score = (
        0.35 * (1.0 - breadth_score)
        + 0.30 * (1.0 - volume_score)
        + 0.25 * (1.0 - oi_score)
        + 0.10 * concentration_penalty
    )

    funding_contribution: float | None = None
    funding_source_sha: str | None = None
    latest_alignment: FundingAlignmentRecord | None = None
    if funding_alignment is not None:
        latest_alignment = latest_alignment_through(funding_alignment, latest["selection_time"])
        if (
            latest_alignment is not None
            and latest_alignment.coverage_ratio >= _MIN_FUNDING_COVERAGE_RATIO
        ):
            contribution = _clamp(
                (1.0 - 2.0 * latest_alignment.positive_rate_share) * _MAX_FUNDING_CONTRIBUTION,
                -_MAX_FUNDING_CONTRIBUTION,
                _MAX_FUNDING_CONTRIBUTION,
            )
            if not (contribution > 0.0 and risk_score > bull_score):
                funding_contribution = contribution
            else:
                funding_contribution = 0.0
            funding_source_sha = latest_alignment.source_sha256
    if funding_contribution is not None:
        bull_score = _clamp(bull_score + funding_contribution, 0.0, 1.0)
    neutral_score = max(0.05, 1.0 - abs(bull_score - risk_score))
    probabilities = _normalize(
        {
            MarketCycleLabel.BULL.value: bull_score,
            MarketCycleLabel.NEUTRAL.value: neutral_score,
            MarketCycleLabel.RISK_OFF.value: risk_score,
        }
    )
    label_value, confidence = max(probabilities.items(), key=lambda item: (item[1], item[0]))
    evidence: dict[str, float | int | str | None] = {
        "breadth": breadth,
        "volume_momentum": volume_momentum,
        "open_interest_momentum": oi_momentum,
        "top3_concentration": concentration,
        "lookback_days": int(len(trailing)),
        "latest_member_count": int(latest["member_count"]),
    }
    if latest_alignment is not None:
        evidence["funding_alignment"] = funding_contribution
        evidence["funding_alignment_source_sha256"] = funding_source_sha
    evidence_sha = _canonical_hash({"evidence": evidence, "probabilities": probabilities})
    return MarketCycleState(
        label=MarketCycleLabel(label_value),
        confidence=round(float(confidence), 6),
        probabilities={k: round(v, 6) for k, v in probabilities.items()},
        decision_time=latest["selection_time"],
        sample_count=len(work),
        evidence=evidence,
        evidence_sha256=evidence_sha,
    )


def market_cycle_payload(state: MarketCycleState) -> dict[str, object]:
    return {
        "label": state.label.value,
        "confidence": state.confidence,
        "probabilities": state.probabilities,
        "decision_time": state.decision_time.isoformat() if state.decision_time else None,
        "sample_count": state.sample_count,
        "evidence": state.evidence,
        "evidence_sha256": state.evidence_sha256,
    }


def _insufficient(sample_count: int) -> MarketCycleState:
    payload: dict[str, float | int | str | None] = {
        "sample_count": sample_count,
        "reason": "MINIMUM_30_DAILY_OBSERVATIONS",
    }
    return MarketCycleState(
        label=MarketCycleLabel.INSUFFICIENT_EVIDENCE,
        confidence=0.0,
        probabilities={
            MarketCycleLabel.BULL.value: 0.0,
            MarketCycleLabel.NEUTRAL.value: 0.0,
            MarketCycleLabel.RISK_OFF.value: 0.0,
        },
        decision_time=None,
        sample_count=sample_count,
        evidence=payload,
        evidence_sha256=_canonical_hash(payload),
    )


def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    return float(pd.Series(values, dtype=float).median())


def _top_n_share(values: list[float], n: int) -> float:
    total = sum(v for v in values if v > 0)
    if total <= 0:
        return 0.0
    return sum(sorted((v for v in values if v > 0), reverse=True)[:n]) / total


def _relative_change(current: float, previous: float) -> float:
    if not math.isfinite(current) or not math.isfinite(previous) or previous <= 0:
        return 0.0
    return (current - previous) / previous


def _sigmoid(value: float) -> float:
    value = _clamp(value, -20.0, 20.0)
    return 1.0 / (1.0 + math.exp(-value))


def _normalize(scores: dict[str, float]) -> dict[str, float]:
    total = sum(max(0.0, v) for v in scores.values())
    if total <= 0:
        return {k: 0.0 for k in scores}
    return {k: max(0.0, v) / total for k, v in scores.items()}


def _clamp(value: float, lower: float, upper: float) -> float:
    return min(upper, max(lower, value))


def _canonical_hash(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()
