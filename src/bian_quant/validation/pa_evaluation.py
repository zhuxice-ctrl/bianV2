import argparse
import hashlib
import json
from dataclasses import asdict, dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from bian_quant.backtest.engine import EventEngine
from bian_quant.backtest.events import Bar, SignalEvent
from bian_quant.data.quality import inspect_ohlcv
from bian_quant.experiments.models import LockedHoldout, RunManifest, RunStatus
from bian_quant.legacy.pa_baseline import replay_all
from bian_quant.signals.legacy_pa import adapt_confluence_signals
from bian_quant.validation.bootstrap import stationary_block_ci
from bian_quant.validation.metrics import max_drawdown, sharpe_ratio
from bian_quant.validation.promotion import (
    FoldMetrics,
    PromotionDiagnostics,
    PromotionPolicy,
)
from bian_quant.validation.splits import TimeFold, anchored_walk_forward, partition_locked_holdout

PERIODS_PER_YEAR_4H = 365 * 6


@dataclass(frozen=True)
class WindowResult:
    returns: list[float]
    total_return: float
    sharpe: float
    max_drawdown: float
    trades: int


def _window_summary(result: WindowResult) -> dict[str, float | int]:
    return {
        "total_return": result.total_return,
        "sharpe": result.sharpe,
        "max_drawdown": result.max_drawdown,
        "trades": result.trades,
    }


def _load_frame(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path)
    frame["event_time"] = pd.to_datetime(frame.pop("datetime"), utc=True)
    frame = frame.set_index("event_time").sort_index()
    if frame.index.has_duplicates:
        raise ValueError(f"duplicate timestamps in {path}")
    return frame


def _bars(frame: pd.DataFrame, index: pd.DatetimeIndex, duration: pd.Timedelta) -> list[Bar]:
    selected = frame.loc[index]
    bars = []
    for timestamp, row in selected.iterrows():
        if not isinstance(timestamp, pd.Timestamp):
            raise TypeError("PA frame index must contain timestamps")
        bars.append(
            Bar(
                timestamp=(timestamp + duration).to_pydatetime(),
                open=Decimal(str(row["open"])),
                high=Decimal(str(row["high"])),
                low=Decimal(str(row["low"])),
                close=Decimal(str(row["close"])),
                volume=Decimal(str(row["volume"])),
            )
        )
    return bars


def _strategy_parameters(scale: float) -> dict[str, int]:
    return {
        "atr_period": max(2, round(14 * scale)),
        "ema_fast": max(2, round(20 * scale)),
        "ema_slow": max(3, round(50 * scale)),
        "ema_trend": max(4, round(200 * scale)),
    }


def _signal_events(
    frame: pd.DataFrame,
    index: pd.DatetimeIndex,
    *,
    asset: str,
    duration: pd.Timedelta,
    parameter_scale: float,
) -> list[SignalEvent]:
    from strategies.price_action import confluence_signals

    parameters = _strategy_parameters(parameter_scale)
    enriched = confluence_signals(frame, **parameters)
    records = adapt_confluence_signals(
        frame,
        asset=asset,
        horizon="4h",
        strategy_parameters=parameters,
    )
    allowed_source_times = set(index)
    events: list[SignalEvent] = []
    for record in records:
        source_time = pd.Timestamp(record.decision_time) - duration
        if source_time not in allowed_source_times:
            continue
        atr_value = float(enriched.loc[source_time, "atr"])
        if not np.isfinite(atr_value) or atr_value <= 0:
            continue
        stop_distance = Decimal(str(atr_value * 1.5))
        events.append(
            SignalEvent(
                timestamp=record.decision_time,
                available_time=record.available_time,
                direction=record.direction,
                stop_distance=stop_distance,
                target_distance=stop_distance * Decimal("3"),
            )
        )
    return events


def _run_asset_window(
    frame: pd.DataFrame,
    index: pd.DatetimeIndex,
    *,
    asset: str,
    fee_bps: float,
    slippage_bps: float,
    parameter_scale: float = 1.0,
) -> WindowResult:
    duration = pd.Timedelta("4h")
    result = EventEngine(
        taker_fee_bps=Decimal(str(fee_bps)),
        slippage_bps=Decimal(str(slippage_bps)),
        initial_equity=Decimal("10000"),
        gross_limit=Decimal("1"),
        close_at_end=True,
    ).run(
        bars=_bars(frame, index, duration),
        signals=_signal_events(
            frame,
            index,
            asset=asset,
            duration=duration,
            parameter_scale=parameter_scale,
        ),
    )
    returns = [float(value) for value in result.returns]
    equity = [float(value) for value in result.equity]
    total_return = equity[-1] / 10_000.0 - 1.0 if equity else 0.0
    return WindowResult(
        returns=returns,
        total_return=total_return,
        sharpe=sharpe_ratio(returns, periods_per_year=PERIODS_PER_YEAR_4H),
        max_drawdown=max_drawdown(equity),
        trades=len(result.trades),
    )


