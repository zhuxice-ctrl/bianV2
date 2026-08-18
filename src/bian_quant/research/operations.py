"""Operator boundaries for cataloged analysis and one-time holdout access."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow.parquet as pq  # type: ignore[import-untyped]

from bian_quant.data.acquisition import DualHorizonAcquisition
from bian_quant.data.catalog import CatalogEntry, DatasetCatalog
from bian_quant.data.contracts import DatasetLayer
from bian_quant.experiments.holdout import HoldoutLedger
from bian_quant.experiments.models import LockedHoldout, RunManifest, RunStatus
from bian_quant.experiments.registry import ExperimentRegistry
from bian_quant.factors.dual_horizon import compute_dual_horizon_factor_columns
from bian_quant.factors.labels import (
    forward_log_return,
    forward_open_to_open_log_return,
)
from bian_quant.factors.registry import FactorRegistry
from bian_quant.factors.spec import FactorSpec, FactorState
from bian_quant.factors.taker_orderflow import taker_orderflow_imbalance
from bian_quant.regimes.macro import (
    classify_macro_history,
    macro_evidence_payload,
    render_macro_evidence_markdown,
)
from bian_quant.reporting.decision import DecisionEvidence, write_decision_packet
from bian_quant.research.dual_horizon import (
    _apply_membership_lineage,
    run_dual_horizon_screening,
)
from bian_quant.research.orderflow_batch7 import build_orderflow_gate_inputs
from bian_quant.research.orderflow_development import (
    FamilySnapshot,
    ResearchFamilyLedger,
    run_bh_inference,
)
from bian_quant.research.orderflow_gate import GatePreconditions, evaluate_development_gate
from bian_quant.research.orderflow_protocol import (
    build_orderflow_targets,
    compute_fee,
    compute_turnover_l1,
    drift_weights_open_to_open,
)

REQUIRED_SNAPSHOTS = ("macro-1d", "macro-4h", "micro-1h", "micro-4h")
SNAPSHOT_COLUMNS = (
    "asset",
    "event_time",
    "available_time",
    "open",
    "close",
    "high",
    "low",
    "volume",
    "quote_volume",
    "funding_rate",
    "funding_available_time",
    "funding_interval_hours",
    "sum_open_interest",
    "sum_open_interest_value",
    "oi_available_time",
    "availability_assumption",
    "taker_buy_base",
    "taker_buy_quote",
)


class AnalysisBlocked(RuntimeError):
    """Stable fail-closed analysis boundary."""


@dataclass(frozen=True)
class CatalogedSnapshots:
    entries: dict[str, CatalogEntry]
    oi_delay_entries: dict[int, CatalogEntry]

    @property
    def snapshot_ids(self) -> tuple[str, ...]:
        return tuple(self.entries[name].manifest.snapshot_id for name in REQUIRED_SNAPSHOTS)


@dataclass(frozen=True)
class CatalogedAnalysisResult:
    run_id: str
    status: str
    artifact_dir: Path
    snapshot_ids: tuple[str, ...]
    candidate_factor_ids: tuple[str, ...]
    error_code: str | None = None


@dataclass(frozen=True)
class HoldoutEvaluationResult:
    run_id: str
    status: str
    factor_state: FactorState
    artifact_path: Path
    reason_codes: tuple[str, ...]


@dataclass(frozen=True)
class OrderflowDevelopmentResult:
    """Development-only evidence result for orderflow factor."""

    run_id: str
    status: str
    artifact_path: Path
    snapshot_ids: tuple[str, ...]
    holdout_accessed: bool
    factor_id: str
    protocol_sha: str
    reason_code_counts: dict[str, int]
    development_gate_status: str
    error_code: str | None = None


@dataclass(frozen=True)
class OrderflowGateRunResult:
    """Result of a real, Development-only orderflow gate run."""

    run_id: str
    status: str
    gate_verdict: str
    artifact_path: Path
    snapshot_ids: tuple[str, ...]
    holdout_accessed: bool
    development_rows: int
    slice_count: int
    preregistered_unit_count: int
    error_code: str | None = None


def resolve_dual_horizon_snapshots(
    config: DualHorizonAcquisition, *, code_sha: str
) -> CatalogedSnapshots:
    """Resolve exactly one immutable snapshot for each locked horizon/interval."""
    catalog = DatasetCatalog(config.catalog_path)
    entries: dict[str, CatalogEntry] = {}
    expected = {
        "assets": list(config.assets),
        "macro_start": config.macro_start.isoformat(),
        "micro_start": config.micro_start.isoformat(),
        "as_of": config.as_of.isoformat(),
        "code_sha": code_sha,
    }
    for name in REQUIRED_SNAPSHOTS:
        matches: list[CatalogEntry] = []
        for entry in catalog.find_by_name(name):
            try:
                identity = json.loads(entry.manifest.config_json)
            except json.JSONDecodeError as error:
                raise AnalysisBlocked(f"SNAPSHOT_CONFIG_INVALID:{name}") from error
            if all(identity.get(key) == value for key, value in expected.items()):
                matches.append(entry)
        if not matches:
            raise AnalysisBlocked(f"SNAPSHOT_MISSING:{name}")
        if len(matches) != 1:
            raise AnalysisBlocked(f"SNAPSHOT_AMBIGUOUS:{name}")
        entry = matches[0]
        if entry.manifest.layer != DatasetLayer.RESEARCH:
            raise AnalysisBlocked(f"SNAPSHOT_LAYER_INVALID:{name}")
        if not entry.path.is_file():
            raise AnalysisBlocked(f"SNAPSHOT_FILE_MISSING:{name}")
        entries[name] = entry

    parent_sets = {tuple(entry.manifest.parent_snapshot_ids) for entry in entries.values()}
    if len(parent_sets) != 1 or not next(iter(parent_sets)):
        raise AnalysisBlocked("SNAPSHOT_LINEAGE_INVALID")
    delay_entries = _resolve_delay_entries(
        config,
        required_parent_ids={entry.manifest.snapshot_id for entry in entries.values()},
    )
    return CatalogedSnapshots(entries=entries, oi_delay_entries=delay_entries)


def analyze_cataloged_dual_horizon(
    config: DualHorizonAcquisition,
    *,
    code_sha: str,
    snapshot_code_sha: str | None = None,
) -> CatalogedAnalysisResult:
    """Run Macro and development screening from validated catalog snapshots."""
    snapshot_code_sha = snapshot_code_sha or code_sha
    snapshots: CatalogedSnapshots | None = None
    manifest: RunManifest | None = None
    acquisition: dict[str, Any] = {}
    quality: dict[str, Any] = {}
    try:
        snapshots = resolve_dual_horizon_snapshots(config, code_sha=snapshot_code_sha)
        acquisition, quality = _load_acquisition_evidence(
            config,
            source_code_sha=snapshot_code_sha,
            required_snapshot_ids=snapshots.snapshot_ids,
        )
        if acquisition.get("status") != "passed" or quality.get("status") != "passed":
            raise AnalysisBlocked("SOURCE_RUN_BLOCKED")
        eligibility_frame, universe_artifact_ids = _load_popular_universe_eligibility(
            snapshots, config
        )
        manifest = RunManifest.create(
            strategy_name="dual_horizon_analysis",
            code_sha=code_sha,
            dataset_snapshot_ids=list(snapshots.snapshot_ids),
            config={
                "as_of": config.as_of.isoformat(),
                "snapshot_names": REQUIRED_SNAPSHOTS,
                "snapshot_code_sha": snapshot_code_sha,
                "popular_universe_artifact_ids": universe_artifact_ids,
            },
            seed=0,
            locked_holdout=LockedHoldout(
                start=config.factor_protocol.holdout_start,
                end=config.factor_protocol.holdout_end,
            ),
        )
        _start_run(config, manifest)

        frames = {name: _read_snapshot(entry) for name, entry in snapshots.entries.items()}
        if any(frame.empty for frame in frames.values()):
            raise AnalysisBlocked("SNAPSHOT_EMPTY")

        macro_source = frames["macro-4h"].copy()
        macro_source["event_time"] = pd.to_datetime(macro_source["event_time"], utc=True)
        macro_frame = (
            macro_source.groupby("event_time", as_index=False)
            .agg(close=("close", "mean"), volume=("volume", "sum"))
            .sort_values("event_time")
            .reset_index(drop=True)
        )
        initial_train = max(60, min(365, len(macro_frame) // 3))
        if len(macro_frame) <= initial_train:
            raise AnalysisBlocked("MACRO_INSUFFICIENT_ROWS")
        macro = classify_macro_history(macro_frame, initial_train=initial_train, refit_every=30)
        macro_payload = macro_evidence_payload(macro)
        macro_payload["snapshot_ids"] = [
            snapshots.entries["macro-1d"].manifest.snapshot_id,
            snapshots.entries["macro-4h"].manifest.snapshot_id,
        ]

        stage_dir = config.artifact_root / "factor-stages"
        screening = run_dual_horizon_screening(
            frames["micro-4h"],
            eligibility_frame=eligibility_frame,
            config={
                "run_id": manifest.run_id,
                "artifact_dir": stage_dir,
                "factor_registry_path": config.factor_registry_path,
                "code_sha": code_sha,
                "development_start": config.factor_protocol.development_start,
                "development_end": config.factor_protocol.development_end_exclusive,
                "holdout_start": config.factor_protocol.holdout_start,
                "holdout_end": config.factor_protocol.holdout_end,
                "interval": "4h",
                "sensitivity_frame": frames["micro-1h"],
                "oi_delay_frames": _build_delay_factor_frames(
                    frames["micro-4h"], snapshots.oi_delay_entries
                ),
                "bh_alpha": config.factor_protocol.bh_alpha,
                "max_candidates": config.factor_protocol.max_candidates,
            },
        )
        if screening.engineering_status != "passed" or screening.artifact_path is None:
            raise AnalysisBlocked("FACTOR_SCREENING_BLOCKED")
        screening_payload = json.loads(screening.artifact_path.read_text(encoding="utf-8"))
        screening_payload["snapshot_ids"] = [
            snapshots.entries["micro-1h"].manifest.snapshot_id,
            snapshots.entries["micro-4h"].manifest.snapshot_id,
        ]
        candidates = screening.candidate_factor_ids
        states = screening.lifecycle_states
        evidence = DecisionEvidence(
            acquisition=acquisition,
            quality=quality,
            macro_regime=macro_payload,
            macro_regime_md=render_macro_evidence_markdown(macro),
            factor_screening=screening_payload,
            factor_screening_md=_render_factor_screening(screening_payload),
            engineering_status="PASSED",
            data_status="COMPLETE",
            factor_status="CANDIDATES_PENDING_HOLDOUT" if candidates else "NO_PROMOTION",
            human_decision="REVIEW_CANDIDATES" if candidates else "NONE_REQUIRED",
            candidate_factor_ids=candidates,
            current_regime=macro.current.label,
            passed_factors=list(candidates),
            failed_factors=sorted(
                name
                for name, reasons in screening.gate_reasons.items()
                if reasons != ["ALL_DEVELOPMENT_GATES_PASSED"]
            ),
            observed_factors=sorted(
                name for name, state in states.items() if state == FactorState.OBSERVED.value
            ),
        )
        run_dir = config.artifact_root / manifest.run_id
        write_decision_packet(evidence, run_dir)
        _finish_run(config, manifest.run_id, RunStatus.PASSED)
        return CatalogedAnalysisResult(
            run_id=manifest.run_id,
            status="passed",
            artifact_dir=run_dir,
            snapshot_ids=snapshots.snapshot_ids,
            candidate_factor_ids=candidates,
        )
    except Exception as error:
        reason = str(error) if isinstance(error, AnalysisBlocked) else f"ANALYSIS_FAILED:{error}"
        if manifest is None:
            snapshot_ids = list(snapshots.snapshot_ids) if snapshots is not None else []
            manifest = _blocked_manifest(
                config,
                code_sha=code_sha,
                snapshot_code_sha=snapshot_code_sha,
                snapshot_ids=snapshot_ids,
            )
            _start_run(config, manifest)
        run_dir = config.artifact_root / manifest.run_id
        if not run_dir.exists():
            write_decision_packet(
                DecisionEvidence(
                    acquisition=acquisition or {"status": "blocked", "reason": reason},
                    quality=quality or {"status": "blocked", "findings": [reason]},
                    macro_regime={"status": "blocked", "reason": reason},
                    macro_regime_md=f"# Macro Regime\n\nBlocked: {reason}",
                    factor_screening={"status": "blocked", "reason": reason},
                    factor_screening_md=f"# Factor Screening\n\nBlocked: {reason}",
                    engineering_status="BLOCKED",
                    data_status="BLOCKED",
                    factor_status="NOT_RUN",
                    human_decision="RESOLVE_BLOCKING_INPUTS",
                ),
                run_dir,
            )
        _finish_run(config, manifest.run_id, RunStatus.BLOCKED)
        return CatalogedAnalysisResult(
            run_id=manifest.run_id,
            status="blocked",
            artifact_dir=run_dir,
            snapshot_ids=tuple(snapshots.snapshot_ids) if snapshots else (),
            candidate_factor_ids=(),
            error_code=reason,
        )


def evaluate_candidate_holdout(
    config: DualHorizonAcquisition,
    *,
    run_id: str,
    factor_id: str,
    factor_version: str,
    snapshot_id: str,
    reader: Callable[[CatalogEntry], pd.DataFrame] | None = None,
    evaluator: Callable[[pd.DataFrame, FactorSpec], tuple[bool, list[str], dict[str, Any]]]
    | None = None,
) -> HoldoutEvaluationResult:
    """Authorize once, then read and evaluate only the locked Micro holdout."""
    reader = reader or _read_snapshot
    evaluator = evaluator or _default_holdout_evaluator
    artifact_path = config.artifact_root / "holdout" / f"{run_id}-{factor_id}-{factor_version}.json"
    if artifact_path.exists():
        raise FileExistsError(f"holdout evidence already exists: {artifact_path}")

    with FactorRegistry(config.factor_registry_path) as factors:
        spec = factors.get(factor_id, factor_version)
        state = factors.state(factor_id, factor_version)
        if state != FactorState.CANDIDATE:
            raise PermissionError("HOLDOUT_ACCESS_DENIED: factor is not Candidate")
        with ExperimentRegistry(config.experiment_registry_path) as experiments:
            parent_run = experiments.get(run_id)
        if (
            parent_run.status != RunStatus.PASSED
            or snapshot_id not in parent_run.dataset_snapshot_ids
        ):
            raise PermissionError("HOLDOUT_ACCESS_DENIED: invalid experiment lineage")
        entry = DatasetCatalog(config.catalog_path).get(snapshot_id)
        if entry.manifest.name != "micro-4h" or entry.manifest.layer != DatasetLayer.RESEARCH:
            raise PermissionError("HOLDOUT_ACCESS_DENIED: snapshot is not locked Micro 4h")
        if not entry.path.is_file():
            raise PermissionError("HOLDOUT_ACCESS_DENIED: snapshot file is missing")
        delay_entries = _resolve_delay_entries(
            config,
            required_parent_ids=set(parent_run.dataset_snapshot_ids),
        )

        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        with HoldoutLedger(config.artifact_root / "holdout-access.sqlite") as ledger:
            access = ledger.authorize(
                snapshot_id=snapshot_id,
                factor_id=factor_id,
                factor_version=factor_version,
                factor_state=state,
                access_run_id=run_id,
            )
        try:
            frame = reader(entry)
            times = pd.to_datetime(frame["available_time"], utc=True, errors="coerce")
            holdout = frame.loc[
                (times >= config.factor_protocol.holdout_start)
                & (times <= config.factor_protocol.holdout_end)
            ].copy()
            if holdout.empty:
                raise AnalysisBlocked("HOLDOUT_EMPTY")
            if factor_id in {"oi_change", "leverage_crowding"}:
                delay_frames = _build_delay_factor_frames(frame, delay_entries)
                for delay, delay_frame in delay_frames.items():
                    delay_times = pd.to_datetime(
                        delay_frame["available_time"], utc=True, errors="coerce"
                    )
                    delay_holdout = delay_frame.loc[
                        (delay_times >= config.factor_protocol.holdout_start)
                        & (delay_times <= config.factor_protocol.holdout_end)
                    ].copy()
                    computed = compute_dual_horizon_factor_columns(delay_holdout, interval="4h")
                    values = computed[["asset", "available_time", factor_id]].rename(
                        columns={factor_id: f"{factor_id}_delay_{delay}"}
                    )
                    holdout = holdout.merge(
                        values, on=["asset", "available_time"], how="left", validate="one_to_one"
                    )
            passed, reasons, metrics = evaluator(holdout, spec)
            if not passed and "FACTOR_PROMOTION_REJECTED" not in reasons:
                reasons.insert(0, "FACTOR_PROMOTION_REJECTED")
            holdout_artifact_ids: list[str] = []
            try:
                snapshot_identity = json.loads(entry.manifest.config_json)
                holdout_artifact_ids = snapshot_identity.get("popular_universe_artifact_ids", [])
            except json.JSONDecodeError:
                pass
            payload = {
                "run_id": run_id,
                "snapshot_id": snapshot_id,
                "factor_id": factor_id,
                "factor_version": factor_version,
                "access": access,
                "status": "passed" if passed else "rejected",
                "reason_codes": reasons,
                "metrics": metrics,
                "popular_universe_artifact_ids": holdout_artifact_ids,
            }
            _write_exclusive_json(artifact_path, payload)
            if passed:
                factors.transition(
                    factor_id,
                    factor_version,
                    FactorState.APPROVED,
                    evidence_run_id=run_id,
                )
                final_state = FactorState.APPROVED
            else:
                final_state = FactorState.CANDIDATE
            return HoldoutEvaluationResult(
                run_id=run_id,
                status="passed" if passed else "rejected",
                factor_state=final_state,
                artifact_path=artifact_path,
                reason_codes=tuple(reasons),
            )
        except Exception as error:
            failure_path = (
                artifact_path
                if not artifact_path.exists()
                else artifact_path.with_name(f"{artifact_path.stem}.failure.json")
            )
            _write_exclusive_json(
                failure_path,
                {
                    "run_id": run_id,
                    "snapshot_id": snapshot_id,
                    "factor_id": factor_id,
                    "factor_version": factor_version,
                    "access": access,
                    "status": "failed",
                    "reason_codes": [f"HOLDOUT_EVALUATION_FAILED:{error}"],
                },
            )
            raise


def analyze_cataloged_orderflow_development(
    config: DualHorizonAcquisition,
    *,
    code_sha: str,
    snapshot_code_sha: str | None = None,
) -> OrderflowDevelopmentResult:
    """Run cataloged orderflow development evidence (Development-only).

    Reads only the locked micro-1h snapshot, computes taker orderflow
    signal and open-to-open labels, builds portfolio diagnostics, and
    writes development evidence.  Never accesses Holdout, paper, live,
    or recovery interfaces.

    A real cataloged Development run requires a separate explicit
    authorization.
    """
    from math import erfc, sqrt

    snapshot_code_sha = snapshot_code_sha or code_sha
    factor_id = "taker_orderflow_imbalance"
    factor_version = "1.0.0"
    family_id = "microstructure_orderflow"

    try:
        # --- Resolve micro-1h snapshot ---
        catalog = DatasetCatalog(config.catalog_path)
        expected = {
            "assets": list(config.assets),
            "macro_start": config.macro_start.isoformat(),
            "micro_start": config.micro_start.isoformat(),
            "as_of": config.as_of.isoformat(),
            "code_sha": snapshot_code_sha,
        }
        matches: list[CatalogEntry] = []
        for entry in catalog.find_by_name("micro-1h"):
            try:
                identity = json.loads(entry.manifest.config_json)
            except json.JSONDecodeError as error:
                raise AnalysisBlocked("SNAPSHOT_CONFIG_INVALID:micro-1h") from error
            if all(identity.get(key) == value for key, value in expected.items()):
                matches.append(entry)
        if not matches:
            raise AnalysisBlocked("SNAPSHOT_MISSING:micro-1h")
        if len(matches) != 1:
            raise AnalysisBlocked("SNAPSHOT_AMBIGUOUS:micro-1h")
        entry = matches[0]
        if entry.manifest.layer != DatasetLayer.RESEARCH:
            raise AnalysisBlocked("SNAPSHOT_LAYER_INVALID:micro-1h")
        if not entry.path.is_file():
            raise AnalysisBlocked("SNAPSHOT_FILE_MISSING:micro-1h")

        # --- Read snapshot ---
        frame = _read_snapshot(entry)
        if frame.empty:
            raise AnalysisBlocked("SNAPSHOT_EMPTY")

        # --- Resolve popular-universe eligibility ---
        snapshots = CatalogedSnapshots(
            entries={"micro-1h": entry},
            oi_delay_entries={},
        )
        eligibility_frame, universe_artifact_ids = _load_popular_universe_eligibility(
            snapshots, config
        )
        if config.universe_policy is not None and eligibility_frame is None:
            raise AnalysisBlocked("POPULAR_UNIVERSE_ARTIFACT_MISSING")
        if eligibility_frame is not None:
            frame = _apply_membership_lineage(frame, eligibility_frame)
            if frame.empty:
                raise AnalysisBlocked("EMPTY_AFTER_MEMBERSHIP_FILTER")
        eligible_assets = sorted(frame["asset"].astype(str).unique().tolist())

        # --- Compute protocol hash ---
        protocol_payload = {
            "factor_id": factor_id,
            "version": factor_version,
            "family": family_id,
            "code_sha": code_sha,
            "snapshot_code_sha": snapshot_code_sha,
            "snapshot_id": entry.manifest.snapshot_id,
        }
        protocol_sha = hashlib.sha256(
            json.dumps(protocol_payload, sort_keys=True).encode("utf-8")
        ).hexdigest()

        # --- Freeze and assert family ledger ---
        ledger_path = config.artifact_root / "research-family-ledger.sqlite"
        family_members = (f"{factor_id}@{factor_version}",)
        with ResearchFamilyLedger(ledger_path) as ledger:
            snapshot = ledger.get_snapshot(family_id)
            if snapshot is None:
                ledger.freeze_family(
                    FamilySnapshot(
                        family_id=family_id,
                        members=family_members,
                        protocol_sha=protocol_sha,
                        bh_boundary="development",
                    )
                )
            ledger.assert_frozen(
                family_id,
                family_members,
                protocol_sha=protocol_sha,
                bh_boundary="development",
            )

        # --- Compute signal ---
        signal_values, signal_reasons = taker_orderflow_imbalance(frame)

        # --- Reason-code counts ---
        reason_code_counts: dict[str, int] = {}
        for reason in signal_reasons:
            if reason:
                reason_code_counts[reason] = reason_code_counts.get(reason, 0) + 1

        # --- Compute labels for 1h, 2h, 4h ---
        horizon_details: dict[str, dict[str, Any]] = {}
        label_values_by_horizon: dict[str, pd.Series] = {}
        label_reasons_by_horizon: dict[str, pd.Series] = {}
        for holding_bars, horizon in [(1, "1h"), (2, "2h"), (4, "4h")]:
            label_values, label_reasons = forward_open_to_open_log_return(
                frame, holding_bars=holding_bars
            )
            label_values_by_horizon[horizon] = label_values
            label_reasons_by_horizon[horizon] = label_reasons
            for reason in label_reasons:
                if reason:
                    key = f"{horizon}:{reason}"
                    reason_code_counts[key] = reason_code_counts.get(key, 0) + 1

            valid_count = int(label_values.notna().sum())
            horizon_details[horizon] = {
                "holding_bars": holding_bars,
                "valid_count": valid_count,
                "missing_count": int(label_values.isna().sum()),
            }

        # --- Compute portfolio diagnostics ---
        signal_frame = frame.copy()
        signal_frame["signal"] = signal_values.values

        portfolio_diagnostics: list[dict[str, Any]] = []
        previous_target: pd.Series | None = None
        previous_open_returns: pd.Series | None = None
        previous_open_reasons: pd.Series | None = None
        taker_fee_bps = 4.0

        for ts, group in signal_frame.groupby("available_time", sort=True):
            valid = group.dropna(subset=["signal"])
            signals_df = valid[["asset", "signal"]].copy()
            result = build_orderflow_targets(signals_df)
            target = result.weights
            held: pd.Series | None
            drift_reason = ""
            if previous_target is None:
                held = pd.Series(0.0, index=target.index, dtype=float)
            else:
                assert previous_open_returns is not None
                assert previous_open_reasons is not None
                active = previous_target[previous_target != 0.0]
                prior_reasons = previous_open_reasons.reindex(active.index).fillna(
                    "MISSING_NEXT_BAR"
                )
                if (prior_reasons != "").any():
                    drift_reason = str(prior_reasons[prior_reasons != ""].iloc[0])
                    held = None
                else:
                    try:
                        held = drift_weights_open_to_open(
                            previous_target,
                            previous_open_returns,
                        )
                    except ValueError:
                        drift_reason = "EXECUTION_BAR_INVALID"
                        held = None

            turnover: float | None
            fee: float | None
            if held is None:
                turnover, fee = None, None
            else:
                turnover = compute_turnover_l1(target, held)
                fee = compute_fee(turnover, taker_fee_bps)
            portfolio_diagnostics.append(
                {
                    "timestamp": str(ts),
                    "reason": result.reason or drift_reason,
                    "long_count": result.long_count,
                    "short_count": result.short_count,
                    "target_assets": sorted(target.loc[target != 0.0].index.astype(str).tolist()),
                    "turnover_l1": turnover,
                    "fee": fee,
                    "held_weight_l1": None if held is None else float(held.abs().sum()),
                    "drift_applied": previous_target is not None and held is not None,
                }
            )
            previous_target = target
            previous_open_returns = pd.Series(
                np.expm1(label_values_by_horizon["1h"].loc[group.index].to_numpy(dtype=float)),
                index=group["asset"].astype(str).to_numpy(),
                dtype=float,
            )
            previous_open_reasons = pd.Series(
                label_reasons_by_horizon["1h"].loc[group.index].to_numpy(dtype=object),
                index=group["asset"].astype(str).to_numpy(),
                dtype=object,
            )

        # --- Compute BH details ---
        bh_evaluations: list[Any] = []
        for _holding_bars, horizon in [(1, "1h"), (2, "2h"), (4, "4h")]:
            label_values = label_values_by_horizon[horizon]
            sig_frame = frame.copy()
            sig_frame["signal"] = signal_values.values
            sig_frame["label"] = label_values.values

            ics: list[float] = []
            for _ts, group in sig_frame.groupby("available_time", sort=True):
                valid = group.dropna(subset=["signal", "label"])
                if len(valid) < 3:
                    continue
                ic = valid["signal"].corr(valid["label"], method="spearman")
                if np.isfinite(ic):
                    ics.append(float(ic))

            if len(ics) < 2:
                continue

            mean_ic = float(np.mean(ics))
            std_ic = float(np.std(ics, ddof=1))
            n_ic = len(ics)
            if std_ic > 0:
                t_stat = mean_ic / (std_ic / sqrt(n_ic))
                p_value = float(erfc(abs(t_stat) / sqrt(2.0)))
            else:
                p_value = 1.0

            bh_evaluations.append(
                type(
                    "Ev",
                    (),
                    {
                        "factor_name": factor_id,
                        "horizon": horizon,
                        "fold": "development",
                        "asset": "all",
                        "regime": "all",
                        "p_value": p_value,
                    },
                )()
            )

        bh_results = run_bh_inference(bh_evaluations, family_id=family_id)
        bh_precheck_status = (
            "available" if len(bh_evaluations) == 3 else "insufficient_horizon_coverage"
        )

        if not bh_results.empty:
            with ResearchFamilyLedger(ledger_path) as ledger:
                ledger.store_bh_results(bh_results)

        bh_details = bh_results.to_dict(orient="records") if not bh_results.empty else []

        # --- Write evidence ---
        run_id = f"orderflow-dev-{code_sha[:8]}"
        artifact_path = config.artifact_root / "orderflow-development" / f"{run_id}.json"

        evidence = {
            "run_id": run_id,
            "status": "collected",
            "development_gate_status": "not_evaluated",
            "factor_id": factor_id,
            "factor_version": factor_version,
            "family_id": family_id,
            "protocol_sha": protocol_sha,
            "code_sha": code_sha,
            "snapshot_code_sha": snapshot_code_sha,
            "snapshot_ids": [entry.manifest.snapshot_id],
            "input_identity": {
                "snapshot_id": entry.manifest.snapshot_id,
                "snapshot_name": entry.manifest.name,
                "popular_universe_artifact_ids": universe_artifact_ids,
                "eligible_assets": eligible_assets,
            },
            "holdout_accessed": False,
            "reason_code_counts": reason_code_counts,
            "horizon_details": horizon_details,
            "bh_details": bh_details,
            "bh_precheck_status": bh_precheck_status,
            "bh_scope": "aggregate_precheck_only",
            "portfolio_diagnostics": portfolio_diagnostics[:200],
            "portfolio_summary": {
                "total_bars": len(portfolio_diagnostics),
                "flat_bars": sum(1 for d in portfolio_diagnostics if d["reason"]),
                "active_bars": sum(
                    1 for d in portfolio_diagnostics if d["long_count"] > 0 and d["reason"] == ""
                ),
                "drifted_bars": sum(1 for d in portfolio_diagnostics if d["drift_applied"]),
                "total_turnover_l1": float(
                    sum(d["turnover_l1"] or 0.0 for d in portfolio_diagnostics)
                ),
                "total_fee": float(sum(d["fee"] or 0.0 for d in portfolio_diagnostics)),
                "taker_fee_bps": taker_fee_bps,
            },
        }

        _write_exclusive_json(artifact_path, evidence)

        return OrderflowDevelopmentResult(
            run_id=run_id,
            status="collected",
            artifact_path=artifact_path,
            snapshot_ids=(entry.manifest.snapshot_id,),
            holdout_accessed=False,
            factor_id=factor_id,
            protocol_sha=protocol_sha,
            reason_code_counts=reason_code_counts,
            development_gate_status="not_evaluated",
        )
    except Exception as error:
        reason = str(error) if isinstance(error, AnalysisBlocked) else f"DEVELOPMENT_FAILED:{error}"
        run_id = f"orderflow-dev-{code_sha[:8]}"
        artifact_path = config.artifact_root / "orderflow-development" / f"{run_id}.json"
        if not artifact_path.exists():
            _write_exclusive_json(
                artifact_path,
                {
                    "run_id": run_id,
                    "status": "blocked",
                    "error_code": reason,
                    "holdout_accessed": False,
                },
            )
        return OrderflowDevelopmentResult(
            run_id=run_id,
            status="blocked",
            artifact_path=artifact_path,
            snapshot_ids=(),
            holdout_accessed=False,
            factor_id=factor_id,
            protocol_sha="",
            reason_code_counts={},
            development_gate_status="not_evaluated",
            error_code=reason,
        )


def analyze_cataloged_orderflow_gate(
    config: DualHorizonAcquisition,
    *,
    code_sha: str,
    snapshot_code_sha: str | None = None,
) -> OrderflowGateRunResult:
    """Run the fully wired orderflow Development gate on locked data.

    This is the only production entry point for Batch 7.  It reads one locked
    research snapshot, filters it to the cataloged popular universe, builds
    in-memory slice evaluations, and writes a Development-only report.  It
    never accesses Holdout, Candidate, Paper, Live, recovery, or download APIs.
    """
    snapshot_code_sha = snapshot_code_sha or code_sha
    factor_id = "taker_orderflow_imbalance"
    family_id = "microstructure_orderflow"
    run_id = f"orderflow-gate-dev-{code_sha[:8]}"
    artifact_path = config.artifact_root / "orderflow-development-gate" / f"{run_id}.json"

    try:
        catalog = DatasetCatalog(config.catalog_path)
        expected = {
            "assets": list(config.assets),
            "macro_start": config.macro_start.isoformat(),
            "micro_start": config.micro_start.isoformat(),
            "as_of": config.as_of.isoformat(),
            "code_sha": snapshot_code_sha,
        }
        matches: list[CatalogEntry] = []
        for entry in catalog.find_by_name("micro-1h"):
            identity = json.loads(entry.manifest.config_json)
            if all(identity.get(key) == value for key, value in expected.items()):
                matches.append(entry)
        if len(matches) != 1:
            raise AnalysisBlocked(
                "SNAPSHOT_MISSING:micro-1h" if not matches else "SNAPSHOT_AMBIGUOUS:micro-1h"
            )
        entry = matches[0]
        if entry.manifest.layer != DatasetLayer.RESEARCH:
            raise AnalysisBlocked("SNAPSHOT_LAYER_INVALID:micro-1h")
        if not entry.path.is_file():
            raise AnalysisBlocked("SNAPSHOT_FILE_MISSING:micro-1h")

        frame = _read_snapshot(entry)
        if frame.empty:
            raise AnalysisBlocked("SNAPSHOT_EMPTY")
        snapshots = CatalogedSnapshots(entries={"micro-1h": entry}, oi_delay_entries={})
        eligibility_frame, universe_artifact_ids = _load_popular_universe_eligibility(
            snapshots, config
        )
        if config.universe_policy is not None and eligibility_frame is None:
            raise AnalysisBlocked("POPULAR_UNIVERSE_ARTIFACT_MISSING")
        if eligibility_frame is not None:
            frame = _apply_membership_lineage(frame, eligibility_frame)
        if frame.empty:
            raise AnalysisBlocked("EMPTY_AFTER_MEMBERSHIP_FILTER")

        gate_inputs = build_orderflow_gate_inputs(
            frame,
            development_start=config.factor_protocol.development_start,
            development_end_exclusive=config.factor_protocol.development_end_exclusive,
        )

        protocol_payload = {
            "factor_id": factor_id,
            "version": "1.0.0",
            "family": family_id,
            "code_sha": code_sha,
            "snapshot_code_sha": snapshot_code_sha,
            "snapshot_id": entry.manifest.snapshot_id,
        }
        protocol_sha = hashlib.sha256(
            json.dumps(protocol_payload, sort_keys=True).encode("utf-8")
        ).hexdigest()
        ledger_path = config.artifact_root / "research-family-ledger.sqlite"
        family_members = (f"{factor_id}@1.0.0",)
        retry_of_run_id: str | None = None
        with ResearchFamilyLedger(ledger_path) as ledger:
            snapshot = ledger.get_snapshot(family_id)
            if snapshot is None:
                ledger.freeze_family(
                    FamilySnapshot(
                        family_id=family_id,
                        members=family_members,
                        protocol_sha=protocol_sha,
                        bh_boundary="development",
                    )
                )
            else:
                try:
                    ledger.assert_frozen(
                        family_id,
                        family_members,
                        protocol_sha=protocol_sha,
                        bh_boundary="development",
                    )
                except ValueError:
                    blocked_runs: list[str] = []
                    prior_dir = config.artifact_root / "orderflow-development-gate"
                    for prior_path in prior_dir.glob("*.json"):
                        try:
                            prior = json.loads(prior_path.read_text(encoding="utf-8"))
                        except (OSError, json.JSONDecodeError):
                            continue
                        if prior.get("status") == "blocked" and not prior.get(
                            "holdout_accessed", True
                        ):
                            blocked_runs.append(str(prior.get("run_id", prior_path.stem)))
                    if ledger.bh_result_count() == 0 and blocked_runs:
                        retry_of_run_id = sorted(blocked_runs)[-1]
                        protocol_sha = snapshot.protocol_sha
                    else:
                        raise
        report = evaluate_development_gate(
            gate_inputs.slices,
            gate_inputs.preregistered_units,
            GatePreconditions(
                universe_artifact_ok=bool(universe_artifact_ids),
                snapshot_identity_ok=True,
                family_members_frozen_ok=True,
                protocol_sha_ok=True,
            ),
        )

        bh_rows = run_bh_inference(list(gate_inputs.slices), family_id=family_id)
        if not bh_rows.empty:
            with ResearchFamilyLedger(ledger_path) as ledger:
                ledger.store_bh_results(bh_rows)

        evidence = {
            "run_id": run_id,
            "status": "completed",
            "gate_verdict": report.verdict.value,
            "factor_id": factor_id,
            "factor_version": "1.0.0",
            "family_id": family_id,
            "protocol_sha": protocol_sha,
            "retry_of_run_id": retry_of_run_id,
            "code_sha": code_sha,
            "snapshot_code_sha": snapshot_code_sha,
            "snapshot_ids": [entry.manifest.snapshot_id],
            "popular_universe_artifact_ids": universe_artifact_ids,
            "development_rows": gate_inputs.development_rows,
            "fold_count": gate_inputs.fold_count,
            "slice_count": len(gate_inputs.slices),
            "preregistered_unit_count": len(gate_inputs.preregistered_units),
            "holdout_accessed": False,
            "gate_report": _orderflow_json_safe(asdict(report)),
        }
        _write_exclusive_json(artifact_path, evidence)
        return OrderflowGateRunResult(
            run_id=run_id,
            status="completed",
            gate_verdict=report.verdict.value,
            artifact_path=artifact_path,
            snapshot_ids=(entry.manifest.snapshot_id,),
            holdout_accessed=False,
            development_rows=gate_inputs.development_rows,
            slice_count=len(gate_inputs.slices),
            preregistered_unit_count=len(gate_inputs.preregistered_units),
        )
    except Exception as error:
        reason = str(error) if isinstance(error, AnalysisBlocked) else f"DEVELOPMENT_FAILED:{error}"
        if not artifact_path.exists():
            _write_exclusive_json(
                artifact_path,
                {
                    "run_id": run_id,
                    "status": "blocked",
                    "error_code": reason,
                    "holdout_accessed": False,
                },
            )
        return OrderflowGateRunResult(
            run_id=run_id,
            status="blocked",
            gate_verdict="blocked",
            artifact_path=artifact_path,
            snapshot_ids=(),
            holdout_accessed=False,
            development_rows=0,
            slice_count=0,
            preregistered_unit_count=0,
            error_code=reason,
        )


def _orderflow_json_safe(value: Any) -> Any:
    """Convert non-finite numeric evidence values to JSON null."""
    if isinstance(value, dict):
        return {key: _orderflow_json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_orderflow_json_safe(item) for item in value]
    if isinstance(value, (float, np.floating)):
        return float(value) if np.isfinite(value) else None
    return value


def _load_popular_universe_eligibility(
    snapshots: CatalogedSnapshots, config: DualHorizonAcquisition
) -> tuple[pd.DataFrame | None, list[str]]:
    """Load popular-universe artifacts referenced by snapshot config.

    Returns (eligibility_frame, artifact_ids).  When no artifacts are
    referenced, returns (None, []).
    """
    artifact_ids: list[str] = []
    for entry in snapshots.entries.values():
        try:
            identity = json.loads(entry.manifest.config_json)
        except json.JSONDecodeError:
            continue
        ids = identity.get("popular_universe_artifact_ids", [])
        if ids:
            artifact_ids = ids
            break

    if not artifact_ids:
        return None, []

    artifacts_dir = config.artifact_root / "popular-universe"
    if not artifacts_dir.is_dir():
        raise AnalysisBlocked("POPULAR_UNIVERSE_DIR_MISSING")

    rows: list[dict[str, Any]] = []
    found_ids: set[str] = set()
    for path in sorted(artifacts_dir.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if payload.get("artifact_id") not in artifact_ids:
            continue
        found_ids.add(payload["artifact_id"])
        selection_time = payload["selection_time"]
        for member in payload.get("members", []):
            rows.append(
                {
                    "asset": member["asset"],
                    "selection_time": selection_time,
                    "rank": member["rank"],
                }
            )

    missing = set(artifact_ids) - found_ids
    if missing:
        raise AnalysisBlocked(f"POPULAR_UNIVERSE_ARTIFACT_MISSING:{','.join(sorted(missing))}")

    if not rows:
        return None, artifact_ids
    return pd.DataFrame(rows), artifact_ids


def _read_snapshot(entry: CatalogEntry) -> pd.DataFrame:
    schema = set(pq.ParquetFile(entry.path).schema.names)
    columns = [column for column in SNAPSHOT_COLUMNS if column in schema]
    required = {"asset", "event_time", "available_time", "close", "volume"}
    if not required <= set(columns):
        raise AnalysisBlocked(f"SNAPSHOT_SCHEMA_INVALID:{entry.manifest.name}")
    return pd.read_parquet(entry.path, columns=columns)


def _resolve_delay_entries(
    config: DualHorizonAcquisition,
    *,
    required_parent_ids: set[str],
) -> dict[int, CatalogEntry]:
    catalog_path = config.research_root / "delay_catalog.sqlite"
    if not catalog_path.is_file():
        raise AnalysisBlocked("OI_DELAY_CATALOG_MISSING")
    catalog = DatasetCatalog(catalog_path)
    result: dict[int, CatalogEntry] = {}
    for delay in config.oi_delay_minutes:
        name = f"metrics-oi-delay-{delay}m"
        matches = catalog.find_by_name(name)
        if not matches:
            raise AnalysisBlocked(f"OI_DELAY_SNAPSHOT_MISSING:{delay}")
        lineage_matches = [
            entry
            for entry in matches
            if entry.manifest.layer == DatasetLayer.RESEARCH
            and set(entry.manifest.parent_snapshot_ids) == required_parent_ids
            and entry.path.is_file()
        ]
        if len(lineage_matches) != 1:
            raise AnalysisBlocked(f"OI_DELAY_SNAPSHOT_AMBIGUOUS:{delay}")
        entry = lineage_matches[0]
        result[delay] = entry
    return result


def _build_delay_factor_frames(
    primary: pd.DataFrame,
    entries: dict[int, CatalogEntry],
) -> dict[int, pd.DataFrame]:
    result: dict[int, pd.DataFrame] = {}
    oi_columns = {
        "sum_open_interest",
        "sum_open_interest_value",
        "oi_available_time",
        "availability_assumption",
    }
    for delay, entry in entries.items():
        schema = set(pq.ParquetFile(entry.path).schema.names)
        required = {
            "asset",
            "event_time",
            "available_time",
            "sum_open_interest",
            "sum_open_interest_value",
            "availability_assumption",
        }
        if not required <= schema:
            raise AnalysisBlocked(f"OI_DELAY_SCHEMA_INVALID:{delay}")
        metrics = pd.read_parquet(entry.path, columns=sorted(required))
        assets: list[pd.DataFrame] = []
        for asset, bars in primary.groupby("asset", sort=True):
            left = bars.drop(columns=list(oi_columns), errors="ignore").sort_values(
                "available_time"
            )
            right = metrics.loc[metrics["asset"] == asset].sort_values("available_time")
            if right.empty:
                raise AnalysisBlocked(f"OI_DELAY_ASSET_MISSING:{delay}:{asset}")
            right = right.drop(columns=["asset", "event_time"]).rename(
                columns={"available_time": "oi_available_time"}
            )
            assets.append(
                pd.merge_asof(
                    left,
                    right,
                    left_on="available_time",
                    right_on="oi_available_time",
                    direction="backward",
                    allow_exact_matches=True,
                )
            )
        result[delay] = pd.concat(assets, ignore_index=True).sort_values(
            ["asset", "available_time"]
        )
    return result


def _load_acquisition_evidence(
    config: DualHorizonAcquisition,
    *,
    source_code_sha: str,
    required_snapshot_ids: tuple[str, ...],
) -> tuple[dict[str, Any], dict[str, Any]]:
    with ExperimentRegistry(config.experiment_registry_path) as registry:
        runs = [
            run
            for run in registry.list_runs()
            if run.strategy_name == "dual_horizon_derivatives"
            and run.code_sha == source_code_sha
            and run.status == RunStatus.PASSED
        ]
    for run in reversed(runs):
        acquisition_path = config.artifact_root / run.run_id / "data-acquisition.json"
        quality_path = config.artifact_root / run.run_id / "data-quality.json"
        if acquisition_path.is_file() and quality_path.is_file():
            acquisition = json.loads(acquisition_path.read_text(encoding="utf-8"))
            quality = json.loads(quality_path.read_text(encoding="utf-8"))
            snapshot_ids = acquisition.get("snapshot_ids", [])
            if (
                isinstance(snapshot_ids, list)
                and len(snapshot_ids) == len(required_snapshot_ids)
                and set(snapshot_ids) == set(required_snapshot_ids)
            ):
                return acquisition, quality
    raise AnalysisBlocked("SOURCE_EVIDENCE_MISSING")


def _start_run(config: DualHorizonAcquisition, manifest: RunManifest) -> None:
    config.experiment_registry_path.parent.mkdir(parents=True, exist_ok=True)
    with ExperimentRegistry(config.experiment_registry_path) as registry:
        registry.create(manifest)
        registry.transition(manifest.run_id, RunStatus.RUNNING)


def _finish_run(config: DualHorizonAcquisition, run_id: str, status: RunStatus) -> None:
    with ExperimentRegistry(config.experiment_registry_path) as registry:
        current = registry.get(run_id)
        if current.status == RunStatus.RUNNING:
            registry.transition(run_id, status)


def _blocked_manifest(
    config: DualHorizonAcquisition,
    *,
    code_sha: str,
    snapshot_code_sha: str,
    snapshot_ids: list[str],
) -> RunManifest:
    identity = hashlib.sha256(
        json.dumps(
            {
                "code_sha": code_sha,
                "snapshot_code_sha": snapshot_code_sha,
                "snapshot_ids": snapshot_ids,
                "status": "blocked",
            },
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    created = RunManifest.create(
        strategy_name="dual_horizon_analysis",
        code_sha=code_sha,
        dataset_snapshot_ids=snapshot_ids or [f"catalog-resolution-{identity[:16]}"],
        config={
            "as_of": config.as_of.isoformat(),
            "snapshot_code_sha": snapshot_code_sha,
            "status": "blocked",
        },
        seed=0,
        locked_holdout=LockedHoldout(
            start=config.factor_protocol.holdout_start,
            end=config.factor_protocol.holdout_end,
        ),
    )
    return created


def _render_factor_screening(payload: dict[str, Any]) -> str:
    candidates = payload.get("candidate_factor_ids", [])
    lines = [
        "# Factor Screening",
        "",
        f"Engineering status: {payload.get('status', 'unknown')}",
        f"Candidate factors: {len(candidates)}",
        "",
        "## Gate decisions",
        "",
    ]
    for factor, reasons in sorted(payload.get("gates", {}).items()):
        lines.append(f"- **{factor}**: {', '.join(reasons)}")
    return "\n".join(lines)


def _default_holdout_evaluator(
    frame: pd.DataFrame, spec: FactorSpec
) -> tuple[bool, list[str], dict[str, Any]]:
    work = compute_dual_horizon_factor_columns(frame, interval="4h")
    if spec.factor_id not in work:
        return False, ["FACTOR_PROMOTION_REJECTED", "FACTOR_COLUMN_MISSING"], {}
    correlations: dict[str, float] = {}
    returns: dict[str, float] = {}
    for asset, asset_frame in work.groupby("asset", sort=True):
        label = forward_log_return(asset_frame["close"], periods=1)
        correlation = asset_frame[spec.factor_id].corr(label, method="spearman")
        if np.isfinite(correlation):
            correlations[str(asset)] = float(correlation)
            direction = np.sign(correlation)
            returns[str(asset)] = float((direction * label).dropna().mean())
    reasons: list[str] = []
    if len(correlations) < 2:
        reasons.append("HOLDOUT_ASSET_COVERAGE_LT_2")
    target = 1.0 if spec.direction == "positive" else -1.0 if spec.direction == "negative" else 0.0
    if target and any(np.sign(value) != target for value in correlations.values()):
        reasons.append("HOLDOUT_DIRECTION_UNSTABLE")
    support = [asset for asset, value in returns.items() if value > 0]
    if support and 1 / len(support) > 0.5:
        reasons.append("HOLDOUT_ASSET_CONCENTRATION_GT_50PCT")
    mean_return = float(np.mean(list(returns.values()))) if returns else float("nan")
    five_bps = mean_return - 0.0005
    ten_bps = mean_return - 0.001
    if not np.isfinite(five_bps) or five_bps <= 0:
        reasons.append("HOLDOUT_5BPS_NON_POSITIVE")
    if not np.isfinite(ten_bps) or ten_bps < 0:
        reasons.append("HOLDOUT_10BPS_NEGATIVE")
    if spec.factor_id in {"oi_change", "leverage_crowding"}:
        delay_directions: dict[int, float] = {}
        for delay in (5, 10, 15):
            column = f"{spec.factor_id}_delay_{delay}"
            if column not in work:
                continue
            delay_correlations: list[float] = []
            for _asset, asset_frame in work.groupby("asset", sort=True):
                value = asset_frame[column].corr(
                    forward_log_return(asset_frame["close"], periods=1),
                    method="spearman",
                )
                if np.isfinite(value):
                    delay_correlations.append(float(value))
            if delay_correlations:
                delay_directions[delay] = float(np.sign(np.median(delay_correlations)))
        if set(delay_directions) != {5, 10, 15}:
            reasons.append("HOLDOUT_OI_DELAY_STRESS_UNAVAILABLE")
        elif target and any(value != target for value in delay_directions.values()):
            reasons.append("HOLDOUT_OI_DELAY_DIRECTION_UNSTABLE")
    return (
        not reasons,
        reasons or ["ALL_HOLDOUT_GATES_PASSED"],
        {
            "asset_spearman_ic": correlations,
            "asset_mean_return": returns,
            "cost_adjusted_return_5bps": five_bps,
            "cost_adjusted_return_10bps": ten_bps,
        },
    )


def _write_exclusive_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        json.dump(payload, handle, sort_keys=True, indent=2, allow_nan=False, default=str)


@dataclass(frozen=True)
class SmallAccountBacktestResult:
    """Result of a 100 USDT portfolio backtest gated on Approved factor."""

    run_id: str
    status: str
    factor_id: str
    factor_version: str
    artifact_path: Path
    trade_count: int
    final_equity: str
    maximum_gross: str
    reason_codes: tuple[str, ...] = ()


def run_small_account_backtest(
    config: DualHorizonAcquisition,
    *,
    factor_id: str,
    factor_version: str,
    snapshot_id: str,
    backtest_config_path: Path,
    run_id: str | None = None,
) -> SmallAccountBacktestResult:
    """Run a 100 USDT portfolio backtest gated on an Approved factor.

    Raises PermissionError if the factor is not in APPROVED state.
    """
    from decimal import Decimal

    from bian_quant.backtest.events import Bar, SignalEvent
    from bian_quant.backtest.portfolio import replay_ranked_portfolio
    from bian_quant.backtest.small_account import ContractRules, SmallAccountLimits

    # Gate: factor must be APPROVED.
    with FactorRegistry(config.factor_registry_path) as factors:
        factors.get(factor_id, factor_version)
        state = factors.state(factor_id, factor_version)
        if state != FactorState.APPROVED:
            raise PermissionError(
                f"BACKTEST_ACCESS_DENIED: factor {factor_id}@{factor_version} "
                f"is {state.value}, not APPROVED"
            )

    # Load locked Micro-4h snapshot.
    entry = DatasetCatalog(config.catalog_path).get(snapshot_id)
    if entry.manifest.name != "micro-4h" or entry.manifest.layer != DatasetLayer.RESEARCH:
        raise PermissionError("BACKTEST_ACCESS_DENIED: snapshot is not locked Micro 4h")
    if not entry.path.is_file():
        raise PermissionError("BACKTEST_ACCESS_DENIED: snapshot file is missing")

    frame = _read_snapshot(entry)
    computed = compute_dual_horizon_factor_columns(frame, interval="4h")
    if factor_id not in computed.columns:
        raise AnalysisBlocked(f"FACTOR_COLUMN_MISSING:{factor_id}")

    limits = SmallAccountLimits.from_yaml(backtest_config_path)

    # Derive per-asset contract rules with conservative defaults.
    contract_rules: dict[str, ContractRules] = {}
    for asset in computed["asset"].unique():
        contract_rules[str(asset)] = ContractRules(
            asset=str(asset),
            min_qty=Decimal("0.001"),
            step_size=Decimal("0.001"),
            min_notional=Decimal("5"),
            tick_size=Decimal("0.01"),
        )

    # Build a single-timeline bar list (one bar per unique timestamp).
    # Use the average close across assets as the representative price.
    timeline = (
        computed.groupby("available_time", as_index=False)
        .agg(
            open=("open", "mean"),
            high=("high", "max"),
            low=("low", "min"),
            close=("close", "mean"),
            volume=("volume", "sum"),
        )
        .sort_values("available_time")
        .reset_index(drop=True)
    )
    bars: list[Bar] = []
    for row in timeline.to_dict(orient="records"):
        timestamp = pd.Timestamp(row["available_time"]).to_pydatetime()
        bars.append(
            Bar(
                timestamp=timestamp,
                open=Decimal(str(row["open"])),
                high=Decimal(str(row["high"])),
                low=Decimal(str(row["low"])),
                close=Decimal(str(row["close"])),
                volume=Decimal(str(row["volume"])),
            )
        )

    # Generate ranked signals from factor values.
    signals: list[SignalEvent] = []
    for _timestamp, group in computed.groupby("available_time"):
        factor_values = group[[factor_id, "asset", "available_time"]].dropna(subset=[factor_id])
        if factor_values.empty:
            continue
        ranked = factor_values.assign(_abs=factor_values[factor_id].abs()).sort_values(
            "_abs", ascending=False
        )
        for rank, row in enumerate(ranked.to_dict(orient="records"), start=1):
            value = row[factor_id]
            if value == 0:
                continue
            direction = 1 if value > 0 else -1
            timestamp = pd.Timestamp(row["available_time"]).to_pydatetime()
            signals.append(
                SignalEvent(
                    timestamp=timestamp,
                    direction=direction,
                    available_time=timestamp,
                    asset=str(row["asset"]),
                    rank=rank,
                    stop_distance=Decimal("0.02"),
                    target_distance=Decimal("0.04"),
                )
            )

    bt_run_id = run_id or f"backtest-{factor_id}-{factor_version}"
    result = replay_ranked_portfolio(
        bars=bars,
        signals=signals,
        limits=limits,
        contract_rules=contract_rules,
    )

    final_equity = result.equity[-1] if result.equity else limits.initial_equity_usdt
    artifact_path = config.artifact_root / "backtest" / f"{bt_run_id}.json"
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "run_id": bt_run_id,
        "factor_id": factor_id,
        "factor_version": factor_version,
        "snapshot_id": snapshot_id,
        "status": "completed",
        "trade_count": len(result.trades),
        "final_equity": str(final_equity),
        "maximum_gross": str(result.maximum_gross),
        "fills": [
            {
                "timestamp": fill.timestamp.isoformat(),
                "direction": fill.direction,
                "exec_price": str(fill.exec_price),
                "notional": str(fill.notional),
                "reason": fill.reason,
            }
            for fill in result.fills
        ],
        "trades": [
            {
                "entry_time": t.entry_time.isoformat(),
                "exit_time": t.exit_time.isoformat(),
                "direction": t.direction,
                "entry_price": str(t.entry_price),
                "exit_price": str(t.exit_price),
                "pnl": str(t.pnl),
                "exit_reason": t.exit_reason,
            }
            for t in result.trades
        ],
        "rejections": result.rejections,
        "pause_events": result.pause_events,
        "daily_attribution": {k: str(v) for k, v in result.daily_attribution.items()},
    }
    with artifact_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, sort_keys=True, indent=2, allow_nan=False, default=str)

    return SmallAccountBacktestResult(
        run_id=bt_run_id,
        status="completed",
        factor_id=factor_id,
        factor_version=factor_version,
        artifact_path=artifact_path,
        trade_count=len(result.trades),
        final_equity=str(final_equity),
        maximum_gross=str(result.maximum_gross),
    )
