"""Run the reproducible BTC/ETH/BNB 4h price/volume factor screen."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

import pandas as pd

from bian_quant.experiments.registry import ExperimentRegistry
from bian_quant.factors.registry import FactorRegistry
from bian_quant.factors.runner import FactorRunConfig, run_factor_pipeline
from bian_quant.factors.screening import (
    BUILTIN_FACTOR_FUNCTIONS,
    builtin_factor_specs,
    load_legacy_screening_data,
)

ASSETS = ["BTCUSDT", "ETHUSDT", "BNBUSDT"]
INTERVAL = "4h"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--code-sha", required=True)
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--output-dir", type=Path, default=Path("docs/evidence"))
    parser.add_argument("--state-dir", type=Path, default=Path("var/factor_screening"))
    parser.add_argument("--seed", type=int, default=7)
    return parser.parse_args()


def run_screening(args: argparse.Namespace) -> tuple[Path, Path]:
    data, snapshot_id = load_legacy_screening_data(args.data_dir, assets=ASSETS, interval=INTERVAL)
    args.state_dir.mkdir(parents=True, exist_ok=True)
    specs = builtin_factor_specs(horizon=INTERVAL)
    config = FactorRunConfig(
        dataset_snapshot_id=snapshot_id,
        factor_specs=specs,
        split_config={"n_folds": 3, "train_ratio": 0.6, "purge_bars": 6},
        code_sha=args.code_sha,
        seed=args.seed,
        artifact_dir=args.state_dir / "artifacts",
        experiment_registry_path=args.state_dir / "experiments.sqlite",
        bh_alpha=0.05,
        redundancy_distance=0.3,
        incremental_cost_bps=5.0,
    )

    with (
        FactorRegistry(args.state_dir / "factors.sqlite") as factor_registry,
        ExperimentRegistry(config.experiment_registry_path) as experiment_registry,
    ):
        result = run_factor_pipeline(
            config,
            data,
            registry=factor_registry,
            factor_functions=BUILTIN_FACTOR_FUNCTIONS,
            experiment_registry=experiment_registry,
        )
    if result.status != "completed" or result.artifact_path is None:
        raise RuntimeError(result.error or f"factor screen ended as {result.status}")

    artifact = json.loads(result.artifact_path.read_text(encoding="utf-8"))
    evidence = _build_evidence(
        artifact,
        data=data,
        data_dir=args.data_dir,
        snapshot_id=snapshot_id,
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.output_dir / "factor-screening-results.json"
    markdown_path = args.output_dir / "factor-screening-results.md"
    json_path.write_text(
        json.dumps(evidence, indent=2, sort_keys=True, allow_nan=False),
        encoding="utf-8",
    )
    markdown_path.write_text(_render_markdown(evidence), encoding="utf-8")
    return markdown_path, json_path


def _build_evidence(
    artifact: dict[str, Any],
    *,
    data: pd.DataFrame,
    data_dir: Path,
    snapshot_id: str,
) -> dict[str, Any]:
    source_files = []
    for asset in ASSETS:
        path = data_dir / f"{asset}_{INTERVAL}.csv"
        source_files.append(
            {
                "asset": asset,
                "path": path.as_posix(),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "rows": int((data["asset"] == asset).sum()),
            }
        )

    evaluations = artifact["evaluations"]
    decisions = artifact["multiple_testing"]
    accepted_by_factor: Counter[str] = Counter()
    tested_by_factor: Counter[str] = Counter()
    for key, decision in decisions.items():
        factor_name = key.split("@", maxsplit=1)[0]
        tested_by_factor[factor_name] += 1
        if decision["rejected_null"]:
            accepted_by_factor[factor_name] += 1

    return {
        "evidence_version": 2,
        "run": {
            "run_id": artifact["run_id"],
            "status": artifact["status"],
            "code_sha": artifact["code_sha"],
            "seed": artifact["seed"],
            "dataset_snapshot_id": snapshot_id,
            "split_config": artifact["split_config"],
        },
        "data": {
            "assets": ASSETS,
            "interval": INTERVAL,
            "availability_semantics": (
                "OHLCV close and volume become usable at CSV close_time; "
                "factor decision timestamp equals available_time"
            ),
            "source_files": source_files,
            "min_event_time": data["event_time"].min().isoformat(),
            "max_available_time": data["available_time"].max().isoformat(),
        },
        "methodology": {
            "label": "forward one-bar log return, created separately per asset",
            "regime_thresholds": "fit on each training fold only",
            "confidence_interval": "stationary-block bootstrap of Spearman RankIC",
            "multiple_testing": "Benjamini-Hochberg at alpha=0.05 across reported slices",
            "minimum_inference_samples": 30,
            "redundancy": "train-only absolute Spearman distance clustering",
            "incremental": (
                "ridge weights fit on the final training fold and measured on its "
                "disjoint validation fold with 5 bps turnover cost"
            ),
        },
        "factors": list(BUILTIN_FACTOR_FUNCTIONS),
        "evaluations": evaluations,
        "multiple_testing": decisions,
        "multiple_testing_summary": {
            factor_name: {
                "tested_slices": tested_by_factor[factor_name],
                "bh_surviving_slices": accepted_by_factor[factor_name],
            }
            for factor_name in BUILTIN_FACTOR_FUNCTIONS
        },
        "redundancy": artifact["redundancy"],
        "incremental_contribution": artifact["incremental_contribution"],
        "lifecycle_states": artifact["lifecycle_states"],
        "promotion_decision": {
            "status": "NO_AUTOMATIC_CANDIDATE_PROMOTION",
            "reason": (
                "This run records reproducible observations. Candidate promotion requires "
                "a later explicit gate using stability, BH, redundancy, and incremental evidence."
            ),
        },
        "derivatives_screening": {
            "status": "BLOCKED",
            "reason": (
                "Funding/OI factor code has causal fixture coverage, but no canonical "
                "Funding/OI snapshot is present in this workspace for real-data screening."
            ),
        },
    }


def _format_metric(value: Any) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def _render_markdown(evidence: dict[str, Any]) -> str:
    run = evidence["run"]
    data = evidence["data"]
    lines = [
        "# Price/Volume Factor Screening Results",
        "",
        "## Run identity",
        "",
        f"- Run ID: `{run['run_id']}`",
        f"- Code SHA: `{run['code_sha']}`",
        f"- Dataset snapshot: `{run['dataset_snapshot_id']}`",
        f"- Assets: {', '.join(data['assets'])}",
        f"- Interval: {data['interval']}",
        f"- Availability: {data['availability_semantics']}",
        "",
        "## Decision",
        "",
        "**No factor is automatically promoted to candidate.** This screen creates auditable "
        "observations; promotion remains a separate decision gate.",
        "",
        "Funding/OI real-data screening is **BLOCKED** because no canonical Funding/OI "
        "snapshot is present. Causal fixture tests are not treated as market evidence.",
        "",
        "## Multiple-testing summary",
        "",
        "| Factor | Tested slices | BH-surviving slices |",
        "|---|---:|---:|",
    ]
    for factor_name, summary in evidence["multiple_testing_summary"].items():
        lines.append(
            f"| {factor_name} | {summary['tested_slices']} | {summary['bh_surviving_slices']} |"
        )

    lines.extend(
        [
            "",
            "## Redundancy clusters",
            "",
            "| Factor | Cluster | Rejection reason |",
            "|---|---:|---|",
        ]
    )
    redundancy = evidence["redundancy"]
    for factor_name, cluster_id in redundancy["clusters"].items():
        reason = redundancy["rejected"].get(factor_name, "representative")
        lines.append(f"| {factor_name} | {cluster_id} | {reason} |")

    lines.extend(
        [
            "",
            "## Incremental validation",
            "",
            "| Factor | Standalone IC | Delta IC | Delta cost-adjusted return | Incremental |",
            "|---|---:|---:|---:|---|",
        ]
    )
    for item in evidence["incremental_contribution"]:
        lines.append(
            f"| {item['factor_name']} | {_format_metric(item['standalone_ic'])} | "
            f"{_format_metric(item['incremental_ic'])} | "
            f"{_format_metric(item['delta_cost_adjusted_return'])} | "
            f"{item['has_incremental_value']} |"
        )

    lines.extend(
        [
            "",
            "## Lifecycle state",
            "",
            "| Factor | State after evidence run |",
            "|---|---|",
        ]
    )
    for factor_name, state in evidence["lifecycle_states"].items():
        lines.append(f"| {factor_name} | {state} |")

    lines.extend(
        [
            "",
            "## Per-fold / asset / regime evidence",
            "",
            "The table below contains no pooled replacement metric. Raw and BH-adjusted "
            "p-values for every row are retained in the companion JSON file.",
            "",
            "| Factor | Fold | Asset | Regime | RankIC | Pearson IC | Coverage | N | "
            "RankIC CI | Raw p |",
            "|---|---|---|---|---:|---:|---:|---:|---|---:|",
        ]
    )
    for item in evidence["evaluations"]:
        ci = f"[{_format_metric(item['ci_lower'])}, {_format_metric(item['ci_upper'])}]"
        lines.append(
            f"| {item['factor_name']} | {item['fold']} | {item['asset']} | "
            f"{item['regime']} | {_format_metric(item['spearman_ic'])} | "
            f"{_format_metric(item['pearson_ic'])} | {_format_metric(item['coverage'])} | "
            f"{item['sample_count']} | {ci} | {_format_metric(item['p_value'])} |"
        )
    lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    markdown, json_file = run_screening(parse_args())
    print(markdown)
    print(json_file)