def _run_portfolio_window(
    frames: dict[str, pd.DataFrame],
    index: pd.DatetimeIndex,
    *,
    fee_bps: float,
    slippage_bps: float,
    parameter_scale: float = 1.0,
) -> tuple[WindowResult, dict[str, WindowResult]]:
    by_asset = {
        asset: _run_asset_window(
            frame,
            index,
            asset=asset,
            fee_bps=fee_bps,
            slippage_bps=slippage_bps,
            parameter_scale=parameter_scale,
        )
        for asset, frame in frames.items()
    }
    portfolio_returns = np.mean(
        np.asarray([result.returns for result in by_asset.values()], dtype=np.float64), axis=0
    )
    equity = np.cumprod(1.0 + portfolio_returns) * 10_000.0
    return (
        WindowResult(
            returns=portfolio_returns.tolist(),
            total_return=float(equity[-1] / 10_000.0 - 1.0),
            sharpe=sharpe_ratio(portfolio_returns.tolist(), periods_per_year=PERIODS_PER_YEAR_4H),
            max_drawdown=max_drawdown(equity.tolist()),
            trades=sum(result.trades for result in by_asset.values()),
        ),
        by_asset,
    )


def _fold_results(
    frames: dict[str, pd.DataFrame],
    folds: list[TimeFold],
    *,
    fee_bps: float,
    slippage_bps: float,
    parameter_scale: float = 1.0,
) -> tuple[list[FoldMetrics], list[float], dict[str, float]]:
    metrics: list[FoldMetrics] = []
    all_returns: list[float] = []
    asset_returns: dict[str, list[float]] = {asset: [] for asset in frames}
    for fold in folds:
        portfolio, by_asset = _run_portfolio_window(
            frames,
            fold.test,
            fee_bps=fee_bps,
            slippage_bps=slippage_bps,
            parameter_scale=parameter_scale,
        )
        metrics.append(
            FoldMetrics(
                net_return=portfolio.total_return,
                sharpe=portfolio.sharpe,
                max_drawdown=portfolio.max_drawdown,
            )
        )
        all_returns.extend(portfolio.returns)
        for asset, result in by_asset.items():
            asset_returns[asset].append(result.total_return)
    return (
        metrics,
        all_returns,
        {asset: float(np.sum(values)) for asset, values in asset_returns.items()},
    )


