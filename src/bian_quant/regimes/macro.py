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

import pandas as pd

from bian_quant.regimes.classifier import (
    REGIME_LABELS,
    RegimeThresholds,
    _illiquidity,
    _rolling_volatility,
    _trend_strength,
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
    reason_codes: tuple[str, ...] = ()


@dataclass(frozen=True)
class MacroDecision:
    """Causal evidence attached to one historical classification decision."""

    label: str
    decision_time: datetime
    thresholds_fitted_through: datetime
    threshold_values: dict[str, float]
    inputs: dict[str, float]
    reason_codes: tuple[str, ...]


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
    threshold_history: list[dict[str, float | int]] = field(default_factory=list)
    decisions: list[MacroDecision] = field(default_factory=list)


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
    if n <= initial_train:
        raise ValueError("insufficient data for initial training window")
    if refit_every < 1:
        raise ValueError("refit_every must be positive")
    if "event_time" not in frame:
        raise ValueError("event_time is required for causal macro evidence")
    work = frame.copy()
    work["event_time"] = pd.to_datetime(work["event_time"], utc=True, errors="coerce")
    if work["event_time"].isna().any() or not work["event_time"].is_monotonic_increasing:
        raise ValueError("event_time must be valid and sorted")
    frame = work

    labels: list[str] = []
    threshold_history: list[dict[str, float | int]] = []
    decisions: list[MacroDecision] = []
    last_thresholds: RegimeThresholds | None = None
    fit_through_idx = 0

    # Initial fit on first `initial_train` rows
    train_frame = frame.iloc[:initial_train]
    thresholds = fit_regime_thresholds(train_frame)
    last_thresholds = thresholds
    fit_through_idx = initial_train
    threshold_history.append(
        {
            "fit_through_idx": initial_train,
            "fitted_through": frame["event_time"].iloc[initial_train - 1].isoformat(),
            "effective_from": frame["event_time"].iloc[initial_train].isoformat(),
            "vol_48_q75": thresholds.vol_48_q75,
            "trend_q60": thresholds.trend_q60,
            "illiquidity_q95": thresholds.illiquidity_q95,
        }
    )

    # Classify in blocks, refitting every `refit_every` rows
    volatility = _rolling_volatility(frame["close"])
    trend = _trend_strength(frame["close"])
    illiquidity = _illiquidity(frame["close"], frame["volume"])
    idx = initial_train
    while idx < n:
        block_end = min(idx + refit_every, n)
        # Include the causal prefix so rolling inputs do not reset at block
        # boundaries, then retain only decisions in this block.
        block_labels = classify_regime(frame.iloc[:block_end], last_thresholds).iloc[idx:block_end]
        labels.extend(block_labels.tolist())
        fit_time = frame["event_time"].iloc[fit_through_idx - 1]
        threshold_values = _threshold_values(last_thresholds)
        for decision_index, label in zip(range(idx, block_end), block_labels.tolist(), strict=True):
            decision_time = frame["event_time"].iloc[decision_index]
            if fit_time >= decision_time:
                raise AssertionError("macro thresholds must be fit strictly before decisions")
            inputs = {
                "trailing_volatility": float(volatility.iloc[decision_index]),
                "trailing_trend": float(trend.iloc[decision_index]),
                "trailing_illiquidity": float(illiquidity.iloc[decision_index]),
            }
            decisions.append(
                MacroDecision(
                    label=str(label),
                    decision_time=decision_time,
                    thresholds_fitted_through=fit_time,
                    threshold_values=threshold_values.copy(),
                    inputs=inputs,
                    reason_codes=_classification_reasons(inputs, last_thresholds),
                )
            )

        # Refit only when another block remains.  The final partial block must
        # retain thresholds fitted strictly before its first decision row.
        if block_end < n:
            train_frame = frame.iloc[:block_end]
            last_thresholds = fit_regime_thresholds(train_frame)
            fit_through_idx = block_end
            threshold_history.append(
                {
                    "fit_through_idx": block_end,
                    "fitted_through": frame["event_time"].iloc[block_end - 1].isoformat(),
                    "effective_from": frame["event_time"].iloc[block_end].isoformat(),
                    "vol_48_q75": last_thresholds.vol_48_q75,
                    "trend_q60": last_thresholds.trend_q60,
                    "illiquidity_q95": last_thresholds.illiquidity_q95,
                }
            )
        idx = block_end

    label_series = pd.Series(labels, index=frame.index[initial_train : initial_train + len(labels)])

    # Compute current state
    current_label = labels[-1] if labels else "unknown"
    duration = 1
    for i in range(len(labels) - 2, -1, -1):
        if labels[i] == current_label:
            duration += 1
        else:
            break

    final_decision = decisions[-1]

    current = MacroState(
        label=current_label,
        decision_time=final_decision.decision_time,
        duration_bars=duration,
        trailing_volatility=final_decision.inputs["trailing_volatility"],
        trailing_trend=final_decision.inputs["trailing_trend"],
        trailing_illiquidity=final_decision.inputs["trailing_illiquidity"],
        thresholds_fitted_through=final_decision.thresholds_fitted_through,
        threshold_values=final_decision.threshold_values,
        reason_codes=final_decision.reason_codes,
    )

    # Compute transitions
    transitions: list[tuple[datetime, str, str]] = []
    for i in range(1, len(labels)):
        if labels[i] != labels[i - 1]:
            t = (
                frame["event_time"].iloc[initial_train + i]
                if "event_time" in frame.columns
                else datetime.now(UTC)
            )
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
        decisions=decisions,
    )


