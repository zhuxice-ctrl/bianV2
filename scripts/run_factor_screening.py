"""Run Price/Volume factor screening on real BTC/ETH/BNB 4h data.

Generates Markdown + JSON evidence with per-fold/asset/regime IC.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from bian_quant.factors.evaluate import evaluate_factor
from bian_quant.factors.labels import forward_log_return
from bian_quant.factors.price import momentum, realized_volatility, reversal
from bian_quant.factors.volume import amihud_illiquidity, volume_surprise
from bian_quant.regimes.classifier import classify_regime, fit_regime_thresholds

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
ASSETS = ["BTCUSDT", "ETHUSDT", "BNBUSDT"]
INTERVAL = "4h"
FACTORS = {
    "momentum_24": lambda df: momentum(df["close"], periods=24),
    "reversal_12": lambda df: reversal(df["close"], periods=12),
    "realized_vol_24": lambda df: realized_volatility(df["close"], periods=24),
    "volume_surprise_24": lambda df: volume_surprise(df["volume"], periods=24),
    "amihud_24": lambda df: amihud_illiquidity(df["close"], df["volume"], periods=24),
}


def load_asset_data(asset: str) -> pd.DataFrame:
    """Load 4h CSV data for an asset."""
    path = DATA_DIR / f"{asset}_{INTERVAL}.csv"
    df = pd.read_csv(path)
    # Standardize column names
    cols = {c.lower(): c for c in df.columns}
    if "open_time" in cols:
        df["timestamp"] = pd.to_datetime(df[cols["open_time"]], unit="ms", utc=True)
    elif "timestamp" in cols:
        df["timestamp"] = pd.to_datetime(df[cols["timestamp"]], utc=True)
    else:
        df["timestamp"] = pd.to_datetime(df.iloc[:, 0], utc=True)

    df["available_time"] = df["timestamp"]
    df["asset"] = asset
    df = df.rename(
        columns={c.lower(): c for c in df.columns if c.lower() in ["open", "high", "low", "close", "volume"]}
    )
    return df[["timestamp", "available_time", "asset", "close", "volume"]]


def create_walk_forward_splits(n: int, n_folds: int = 3, purge: int = 6) -> dict:
    """Create walk-forward splits."""
    fold_size = n // (n_folds + 1)
    splits = {}
    for i in range(n_folds):
        train_end = fold_size * (i + 1)
        test_start = train_end + purge
        test_end = min(test_start + fold_size, n)
        if test_start >= n or test_end <= test_start:
            continue
        splits[f"fold_{i}"] = (np.arange(0, train_end), np.arange(test_start, test_end))
    if not splits:
        mid = int(n * 0.6)
        splits["fold_0"] = (np.arange(0, mid), np.arange(mid, n))
    return splits


def run_screening() -> None:
    """Run factor screening on real data."""
    all_evaluations = []
    summary_lines = [
        "# Price/Volume Factor Screening Results",
        "",
        "## Overview",
        "",
        f"- **Assets**: {', '.join(ASSETS)}",
        f"- **Interval**: {INTERVAL}",
        f"- **Factors**: {', '.join(FACTORS.keys())}",
        "",
        "## Methodology",
        "",
        "- Walk-forward splits with 6-bar purge between train and test",
        "- Regime thresholds fit on train fold only (no full-sample quantiles)",
        "- IC reported by fold, asset, and regime (no pooled metrics)",
        "- Forward 1-bar log return as label",
        "",
        "## Results",
        "",
    ]

    for asset in ASSETS:
        df = load_asset_data(asset)
        n = len(df)
        if n < 200:
            summary_lines.append(f"- **{asset}**: insufficient data ({n} bars), skipped\n")
            continue

        splits = create_walk_forward_splits(n)
        summary_lines.append(f"### {asset} ({n} bars, {len(splits)} folds)\n")

        for fold_name, (train_idx, test_idx) in splits.items():
            train_data = df.iloc[train_idx]
            test_data = df.iloc[test_idx]

            # Fit regime thresholds on train only
            train_frame = pd.DataFrame(
                {"close": train_data["close"], "volume": train_data["volume"]}
            )
            thresholds = fit_regime_thresholds(train_frame)

            # Classify test data
            test_frame = pd.DataFrame(
                {"close": test_data["close"], "volume": test_data["volume"]}
            )
            regimes = classify_regime(test_frame, thresholds)

            # Build label
            label = forward_log_return(test_data["close"], periods=1)

            # Evaluate each factor
            for factor_name, factor_fn in FACTORS.items():
                try:
                    factor_values = factor_fn(test_data)
                    train_factor_values = factor_fn(train_data)

                    metadata = pd.DataFrame(
                        {"asset": [asset] * len(test_data), "regime": regimes.values},
                        index=test_data.index,
                    )

                    evals = evaluate_factor(
                        factor_values,
                        label,
                        metadata,
                        fold=fold_name,
                        winsor_limits=(0.01, 0.99),
                        train_factor=train_factor_values,
                    )
                    all_evaluations.extend(evals)
                except Exception as e:
                    summary_lines.append(f"- Error evaluating {factor_name} for {asset}@{fold_name}: {e}\n")

    # Build summary tables
    summary_lines.append("\n## Per-Factor IC Summary\n")
    summary_lines.append("| Factor | Fold | Asset | Regime | Spearman IC | Pearson IC | Coverage | N | CI Lower | CI Upper |")
    summary_lines.append("|--------|------|-------|--------|-------------|------------|----------|---|----------|----------|")

    for ev in all_evaluations:
        summary_lines.append(
            f"| {ev.factor_name} | {ev.fold} | {ev.asset} | {ev.regime} | "
            f"{ev.spearman_ic:.4f} | {ev.pearson_ic:.4f} | {ev.coverage:.2f} | "
            f"{ev.sample_count} | {ev.ci_lower:.4f} | {ev.ci_upper:.4f} |"
        )

    # Aggregate stats
    summary_lines.append("\n## Aggregate Statistics\n")
    factor_stats: dict[str, list[float]] = {}
    for ev in all_evaluations:
        factor_stats.setdefault(ev.factor_name, []).append(ev.spearman_ic)

    summary_lines.append("| Factor | Mean IC | Median IC | Std IC | N Groups |")
    summary_lines.append("|--------|---------|-----------|--------|----------|")
    for fname, ics in sorted(factor_stats.items()):
        ics_arr = np.array(ics)
        ics_valid = ics_arr[~np.isnan(ics_arr)]
        if len(ics_valid) > 0:
            summary_lines.append(
                f"| {fname} | {np.mean(ics_valid):.4f} | {np.median(ics_valid):.4f} | "
                f"{np.std(ics_valid):.4f} | {len(ics_valid)} |"
            )

    # Write Markdown evidence
    evidence_dir = Path("docs/evidence")
    evidence_dir.mkdir(parents=True, exist_ok=True)
    md_path = evidence_dir / "factor-screening-results.md"
    md_path.write_text("\n".join(summary_lines))

    # Write JSON evidence
    json_path = evidence_dir / "factor-screening-results.json"
    json_data = {
        "assets": ASSETS,
        "interval": INTERVAL,
        "factors": list(FACTORS.keys()),
        "evaluations": [
            {
                "factor_name": ev.factor_name,
                "fold": ev.fold,
                "asset": ev.asset,
                "regime": ev.regime,
                "spearman_ic": ev.spearman_ic,
                "pearson_ic": ev.pearson_ic,
                "coverage": ev.coverage,
                "sample_count": ev.sample_count,
                "ci_lower": ev.ci_lower,
                "ci_upper": ev.ci_upper,
            }
            for ev in all_evaluations
        ],
    }
    json_path.write_text(json.dumps(json_data, indent=2, default=str))

    print(f"Evidence written to {md_path} and {json_path}")
    print(f"Total evaluations: {len(all_evaluations)}")


if __name__ == "__main__":
    run_screening()