def evaluate_pa(repo_root: Path, *, code_sha: str) -> dict[str, Any]:
    config_path = repo_root / "configs" / "experiments" / "baseline_pa.yaml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assets = tuple(config["assets"])
    frames = {asset: _load_frame(repo_root / "data" / f"{asset}_4h.csv") for asset in assets}
    common_index = frames[assets[0]].index
    if not isinstance(common_index, pd.DatetimeIndex):
        raise TypeError("PA frame index must be a DatetimeIndex")
    if any(not frame.index.equals(common_index) for frame in frames.values()):
        raise ValueError("PA assets must share an identical 4h index")

    locked_size = int(config["locked_holdout"]["size"])
    research_index, locked_index = partition_locked_holdout(common_index, locked_size)
    walk = config["walk_forward"]
    folds = anchored_walk_forward(
        research_index,
        initial_train=int(walk["initial_train_size"]),
        test_size=int(walk["test_size"]),
        step=int(walk["step"]),
        label_horizon=int(walk["label_horizon"]),
        embargo=int(walk["embargo"]),
    )
    if not folds:
        raise ValueError("baseline PA configuration produced no OOS folds")

    normal_costs = config["costs"]["normal"]
    stress_costs = config["costs"]["stress"]
    normal_folds, normal_returns, asset_returns = _fold_results(
        frames,
        folds,
        fee_bps=float(normal_costs["taker_fee_bps"]),
        slippage_bps=float(normal_costs["slippage_bps"]),
    )
    repeat_folds, repeat_returns, _ = _fold_results(
        frames,
        folds,
        fee_bps=float(normal_costs["taker_fee_bps"]),
        slippage_bps=float(normal_costs["slippage_bps"]),
    )
    stress_folds, _, _ = _fold_results(
        frames,
        folds,
        fee_bps=float(stress_costs["taker_fee_bps"]),
        slippage_bps=float(stress_costs["slippage_bps"]),
    )
    down_folds, _, _ = _fold_results(
        frames,
        folds,
        fee_bps=float(normal_costs["taker_fee_bps"]),
        slippage_bps=float(normal_costs["slippage_bps"]),
        parameter_scale=0.9,
    )
    up_folds, _, _ = _fold_results(
        frames,
        folds,
        fee_bps=float(normal_costs["taker_fee_bps"]),
        slippage_bps=float(normal_costs["slippage_bps"]),
        parameter_scale=1.1,
    )
    locked_portfolio, locked_assets = _run_portfolio_window(
        frames,
        locked_index,
        fee_bps=float(normal_costs["taker_fee_bps"]),
        slippage_bps=float(normal_costs["slippage_bps"]),
    )
    full_snapshot = {
        asset: _run_asset_window(
            frame,
            common_index,
            asset=asset,
            fee_bps=float(normal_costs["taker_fee_bps"]),
            slippage_bps=float(normal_costs["slippage_bps"]),
        )
        for asset, frame in frames.items()
    }

    ci_lower, ci_upper = stationary_block_ci(
        normal_returns,
        statistic=lambda values: sharpe_ratio(
            values.tolist(), periods_per_year=PERIODS_PER_YEAR_4H
        ),
        block_size=42,
        samples=500,
        seed=int(config["seed"]),
    )
    absolute_contributions = sum(abs(value) for value in asset_returns.values())
    concentration_passed = absolute_contributions > 0 and (
        max(abs(value) for value in asset_returns.values()) / absolute_contributions <= 0.60
    )
    normal_median = float(np.median([fold.net_return for fold in normal_folds]))
    parameter_stability = all(
        np.sign(float(np.median([fold.net_return for fold in variant]))) == np.sign(normal_median)
        for variant in (down_folds, up_folds)
    )
    quality_passed = all(
        not inspect_ohlcv(frame.reset_index(), expected_frequency="4h").blocking
        for frame in frames.values()
    )
    diagnostics = PromotionDiagnostics(
        baseline_increment=False,
        concentration=concentration_passed,
        parameter_stability=parameter_stability,
        leakage=True,
        reproducibility=(normal_folds == repeat_folds and normal_returns == repeat_returns),
        data_quality=quality_passed,
    )
    decision = PromotionPolicy().evaluate(
        normal_folds,
        sharpe_ci_lower=ci_lower,
        stress_drawdown=min(fold.max_drawdown for fold in stress_folds),
        diagnostics=diagnostics,
    )

    dataset_snapshot_ids = []
    for asset in assets:
        content_hash = hashlib.sha256(
            (repo_root / "data" / f"{asset}_4h.csv").read_bytes()
        ).hexdigest()
        dataset_snapshot_ids.append(f"legacy-{asset}-4h-{content_hash}")
    manifest = RunManifest.create(
        strategy_name="legacy.pa_confluence",
        code_sha=code_sha,
        dataset_snapshot_ids=dataset_snapshot_ids,
        config=config,
        seed=int(config["seed"]),
        locked_holdout=LockedHoldout(
            start=locked_index.min().to_pydatetime(),
            end=(locked_index.max() + pd.Timedelta("4h")).to_pydatetime(),
        ),
    ).model_copy(update={"status": RunStatus.PASSED if decision.passed else RunStatus.FAILED})
    return {
        "run_manifest": manifest.model_dump(mode="json"),
        "decision": asdict(decision),
        "diagnostics": asdict(diagnostics),
        "sharpe_ci": [ci_lower, ci_upper],
        "normal_folds": [asdict(fold) for fold in normal_folds],
        "stress_folds": [asdict(fold) for fold in stress_folds],
        "parameter_down_folds": [asdict(fold) for fold in down_folds],
        "parameter_up_folds": [asdict(fold) for fold in up_folds],
        "locked_holdout": {
            "portfolio": _window_summary(locked_portfolio),
            "assets": {asset: _window_summary(result) for asset, result in locked_assets.items()},
        },
        "legacy_engine": replay_all(repo_root)["results"],
        "new_engine_full_snapshot": {
            asset: _window_summary(result) for asset, result in full_snapshot.items()
        },
        "notes": {
            "baseline_increment": "false: Baseline-0 has no independent incremental comparator",
            "locked_holdout_usage": (
                "evaluated once after research folds; not used to tune thresholds"
            ),
        },
    }