def _threshold_values(thresholds: RegimeThresholds) -> dict[str, float]:
    return {
        "vol_48_q75": thresholds.vol_48_q75,
        "trend_q60": thresholds.trend_q60,
        "illiquidity_q95": thresholds.illiquidity_q95,
    }


def _classification_reasons(
    inputs: dict[str, float], thresholds: RegimeThresholds
) -> tuple[str, ...]:
    if inputs["trailing_illiquidity"] > thresholds.illiquidity_q95:
        return ("ILLIQUIDITY_ABOVE_Q95",)
    trend_reason = (
        "TREND_ABOVE_Q60"
        if inputs["trailing_trend"] > thresholds.trend_q60
        else "TREND_AT_OR_BELOW_Q60"
    )
    volatility_reason = (
        "VOLATILITY_ABOVE_Q75"
        if inputs["trailing_volatility"] > thresholds.vol_48_q75
        else "VOLATILITY_AT_OR_BELOW_Q75"
    )
    return (trend_reason, volatility_reason)


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
            episode_ids = (subset.index.to_series().diff().fillna(1) != 1).cumsum()
            durations = subset.groupby(episode_ids).size()
            result[label] = ComparableEpisodeSummary(
                label=label,
                sample_count=count,
                status="sufficient_evidence",
                avg_duration=float(durations.mean()),
                avg_volatility=(
                    float(subset["trailing_volatility"].mean())
                    if "trailing_volatility" in subset
                    else None
                ),
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
    json_path = artifact_dir / "macro-regime.json"
    md_path = artifact_dir / "macro-regime.md"

    if json_path.exists() or md_path.exists():
        raise FileExistsError(f"macro evidence already exists in {artifact_dir}")

    json_data = macro_evidence_payload(evidence)
    markdown = render_macro_evidence_markdown(evidence)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    with json_path.open("x", encoding="utf-8") as handle:
        json.dump(json_data, handle, indent=2, default=str)
    with md_path.open("x", encoding="utf-8") as handle:
        handle.write(markdown)

    return json_path, md_path


def macro_evidence_payload(evidence: MacroRegimeEvidence) -> dict[str, object]:
    """Return the complete JSON-safe Macro evidence without writing files."""
    return {
        "current": {
            "label": evidence.current.label,
            "decision_time": evidence.current.decision_time.isoformat()
            if isinstance(evidence.current.decision_time, datetime)
            else str(evidence.current.decision_time),
            "duration_bars": evidence.current.duration_bars,
            "trailing_volatility": evidence.current.trailing_volatility,
            "trailing_trend": evidence.current.trailing_trend,
            "trailing_illiquidity": evidence.current.trailing_illiquidity,
            "thresholds_fitted_through": evidence.current.thresholds_fitted_through.isoformat()
            if isinstance(evidence.current.thresholds_fitted_through, datetime)
            else str(evidence.current.thresholds_fitted_through),
            "threshold_values": evidence.current.threshold_values,
            "reason_codes": list(evidence.current.reason_codes),
        },
        "transitions": [
            {"time": t.isoformat() if isinstance(t, datetime) else str(t), "from": f, "to": to_}
            for t, f, to_ in evidence.transitions
        ],
        "state_summaries": {
            label: {
                "sample_count": summary.sample_count,
                "status": summary.status,
                **(
                    {
                        "avg_duration": summary.avg_duration,
                        "avg_volatility": summary.avg_volatility,
                    }
                    if summary.status == "sufficient_evidence"
                    else {}
                ),
            }
            for label, summary in evidence.state_summaries.items()
        },
        "threshold_history": evidence.threshold_history,
        "decisions": [
            {
                "label": decision.label,
                "decision_time": decision.decision_time.isoformat(),
                "thresholds_fitted_through": decision.thresholds_fitted_through.isoformat(),
                "threshold_values": decision.threshold_values,
                "inputs": decision.inputs,
                "reason_codes": list(decision.reason_codes),
            }
            for decision in evidence.decisions
        ],
    }


def render_macro_evidence_markdown(evidence: MacroRegimeEvidence) -> str:
    """Render human-readable Macro evidence without touching the filesystem."""
    md_lines = [
        "# Macro Regime Evidence",
        "",
        f"**Current state:** {evidence.current.label}",
        f"**Duration:** {evidence.current.duration_bars} bars",
        f"**Trailing volatility:** {evidence.current.trailing_volatility:.6f}",
        f"**Trailing trend:** {evidence.current.trailing_trend:.6f}",
        f"**Trailing illiquidity:** {evidence.current.trailing_illiquidity:.6f}",
        f"**Thresholds fitted through:** {evidence.current.thresholds_fitted_through}",
        f"**Threshold values:** {json.dumps(evidence.current.threshold_values, sort_keys=True)}",
        f"**Reason codes:** {', '.join(evidence.current.reason_codes)}",
        "",
        "## Transitions",
        "",
    ]
    if evidence.transitions:
        md_lines.extend(
            f"- {time}: {from_state} → {to_state}"
            for time, from_state, to_state in evidence.transitions
        )
    else:
        md_lines.append("- No transitions observed.")
    md_lines.extend(
        [
            "",
            "## Threshold History",
            "",
        ]
    )
    md_lines.extend(
        f"- effective {item['effective_from']}; fitted through {item['fitted_through']}; "
        f"vol={item['vol_48_q75']:.6g}, trend={item['trend_q60']:.6g}, "
        f"illiquidity={item['illiquidity_q95']:.6g}"
        for item in evidence.threshold_history
    )
    md_lines.extend(
        [
            "",
            "## State Summaries",
            "",
        ]
    )
    for label, summary in evidence.state_summaries.items():
        md_lines.append(f"- **{label}**: {summary.sample_count} samples — {summary.status}")
    return "\n".join(md_lines)
