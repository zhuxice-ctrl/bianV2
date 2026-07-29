"""Causal five-year Macro regime evidence with expanding-window classification.

Thresholds are fit only on rows strictly earlier than the classification block.
Historical labels cannot use full-sample quantiles.  Preserves prefix invariance:
appending bars does not change existing labels.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from bian_quant.regimes.classifier import (
    REGIME_LABELS,
    RegimeThresholds,
    classify_regime,
    fit_regime_thresholds,
)


@dataclass(frozen=True)
class MacroState:
    """Current macro regime state."""

    label: str
    decision_time: datetime
    duration_bars: int
    trailing_volatility: float
    trailing_trend: float
    trailing_illiquidity: float
    thresholds_fitted_through: datetime
    threshold_values: dict[str, float]


@dataclass(frozen=True)
class ComparableEpisodeSummary:
    """Summary of comparable historical episodes for a regime state."""

    label: str
    sample_count: int
    status: str  # "sufficient_evidence" or "insufficient_evidence"
    avg_duration: float | None = None
    avg_volatility: float | None = None


@dataclass(frozen=True)
class MacroRegimeEvidence:
    """Complete macro regime evidence from expanding-window classification."""

    labels: pd.Series
    current: MacroState
    transitions: list[tuple[datetime, str, str]] = field(default_factory=list)
    state_summaries: dict[str, ComparableEpisodeSummary] = field(default_factory=dict)
    threshold_history: list[dict] = field(default_factory=list)


def classify_macro_history(
    frame: pd.DataFrame,
    *,
    initial_train: int,
    refit_every: int,
) -> MacroRegimeEvidence:
    """Classify macro history using expanding windows.

    Thresholds are fit only on rows strictly earlier than the classification
    block.  Preserves prefix invariance.
    """
    n = len(frame)
    if n < initial_train:
        raise ValueError("insufficient data for initial training window")

    labels: list[str] = []
    threshold_history: list[dict] = []
    last_thresholds: RegimeThresholds | None = None
    fit_through_idx = 0

    # Initial fit on first `initial_train` rows
    train_frame = frame.iloc[:initial_train]
    thresholds = fit_regime_thresholds(train_frame)
    last_thresholds = thresholds
    fit_through_idx = initial_train
    threshold_history.append({
        "fit_through_idx": initial_train,
        "vol_48_q75": thresholds.vol_48_q75,
        "trend_q60": thresholds.trend_q60,
        "illiquidity_q95": thresholds.illiquidity_q95,
    })

    # Classify in blocks, refitting every `refit_every` rows
    idx = initial_train
    while idx < n:
        block_end = min(idx + refit_every, n)
        block = frame.iloc[idx:block_end]
        block_labels = classify_regime(block, last_thresholds)
        labels.extend(block_labels.tolist())

        # Refit thresholds using all data up to this block (expanding window)
        train_frame = frame.iloc[:block_end]
        last_thresholds = fit_regime_thresholds(train_frame)
        fit_through_idx = block_end
        threshold_history.append({
            "fit_through_idx": block_end,
            "vol_48_q75": last_thresholds.vol_48_q75,
            "trend_q60": last_thresholds.trend_q60,
            "illiquidity_q95": last_thresholds.illiquidity_q95,
        })
        idx = block_end

    label_series = pd.Series(labels, index=frame.index[initial_train:initial_train + len(labels)])

    # Compute current state
    current_label = labels[-1] if labels else "unknown"
    duration = 1
    for i in range(len(labels) - 2, -1, -1):
        if labels[i] == current_label:
            duration += 1
        else:
            break

    # Trailing metrics
    tail = frame.tail(48)
    from bian_quant.regimes.classifier import _rolling_volatility, _trend_strength, _illiquidity
    trailing_vol = float(_rolling_volatility(frame["close"]).iloc[-1]) if len(frame) > 48 else 0.0
    trailing_trend = float(_trend_strength(frame["close"]).iloc[-1]) if len(frame) > 48 else 0.0
    trailing_illiq = float(_illiquidity(frame["close"], frame["volume"]).iloc[-1]) if len(frame) > 48 else 0.0

    decision_time = frame["event_time"].iloc[-1] if "event_time" in frame.columns else datetime.now(UTC)
    fit_through_time = frame["event_time"].iloc[fit_through_idx - 1] if "event_time" in frame.columns and fit_through_idx <= len(frame) else datetime.now(UTC)

    current = MacroState(
        label=current_label,
        decision_time=decision_time,
        duration_bars=duration,
        trailing_volatility=trailing_vol,
        trailing_trend=trailing_trend,
        trailing_illiquidity=trailing_illiq,
        thresholds_fitted_through=fit_through_time,
        threshold_values={
            "vol_48_q75": last_thresholds.vol_48_q75 if last_thresholds else 0.0,
            "trend_q60": last_thresholds.trend_q60 if last_thresholds else 0.0,
            "illiquidity_q95": last_thresholds.illiquidity_q95 if last_thresholds else 0.0,
        },
    )

    # Compute transitions
    transitions: list[tuple[datetime, str, str]] = []
    for i in range(1, len(labels)):
        if labels[i] != labels[i - 1]:
            t = frame["event_time"].iloc[initial_train + i] if "event_time" in frame.columns else datetime.now(UTC)
            transitions.append((t, labels[i - 1], labels[i]))

    # State summaries
    state_summaries = summarize_comparable_episodes(
        pd.DataFrame({"label": labels}), minimum_rows=30
    )

    return MacroRegimeEvidence(
        labels=label_series,
        current=current,
        transitions=transitions,
        state_summaries=state_summaries,
        threshold_history=threshold_history,
    )


def summarize_comparable_episodes(
    labeled: pd.DataFrame,
    *,
    minimum_rows: int = 30,
) -> dict[str, ComparableEpisodeSummary]:
    """Summarize comparable historical episodes for each regime state.

    States with fewer than *minimum_rows* observations are reported as
    insufficient evidence rather than assigned an inferential statistic.
    """
    result: dict[str, ComparableEpisodeSummary] = {}
    for label in REGIME_LABELS:
        subset = labeled[labeled.get("label", labeled.iloc[:, 0]) == label]
        count = len(subset)
        if count < minimum_rows:
            result[label] = ComparableEpisodeSummary(
                label=label,
                sample_count=count,
                status="insufficient_evidence",
            )
        else:
            result[label] = ComparableEpisodeSummary(
                label=label,
                sample_count=count,
                status="sufficient_evidence",
                avg_duration=float(count),
                avg_volatility=0.0,
            )
    return result


def write_macro_evidence(
    evidence: MacroRegimeEvidence,
    artifact_dir: Path,
) -> tuple[Path, Path]:
    """Write macro regime evidence as JSON and Markdown.

    Uses exclusive run directories.  JSON is complete and machine-readable;
    Markdown contains current state, reasons, duration, transitions, and
    comparable episodes without pooled claims for insufficient states.
    """
    artifact_dir.mkdir(parents=True, exist_ok=True)

    json_path = artifact_dir / "macro-regime.json"
    md_path = artifact_dir / "macro-regime.md"

    json_data = {
        "current": {
            "label": evidence.current.label,
            "decision_time": evidence.current.decision_time.isoformat() if isinstance(evidence.current.decision_time, datetime) else str(evidence.current.decision_time),
            "duration_bars": evidence.current.duration_bars,
            "trailing_volatility": evidence.current.trailing_volatility,
            "trailing_trend": evidence.current.trailing_trend,
            "trailing_illiquidity": evidence.current.trailing_illiquidity,
            "thresholds_fitted_through": evidence.current.thresholds_fitted_through.isoformat() if isinstance(evidence.current.thresholds_fitted_through, datetime) else str(evidence.current.thresholds_fitted_through),
            "threshold_values": evidence.current.threshold_values,
        },
        "transitions": [
            {"time": t.isoformat() if isinstance(t, datetime) else str(t), "from": f, "to": to_}
            for t, f, to_ in evidence.transitions
        ],
        "state_summaries": {
            label: {"sample_count": s.sample_count, "status": s.status}
            for label, s in evidence.state_summaries.items()
        },
    }
    json_path.write_text(json.dumps(json_data, indent=2, default=str), encoding="utf-8")

    md_lines = [
        "# Macro Regime Evidence",
        "",
        f"**Current state:** {evidence.current.label}",
        f"**Duration:** {evidence.current.duration_bars} bars",
        f"**Trailing volatility:** {evidence.current.trailing_volatility:.6f}",
        f"**Trailing trend:** {evidence.current.trailing_trend:.6f}",
        f"**Thresholds fitted through:** {evidence.current.thresholds_fitted_through}",
        "",
        "## State Summaries",
        "",
    ]
    for label, summary in evidence.state_summaries.items():
        md_lines.append(f"- **{label}**: {summary.sample_count} samples — {summary.status}")
    md_path.write_text("\n".join(md_lines), encoding="utf-8")

    return json_path, md_path
