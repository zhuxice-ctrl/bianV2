"""Aggregator that builds a ``ResearchTerminalResponse`` from real artifacts.

Reads the latest ``dual_horizon_derivatives`` run from the experiment registry
and assembles the contract response from its on-disk artifacts:

* ``data-acquisition.json``  -> planned_objects, manifest sha, pre-listing
  exclusions, snapshot ids, acquisition failures (blockers), partial
  availability exclusions and impact.
* ``data-quality.json``      -> coverage reports, blocked periods.
* ``popular-universe/*.json`` -> latest members + daily counts.
* dataset catalog            -> the four locked research snapshots.

All artifact reads are defensive: a missing/unreadable file or an unexpected
key degrades gracefully to a contract-conformant default rather than raising,
so the endpoint always returns a valid ``ResearchTerminalResponse``.  Parsed
JSON is cached by file mtime to avoid re-reading multi-megabyte evidence files
on every request.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from bian_quant.backtest.confidence_allocation import allocate_confidence_cap
from bian_quant.backtest.market_cycle_comparison import (
    build_comparison_from_artifacts,
    comparison_payload,
)
from bian_quant.data.acquisition import DualHorizonAcquisition
from bian_quant.data.catalog import DatasetCatalog
from bian_quant.data.contracts import DatasetLayer
from bian_quant.experiments.models import RunStatus
from bian_quant.experiments.registry import ExperimentRegistry
from bian_quant.regimes.market_cycle import classify_market_cycle, load_popular_universe_records
from bian_quant.reporting.research_protocol import (
    Allocation,
    BacktestComparison,
    BacktestMetrics,
    Blocker,
    CoverageRow,
    CoverageStatus,
    DailyCount,
    DatasetName,
    Exclusion,
    ExclusionReason,
    Granularity,
    Kpis,
    MarketCycle,
    PartialAvailabilityExclusion,
    PartialAvailabilityImpact,
    PartialExclusionReason,
    PopularMember,
    PopularUniverse,
    ResearchTerminalResponse,
    RunInfo,
    Snapshot,
    SnapshotName,
    TerminalState,
)

DERIVATIVES_STRATEGY = "dual_horizon_derivatives"
_REQUIRED_SNAPSHOT_NAMES = ("macro-1d", "macro-4h", "micro-1h", "micro-4h")

_ZERO_IMPACT = PartialAvailabilityImpact(
    affected_assets=[],
    affected_periods=0,
    affected_selection_days=0,
)

_ZERO_METRICS = BacktestMetrics(
    final_equity=100.0,
    total_return=0.0,
    annualized_volatility=0.0,
    max_drawdown=0.0,
    sharpe_like=0.0,
    trade_count=0,
)

_ZERO_ALLOCATION = Allocation(
    total_cap_usdt=0.0,
    per_asset_caps_usdt={"BTCUSDT": 0.0, "ETHUSDT": 0.0, "BNBUSDT": 0.0},
    selected_assets=[],
    reason="INSUFFICIENT_EVIDENCE",
)

# Module-level mtime cache for parsed artifact JSON: {path_str: (mtime, data)}
_json_cache: dict[str, tuple[float, dict[str, Any]]] = {}


def build_research_terminal_response(
    config_path: Path,
    *,
    repo_root: Path,
) -> ResearchTerminalResponse:
    """Build the contract response for the latest derivatives run.

    ``config_path`` is the popular-universe acquisition YAML (relative or
    absolute); relative paths inside it are resolved against ``repo_root``.
    """
    config = DualHorizonAcquisition.from_yaml(config_path)
    artifact_root = _resolve(config.artifact_root, repo_root)
    registry_path = _resolve(config.experiment_registry_path, repo_root)
    catalog_path = _resolve(config.catalog_path, repo_root)
    as_of_iso = config.as_of.isoformat()

    run = _latest_derivatives_run(registry_path)

    if run is None:
        return _empty_response(as_of_iso)

    run_id = run.run_id
    run_dir = artifact_root / run_id
    artifact_path_rel = _relative_to_repo(run_dir, repo_root)

    acquisition = _load_json_cached(run_dir / "data-acquisition.json")
    quality = _load_json_cached(run_dir / "data-quality.json")

    state = _run_status_to_state(run.status)

    # --- run block ---------------------------------------------------------
    pre_listing_exclusions_raw = acquisition.get("pre_listing_exclusions") or []
    planned_objects = int(acquisition.get("planned_objects") or 0)
    manifest_sha = acquisition.get("availability_manifest_sha256")
    publish_start = acquisition.get("popular_universe_start")
    if publish_start is None and config.popular_universe_start is not None:
        publish_start = config.popular_universe_start.isoformat()
    warmup_start = acquisition.get("popular_universe_warmup_start")
    if warmup_start is None and config.popular_universe_start is not None:
        warmup_start = config.micro_start.isoformat()
    warmup_end = acquisition.get("popular_universe_warmup_end")
    if warmup_end is None and config.popular_universe_start is not None:
        warmup_end = _day_before(config.popular_universe_start)
    run_info = RunInfo(
        id=run_id,
        status=state,
        as_of=as_of_iso,
        planned_objects=planned_objects,
        availability_manifest_sha256=manifest_sha,
        pre_listing_exclusion_count=len(pre_listing_exclusions_raw),
        popular_universe_start=publish_start,
        popular_universe_warmup_start=warmup_start,
        popular_universe_warmup_end=warmup_end,
        artifact_path=artifact_path_rel,
    )

    # --- popular universe --------------------------------------------------
    popular_universe = _build_popular_universe(artifact_root)

    # --- snapshots ---------------------------------------------------------
    snapshots = _build_snapshots(acquisition, catalog_path)

    # --- coverage ----------------------------------------------------------
    coverage = _build_coverage(quality, config.assets)

    # --- blockers ----------------------------------------------------------
    blockers = _build_blockers(acquisition)

    # --- pre-listing exclusions -------------------------------------------
    exclusions = _build_exclusions(pre_listing_exclusions_raw)

    # --- partial availability ---------------------------------------------
    partial_exclusions = _build_partial_exclusions(
        acquisition.get("partial_availability_exclusions") or []
    )
    partial_impact = _build_partial_impact(
        acquisition.get("partial_availability_impact")
    )

    # --- market cycle / allocation / 100U comparison -----------------------
    cycle, allocation, comparison = _build_cycle_allocation_backtest(
        artifact_root,
        raw_root=_resolve(config.raw_root, repo_root),
    )

    # --- kpis --------------------------------------------------------------
    popular_member_count = (
        len(popular_universe.latest_members) if popular_universe.latest_members else None
    )
    blocked_period_count = len(quality.get("blocked_periods") or [])
    temporary_blocker_count = sum(1 for b in blockers if b.temporary)
    kpis = Kpis(
        popular_member_count=popular_member_count,
        published_snapshot_count=len(snapshots),
        blocked_period_count=blocked_period_count,
        temporary_blocker_count=temporary_blocker_count,
    )

    return ResearchTerminalResponse(
        schema_version="research-terminal-v1",
        state=state,
        generated_at=datetime.now(UTC).isoformat(),
        run=run_info,
        kpis=kpis,
        popular_universe=popular_universe,
        coverage=coverage,
        blockers=blockers,
        pre_listing_exclusions=exclusions,
        partial_availability_exclusions=partial_exclusions,
        partial_availability_impact=partial_impact,
        market_cycle=cycle,
        allocation=allocation,
        backtest_comparison=comparison,
        snapshots=snapshots,
    )


# ---------------------------------------------------------------------------
# Run discovery
# ---------------------------------------------------------------------------


def _latest_derivatives_run(registry_path: Path) -> Any | None:
    """Return the most recent ``dual_horizon_derivatives`` RunManifest, or None."""
    if not registry_path.is_file():
        return None
    try:
        with ExperimentRegistry(registry_path) as registry:
            runs = [
                run
                for run in registry.list_runs()
                if run.strategy_name == DERIVATIVES_STRATEGY
            ]
    except Exception:
        return None
    if not runs:
        return None
    return max(runs, key=lambda r: (r.created_at, r.run_id))


def _run_status_to_state(status: RunStatus) -> TerminalState:
    if status == RunStatus.PASSED:
        return TerminalState.PASSED
    if status == RunStatus.BLOCKED:
        return TerminalState.BLOCKED
    return TerminalState.BLOCKED


def _empty_response(as_of_iso: str) -> ResearchTerminalResponse:
    return ResearchTerminalResponse(
        schema_version="research-terminal-v1",
        state=TerminalState.EMPTY,
        generated_at=datetime.now(UTC).isoformat(),
        run=RunInfo(
            id=None,
            status=TerminalState.EMPTY,
            as_of=as_of_iso,
            planned_objects=0,
            availability_manifest_sha256=None,
            pre_listing_exclusion_count=0,
            popular_universe_start=None,
            popular_universe_warmup_start=None,
            popular_universe_warmup_end=None,
            artifact_path=None,
        ),
        kpis=Kpis(
            popular_member_count=None,
            published_snapshot_count=0,
            blocked_period_count=0,
            temporary_blocker_count=0,
        ),
        popular_universe=PopularUniverse(
            latest_date=None, latest_members=[], daily_counts=[]
        ),
        coverage=[],
        blockers=[],
        pre_listing_exclusions=[],
        partial_availability_exclusions=[],
        partial_availability_impact=_ZERO_IMPACT,
        market_cycle=MarketCycle(
            label="insufficient_evidence",
            confidence=0.0,
            probabilities={"bull": 0.0, "neutral": 0.0, "risk_off": 0.0},
            decision_time=None,
            sample_count=0,
            evidence_sha256=None,
            status="missing",
        ),
        allocation=_ZERO_ALLOCATION,
        backtest_comparison=BacktestComparison(
            status="missing",
            baseline=_ZERO_METRICS,
            confidence_weighted=_ZERO_METRICS,
            artifact_sha256=None,
        ),
        snapshots=[],
    )


# ---------------------------------------------------------------------------
# Popular universe
# ---------------------------------------------------------------------------


def _build_popular_universe(artifact_root: Path) -> PopularUniverse:
    artifacts_dir = artifact_root / "popular-universe"
    if not artifacts_dir.is_dir():
        return PopularUniverse(latest_date=None, latest_members=[], daily_counts=[])
    records: list[dict[str, Any]] = []
    for path in sorted(artifacts_dir.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        selection_time = payload.get("selection_time")
        members = payload.get("members") or []
        if not selection_time:
            continue
        records.append({"selection_time": selection_time, "members": members})
    if not records:
        return PopularUniverse(latest_date=None, latest_members=[], daily_counts=[])
    records.sort(key=lambda r: r["selection_time"])
    latest = records[-1]
    latest_members = _map_members(latest["members"])
    daily_counts = [
        DailyCount(date=r["selection_time"][:10], member_count=len(r["members"]))
        for r in records
    ]
    return PopularUniverse(
        latest_date=latest["selection_time"][:10],
        latest_members=latest_members,
        daily_counts=daily_counts,
    )


def _map_members(members: list[dict[str, Any]]) -> list[PopularMember]:
    """Map artifact members to contract PopularMember, recomputing ranks."""
    quote_volume_ranks = _descending_ranks(
        {str(m["asset"]): float(m["median_quote_volume"]) for m in members}
    )
    oi_ranks = _descending_ranks(
        {str(m["asset"]): float(m["median_oi_value"]) for m in members}
    )
    result: list[PopularMember] = []
    for m in members:
        asset = str(m["asset"])
        qv_rank = quote_volume_ranks.get(asset)
        oi_rank = oi_ranks.get(asset)
        composite = (qv_rank + oi_rank) if (qv_rank is not None and oi_rank is not None) else None
        result.append(
            PopularMember(
                rank=int(m["rank"]),
                asset=asset,
                composite_score=composite,
                quote_volume_rank=qv_rank,
                open_interest_rank=oi_rank,
            )
        )
    return result


def _descending_ranks(values: dict[str, float]) -> dict[str, int]:
    """Competition ranks with the largest value ranked first (1-based)."""
    ranks: dict[str, int] = {}
    previous: float | None = None
    current_rank = 0
    for position, (asset, value) in enumerate(
        sorted(values.items(), key=lambda item: (-item[1], item[0])), start=1
    ):
        if previous is None or value != previous:
            current_rank = position
            previous = value
        ranks[asset] = current_rank
    return ranks


# ---------------------------------------------------------------------------
# Snapshots
# ---------------------------------------------------------------------------


def _build_snapshots(acquisition: dict[str, Any], catalog_path: Path) -> list[Snapshot]:
    snapshot_ids = acquisition.get("snapshot_ids") or []
    if not snapshot_ids or not catalog_path.is_file():
        return []
    try:
        catalog = DatasetCatalog(catalog_path)
    except Exception:
        return []
    snapshots: list[Snapshot] = []
    for snapshot_id in snapshot_ids:
        try:
            entry = catalog.get(str(snapshot_id))
        except Exception:
            continue
        manifest = entry.manifest
        if manifest.layer != DatasetLayer.RESEARCH:
            continue
        try:
            name = SnapshotName(manifest.name)
        except ValueError:
            continue
        snapshots.append(
            Snapshot(
                name=name,
                id=manifest.snapshot_id,
                min_event_time=(
                    manifest.min_event_time.isoformat() if manifest.min_event_time else ""
                ),
                max_event_time=(
                    manifest.max_event_time.isoformat() if manifest.max_event_time else ""
                ),
            )
        )
    order = {name: i for i, name in enumerate(_REQUIRED_SNAPSHOT_NAMES)}
    snapshots.sort(key=lambda s: order.get(s.name.value, 99))
    return snapshots


# ---------------------------------------------------------------------------
# Coverage
# ---------------------------------------------------------------------------


def _build_coverage(quality: dict[str, Any], assets: tuple[str, ...]) -> list[CoverageRow]:
    reports = quality.get("coverage_reports") or []
    if not reports:
        return []
    by_asset_dataset: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for report in reports:
        asset = report.get("asset")
        dataset = report.get("dataset")
        if not asset or not dataset:
            continue
        by_asset_dataset.setdefault((str(asset), str(dataset)), []).append(report)

    present_assets = sorted({asset for (asset, _) in by_asset_dataset})
    rows: list[CoverageRow] = []
    for asset in present_assets:
        rows.append(
            CoverageRow(
                asset=asset,
                ohlcv=_dataset_status(by_asset_dataset.get((asset, "ohlcv"))),
                funding=_dataset_status(by_asset_dataset.get((asset, "funding"))),
                metrics_oi=_dataset_status(by_asset_dataset.get((asset, "metrics_oi"))),
            )
        )
    return rows


def _dataset_status(reports: list[dict[str, Any]] | None) -> CoverageStatus:
    if not reports:
        return CoverageStatus.UNAVAILABLE
    has_excluded = False
    for report in reports:
        for finding in report.get("findings") or []:
            if finding.get("severity") == "blocking":
                return CoverageStatus.BLOCKED
        if report.get("excluded_periods"):
            has_excluded = True
    return CoverageStatus.EXCLUDED if has_excluded else CoverageStatus.PASSED


# ---------------------------------------------------------------------------
# Blockers
# ---------------------------------------------------------------------------


def _build_blockers(acquisition: dict[str, Any]) -> list[Blocker]:
    results = acquisition.get("results") or []
    blockers: list[Blocker] = []
    for result in results:
        if result.get("status") != "failed":
            continue
        identity_key = str(result.get("identity_key") or "")
        dataset_str, asset, _interval, granularity, period_start = _parse_identity_key(identity_key)
        try:
            dataset = DatasetName(dataset_str) if dataset_str else None
        except ValueError:
            dataset = None
        period = _period_label(period_start, granularity)
        blockers.append(
            Blocker(
                identity_key=identity_key,
                asset=asset,
                dataset=dataset,
                period=period,
                error_code=str(result.get("error_code") or "UNKNOWN"),
                message=str(result.get("message") or ""),
                temporary=bool(result.get("temporary", False)),
            )
        )
    return blockers


# ---------------------------------------------------------------------------
# Pre-listing exclusions
# ---------------------------------------------------------------------------


def _build_exclusions(raw: list[dict[str, Any]]) -> list[Exclusion]:
    exclusions: list[Exclusion] = []
    for item in raw:
        try:
            exclusions.append(
                Exclusion(
                    identity_key=str(item["identity_key"]),
                    asset=str(item["asset"]),
                    dataset=DatasetName(item["dataset"]),
                    granularity=Granularity(item["granularity"]),
                    reason=ExclusionReason(item["reason"]),
                )
            )
        except (KeyError, ValueError, ValidationError):
            continue
    return exclusions


# ---------------------------------------------------------------------------
# Partial availability exclusions
# ---------------------------------------------------------------------------


def _build_partial_exclusions(raw: list[dict[str, Any]]) -> list[PartialAvailabilityExclusion]:
    exclusions: list[PartialAvailabilityExclusion] = []
    for item in raw:
        try:
            exclusions.append(
                PartialAvailabilityExclusion(
                    identity_key=str(item["identity_key"]),
                    asset=str(item["asset"]),
                    dataset=DatasetName(item["dataset"]),
                    granularity=Granularity(item["granularity"]),
                    period=str(item["period"]),
                    reason=PartialExclusionReason(item["reason"]),
                    error_code=str(item["error_code"]),
                    temporary=bool(item["temporary"]),
                )
            )
        except (KeyError, ValueError, ValidationError):
            continue
    return exclusions


def _build_partial_impact(raw: dict[str, Any] | None) -> PartialAvailabilityImpact:
    if not raw or not isinstance(raw, dict):
        return _ZERO_IMPACT
    try:
        return PartialAvailabilityImpact(
            affected_assets=[str(a) for a in raw.get("affected_assets", [])],
            affected_periods=int(raw.get("affected_periods", 0)),
            affected_selection_days=int(raw.get("affected_selection_days", 0)),
        )
    except (KeyError, ValueError, ValidationError):
        return _ZERO_IMPACT


# ---------------------------------------------------------------------------
# Market cycle / allocation / backtest
# ---------------------------------------------------------------------------


def _build_cycle_allocation_backtest(
    artifact_root: Path,
    *,
    raw_root: Path,
) -> tuple[MarketCycle, Allocation, BacktestComparison]:
    artifacts_dir = artifact_root / "popular-universe"
    try:
        records = load_popular_universe_records(artifacts_dir)
        state = classify_market_cycle(records)
        latest_weights = _latest_three_coin_weights(artifacts_dir)
        allocation_decision = allocate_confidence_cap(state, latest_weights)
        comparison = build_comparison_from_artifacts(artifacts_dir, raw_root=raw_root)
    except Exception:
        return (
            MarketCycle(
                label="insufficient_evidence",
                confidence=0.0,
                probabilities={"bull": 0.0, "neutral": 0.0, "risk_off": 0.0},
                decision_time=None,
                sample_count=0,
                evidence_sha256=None,
                status="error",
            ),
            _ZERO_ALLOCATION,
            BacktestComparison(
                status="error",
                baseline=_ZERO_METRICS,
                confidence_weighted=_ZERO_METRICS,
                artifact_sha256=None,
            ),
        )
    status = "ok" if state.sample_count >= 30 else "insufficient_evidence"
    cycle = MarketCycle(
        label=state.label.value,
        confidence=state.confidence,
        probabilities=state.probabilities,
        decision_time=state.decision_time.isoformat() if state.decision_time else None,
        sample_count=state.sample_count,
        evidence_sha256=state.evidence_sha256,
        status=status,
    )
    allocation = Allocation(
        total_cap_usdt=float(allocation_decision.total_cap_usdt),
        per_asset_caps_usdt={
            asset: float(value)
            for asset, value in allocation_decision.per_asset_caps_usdt.items()
        },
        selected_assets=list(allocation_decision.selected_assets),
        reason=allocation_decision.reason,
    )
    comparison_payload_data = comparison_payload(comparison)
    baseline_payload = comparison_payload_data["baseline"]
    weighted_payload = comparison_payload_data["confidence_weighted"]
    if not isinstance(baseline_payload, dict) or not isinstance(weighted_payload, dict):
        raise ValueError("invalid comparison payload")
    backtest = BacktestComparison(
        status="missing_returns" if comparison.baseline.trade_count == 0 else "ok",
        baseline=BacktestMetrics(**baseline_payload),
        confidence_weighted=BacktestMetrics(**weighted_payload),
        artifact_sha256=str(comparison_payload_data["artifact_sha256"]),
    )
    return cycle, allocation, backtest


def _latest_three_coin_weights(artifacts_dir: Path) -> dict[str, float]:
    if not artifacts_dir.is_dir():
        return {}
    files = sorted(artifacts_dir.glob("*.json"))
    if not files:
        return {}
    try:
        payload = json.loads(files[-1].read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    weights: dict[str, float] = {}
    for member in payload.get("members") or []:
        if not isinstance(member, dict):
            continue
        asset = str(member.get("asset"))
        if asset not in {"BTCUSDT", "ETHUSDT", "BNBUSDT"}:
            continue
        rank = int(member.get("rank") or 99)
        weights[asset] = max(0.0, 13.0 - float(rank))
    return weights


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_identity_key(
    identity_key: str,
) -> tuple[str, str | None, str | None, str | None, str | None]:
    """Split ``dataset|asset|interval|granularity|period_start``."""
    parts = identity_key.split("|")
    if len(parts) < 5:
        return (parts[0] if parts else "", None, None, None, None)
    return (parts[0], parts[1], parts[2], parts[3], parts[4])


def _period_label(period_start: str | None, granularity: str | None) -> str | None:
    if not period_start:
        return None
    return period_start[:7] if granularity == "monthly" else period_start[:10]


def _resolve(path: Path, repo_root: Path) -> Path:
    return path if path.is_absolute() else (repo_root / path).resolve()


def _relative_to_repo(path: Path, repo_root: Path) -> str:
    try:
        return str(path.resolve().relative_to(repo_root.resolve()))
    except ValueError:
        return str(path)


def _day_before(value: datetime) -> str:
    return (value.astimezone(UTC) - timedelta(days=1)).isoformat()


def _load_json_cached(path: Path) -> dict[str, Any]:
    """Load a JSON file with mtime-based caching; return {} on any failure."""
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return {}
    key = str(path)
    cached = _json_cache.get(key)
    if cached is not None and cached[0] == mtime:
        return cached[1]
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    _json_cache[key] = (mtime, data)
    return data