def render_markdown(evidence: dict[str, Any]) -> str:
    decision = evidence["decision"]
    lines = [
        "# PA Validation Result",
        "",
        f"- Decision: **{'PASS' if decision['passed'] else 'FAIL'}**",
        f"- Reasons: `{', '.join(decision['reasons']) or 'none'}`",
        f"- Positive fold ratio: `{decision['positive_fold_ratio']:.4f}`",
        f"- Median Sharpe: `{decision['median_sharpe']:.4f}`",
        f"- Sharpe CI lower: `{decision['sharpe_ci_lower']:.4f}`",
        f"- Normal max drawdown: `{decision['normal_max_drawdown']:.4f}`",
        f"- Stress drawdown: `{decision['stress_drawdown']:.4f}`",
        "",
        "## OOS folds",
        "",
        "| Fold | Net return | Sharpe | Max drawdown |",
        "|---:|---:|---:|---:|",
    ]
    lines.extend(
        (
            f"| {index} | {fold['net_return']:.4f} | {fold['sharpe']:.4f} "
            f"| {fold['max_drawdown']:.4f} |"
        )
        for index, fold in enumerate(evidence["normal_folds"])
    )
    lines.extend(
        [
            "",
            "## Locked holdout",
            "",
            f"Portfolio return: `{evidence['locked_holdout']['portfolio']['total_return']:.4f}`  ",
            f"Portfolio Sharpe: `{evidence['locked_holdout']['portfolio']['sharpe']:.4f}`  ",
            (
                "Portfolio max drawdown: "
                f"`{evidence['locked_holdout']['portfolio']['max_drawdown']:.4f}`"
            ),
            "",
            (
                "The locked holdout was evaluated once after research folds "
                "and was not used for tuning."
            ),
        ]
    )
    return "\n".join(lines) + "\n"


def render_comparison(evidence: dict[str, Any]) -> str:
    lines = [
        "# PA Engine Comparison: Legacy vs Deterministic Event Engine",
        "",
        "Both engines were run on the restored BTC/ETH/BNB 4h files. The numerical table is",
        "evidence of semantic differences, not a claim that the engines use identical sizing.",
        "",
        (
            "| Asset | Legacy return | New return | Legacy MDD | New MDD "
            "| Legacy trades | New trades |"
        ),
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for asset in sorted(evidence["legacy_engine"]):
        legacy = evidence["legacy_engine"][asset]
        new = evidence["new_engine_full_snapshot"][asset]
        lines.append(
            f"| {asset} | {legacy['total_return_pct'] / 100:.4f} | {new['total_return']:.4f} "
            f"| {legacy['max_drawdown_pct'] / 100:.4f} | {new['max_drawdown']:.4f} "
            f"| {legacy['total_trades']} | {new['trades']} |"
        )
    lines.extend(
        [
            "",
            "## Semantic differences",
            "",
            "- Both enter no earlier than the next bar open.",
            "- The new engine applies explicit adverse slippage and fees on every fill.",
            "- Same-bar stop/target conflicts use the explicit conservative `STOP_FIRST` policy.",
            "- The new engine caps notional at current equity and uses Decimal arithmetic.",
            (
                "- The legacy engine uses 2% stop-risk sizing; "
                "the new comparison uses gross limit 1.0."
            ),
            "- Final open positions are explicitly closed at the final close in this comparison.",
            "",
            "## Promotion result",
            "",
            f"Decision: **{'PASS' if evidence['decision']['passed'] else 'FAIL'}**  ",
            f"Reasons: `{', '.join(evidence['decision']['reasons']) or 'none'}`",
            "",
            "See `pa-validation-result.json` for fold, stress, locked-holdout, manifest,",
            "dataset-hash, and diagnostic evidence.",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--code-sha", required=True)
    parser.add_argument(
        "--output", type=Path, default=Path("docs/evidence/pa-validation-result.json")
    )
    parser.add_argument(
        "--comparison-output",
        type=Path,
        default=Path("docs/evidence/pa-engine-comparison.md"),
    )
    args = parser.parse_args()
    evidence = evaluate_pa(args.repo_root.resolve(), code_sha=args.code_sha)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    args.output.with_suffix(".md").write_text(render_markdown(evidence), encoding="utf-8")
    args.comparison_output.write_text(render_comparison(evidence), encoding="utf-8")


if __name__ == "__main__":
    main()
