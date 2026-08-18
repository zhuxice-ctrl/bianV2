"""Production Development input construction for the orderflow gate.

This module consumes an already-resolved research snapshot frame and produces
only synthetic, in-memory slice evaluations.  It does not know about catalog
paths, Holdout ledgers, Candidate registries, or trading interfaces.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import numpy as np
import pandas as pd
from scipy import stats as sp_stats  # type: ignore[import-untyped]

from bian_quant.factors.labels import forward_open_to_open_log_return
from bian_quant.factors.taker_orderflow import taker_orderflow_imbalance
from bian_quant.regimes.classifier import classify_regime, fit_regime_thresholds
from bian_quant.research.orderflow_gate import (
    GateConfig,
    PreregisteredUnit,
    SliceEvaluation,
)
from bian_quant.validation.splits import anchored_walk_forward


@dataclass(frozen=True)
class OrderflowGateInputs:
    """Pure in-memory inputs for the Development gate."""

    slices: tuple[SliceEvaluation, ...]
    preregistered_units: tuple[PreregisteredUnit, ...]
    fold_count: int
    development_rows: int


def _slice_statistics(
    factor: pd.Series,
    label: pd.Series,
) -> tuple[float | None, float, int]:
    common = (
        pd.DataFrame({"factor": factor, "label": label}).replace([np.inf, -np.inf], np.nan).dropna()
    )
    n_effective = len(common)
    if n_effective < 30:
        return None, float("nan"), n_effective
    factor_values = common["factor"].to_numpy(dtype=float)
    label_values = common["label"].to_numpy(dtype=float)
    if np.ptp(factor_values) == 0.0 or np.ptp(label_values) == 0.0:
        return None, float("nan"), n_effective
    result = sp_stats.spearmanr(factor_values, label_values)
    if np.isnan(result.statistic) or np.isnan(result.pvalue):
        return None, float("nan"), n_effective
    return float(result.pvalue), float(result.statistic), n_effective


def build_orderflow_gate_inputs(
    frame: pd.DataFrame,
    *,
    development_start: datetime,
    development_end_exclusive: datetime,
    config: GateConfig | None = None,
) -> OrderflowGateInputs:
    """Build causal slice evaluations from a locked research frame.

    The frame must already have been filtered to the locked universe.  Bars
    after ``development_end_exclusive`` are discarded before fold construction,
    so no alignment or holdout rows can influence thresholds or labels.
    """
    cfg = config or GateConfig()
    required = {
        "asset",
        "event_time",
        "available_time",
        "open",
        "volume",
        "quote_volume",
        "taker_buy_base",
        "close",
    }
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"ORDERFLOW_GATE_SCHEMA_INVALID:{','.join(sorted(missing))}")

    start = pd.Timestamp(development_start).tz_convert("UTC")
    end = pd.Timestamp(development_end_exclusive).tz_convert("UTC")
    source = frame.copy()
    source["available_time"] = pd.to_datetime(source["available_time"], utc=True)
    source["event_time"] = pd.to_datetime(source["event_time"], utc=True)
    source = source.loc[
        (source["available_time"] >= start) & (source["available_time"] < end)
    ].copy()
    source = source.sort_values(["asset", "available_time"]).reset_index(drop=True)

    slices: list[SliceEvaluation] = []
    units: list[PreregisteredUnit] = []
    fold_count = 0
    horizons = tuple(cfg.required_horizons)
    qs = tuple(sorted({cfg.primary_q, *cfg.sensitivity_qs}))
    all_signals, _ = taker_orderflow_imbalance(source)

    for asset, asset_frame in source.groupby("asset", sort=True):
        source_positions = asset_frame.index.to_numpy(dtype=int)
        work = asset_frame.reset_index(drop=True)
        index = pd.DatetimeIndex(work["available_time"])
        if len(work) < 100:
            continue
        initial_train = max(60, len(work) // 4)
        test_size = max(30, (len(work) - initial_train) // 3)
        folds = anchored_walk_forward(
            index,
            initial_train=initial_train,
            test_size=test_size,
            step=test_size,
            label_horizon=1,
            embargo=6,
        )
        fold_count += len(folds)
        signals = all_signals.iloc[source_positions].reset_index(drop=True)
        labels: dict[str, pd.Series] = {}
        reasons: dict[str, pd.Series] = {}
        for horizon in horizons:
            holding_bars = int(horizon.rstrip("h"))
            labels[horizon], reasons[horizon] = forward_open_to_open_log_return(
                work,
                holding_bars=holding_bars,
            )

        for fold in folds:
            train_positions = index.get_indexer(fold.train)
            test_positions = index.get_indexer(fold.test)
            train = work.iloc[train_positions]
            try:
                thresholds = fit_regime_thresholds(train[["close", "volume"]])
            except ValueError:
                continue
            regimes = classify_regime(work[["close", "volume"]], thresholds)
            fold_name = f"fold_{fold.number}"
            test_regimes = regimes.iloc[test_positions]
            for regime in sorted(test_regimes.dropna().unique().tolist()):
                regime_mask = test_regimes == regime
                positions = test_positions[np.asarray(regime_mask, dtype=bool)]
                if len(positions) == 0:
                    continue
                primary_labels = labels[cfg.primary_horizon].iloc[positions]
                primary_reasons = reasons[cfg.primary_horizon].iloc[positions]
                primary_signals = signals.iloc[positions]
                effective = int(
                    pd.DataFrame({"signal": primary_signals, "label": primary_labels})
                    .replace([np.inf, -np.inf], np.nan)
                    .dropna()
                    .shape[0]
                )
                units.append(
                    PreregisteredUnit(
                        fold=fold_name,
                        asset=str(asset),
                        regime=str(regime),
                        effective_bar_count=effective,
                        missing_next_bar_count=int((primary_reasons == "MISSING_NEXT_BAR").sum()),
                        execution_infeasible_count=int(
                            (primary_reasons == "EXECUTION_BAR_INVALID").sum()
                        ),
                    )
                )
                bars = frozenset(int(position) for position in positions)
                for horizon in horizons:
                    horizon_labels = labels[horizon].iloc[positions]
                    for q in qs:
                        p_value, direction, n_effective = _slice_statistics(
                            primary_signals,
                            horizon_labels,
                        )
                        slices.append(
                            SliceEvaluation(
                                factor_id="taker_orderflow_imbalance",
                                horizon=horizon,
                                q=float(q),
                                fold=fold_name,
                                asset=str(asset),
                                regime=str(regime),
                                p_value=p_value,
                                direction_estimate=direction,
                                n_effective=n_effective,
                                test_bar_indices=bars,
                            )
                        )

    return OrderflowGateInputs(
        slices=tuple(slices),
        preregistered_units=tuple(units),
        fold_count=fold_count,
        development_rows=len(source),
    )
