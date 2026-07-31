# Funding Monthly-Tail Acquisition Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace nonexistent cutoff-month daily Funding requests with official delayed monthly archives, causally clip every canonical dataset to the locked evidence cutoff, and resume Plan 03.5 through real evidence and final gates.

**Architecture:** Keep the approved `as_of`, research windows, factor protocol, and archive-only provenance. The source plan includes the cutoff month's three Funding monthly ZIPs, classifies their pre-publication 404s as a temporary resumable state, projects validated source frames through a generic event/availability cutoff, and writes amended canonical data below a deterministic source-plan namespace so prior blocked evidence remains immutable.

**Tech Stack:** Python 3.11, Pydantic, pandas, PyArrow/Parquet, SQLite, Typer, urllib, pytest, uv, Binance public USD-M archives.

---

## Executor contract

1. Work only in `F:\bianV2-research-implementation` on
   `codex/research-platform-implementation`.
2. Verify `f212221` is an ancestor, the branch is not `main`, and the worktree
   is clean before Task 1:

```powershell
git branch --show-current
git merge-base --is-ancestor f212221 HEAD
git status --short
```

3. Read the approved amendment before editing:
   `docs/superpowers/specs/2026-07-31-funding-monthly-tail-design.md`.
4. Preserve every existing run, raw object, canonical partition, catalog,
   registry, and artifact under `var/`. Never delete runtime evidence to make a
   test or rerun pass.
5. Network access remains limited to objects emitted by
   `configs/experiments/dual_horizon_derivatives.yaml`; keep `max_workers <= 4`.
6. Use TDD and one focused commit per task. Do not push until Task 7.
7. Do not start Plan 04.

## File map

- `configs/experiments/dual_horizon_derivatives.yaml`: locked strategy identity.
- `src/bian_quant/data/acquisition.py`: configuration and exact source plan.
- `src/bian_quant/data/acquisition_failures.py`: stable acquisition-failure
  classification, including temporary cutoff-month Funding 404s.
- `src/bian_quant/data/evidence_cutoff.py`: generic event/availability cutoff
  projection, cutoff evidence, and plan-namespaced canonical paths.
- `src/bian_quant/data/dual_horizon.py`: orchestration only; integrates the
  planner, classifier, cutoff projection, quality gates, catalog, and artifacts.
- `src/bian_quant/data/derivatives_quality.py`: causal coverage denominators.
- `tests/unit/data/test_source_plan.py`: locked source counts and identities.
- `tests/unit/data/test_acquisition_failures.py`: stable error semantics.
- `tests/unit/data/test_evidence_cutoff.py`: cutoff and immutability invariants.
- `tests/unit/data/test_dual_horizon_real_archives.py`: real timestamp/cutoff
  regressions.
- `tests/integration/data/test_dual_horizon_pipeline.py`: offline full pipeline,
  resumability, artifacts, and snapshots.
- `tests/unit/test_cli_dual_horizon.py`: network-free dry-run contract.
- `docs/implementation-notes.md`: migration and verified results.
- `docs/evidence/dual-horizon-*.json` and `.md`: bounded real-run evidence only.

---

### Task 1: Lock the monthly Funding-tail source plan

**Files:**
- Modify: `configs/experiments/dual_horizon_derivatives.yaml`
- Modify: `src/bian_quant/data/acquisition.py`
- Modify: `tests/unit/data/test_acquisition.py`
- Modify: `tests/unit/data/test_source_plan.py`
- Modify: `tests/unit/test_cli_dual_horizon.py`

- [ ] **Step 1: Write failing configuration and exact-count tests**

Add to `tests/unit/data/test_acquisition.py`:

```python
def test_funding_tail_strategy_is_locked() -> None:
    config = DualHorizonAcquisition.from_yaml(
        Path("configs/experiments/dual_horizon_derivatives.yaml")
    )
    assert config.funding_tail_strategy == "monthly_archive_after_period_close"
```

Replace the old `3192` and all-daily partial-month assertions in
`tests/unit/data/test_source_plan.py` with:

```python
def test_locked_plan_uses_monthly_funding_tail() -> None:
    config = DualHorizonAcquisition.from_yaml(CONFIG)
    plan = build_source_plan(config)
    funding = [item for item in plan if item.dataset == SourceDataset.FUNDING]
    cutoff_month = [
        item
        for item in funding
        if (item.period_start.year, item.period_start.month) == (2026, 7)
    ]

    assert len(plan) == 3117
    assert len(funding) == 183
    assert all(item.granularity == SourceGranularity.MONTHLY for item in funding)
    assert {item.asset for item in cutoff_month} == {
        "BTCUSDT",
        "ETHUSDT",
        "BNBUSDT",
    }
    assert len(cutoff_month) == 3
    assert not [
        item
        for item in plan
        if item.dataset == SourceDataset.FUNDING
        and item.granularity == SourceGranularity.DAILY
    ]


def test_locked_plan_counts_are_exact() -> None:
    payload = source_plan_payload(DualHorizonAcquisition.from_yaml(CONFIG))
    assert payload["counts"] == {
        "total": 3117,
        "by_dataset": {"funding": 183, "metrics_oi": 2268, "ohlcv": 666},
        "by_granularity": {"daily": 2502, "monthly": 615},
    }
    assert payload["config_identity"]["funding_tail_strategy"] == (
        "monthly_archive_after_period_close"
    )


def test_partial_month_keeps_only_supported_daily_datasets() -> None:
    config = DualHorizonAcquisition.from_yaml(CONFIG)
    july = [
        item
        for item in build_source_plan(config)
        if (item.period_start.year, item.period_start.month) == (2026, 7)
    ]
    assert any(
        item.dataset == SourceDataset.FUNDING
        and item.granularity == SourceGranularity.MONTHLY
        for item in july
    )
    assert all(
        item.granularity == SourceGranularity.DAILY
        for item in july
        if item.dataset != SourceDataset.FUNDING
    )
```

Extend `test_prepare_dual_horizon_dry_run_is_network_free` in
`tests/unit/test_cli_dual_horizon.py`:

```python
    assert payload["counts"]["total"] == 3117
    assert payload["counts"]["by_dataset"]["funding"] == 183
    assert payload["config_identity"]["funding_tail_strategy"] == (
        "monthly_archive_after_period_close"
    )
```

- [ ] **Step 2: Run the focused tests and confirm RED**

```powershell
uv run pytest tests/unit/data/test_acquisition.py `
  tests/unit/data/test_source_plan.py `
  tests/unit/test_cli_dual_horizon.py -q
```

Expected: failures report the missing `funding_tail_strategy` and old 3,192
object plan.

- [ ] **Step 3: Add the locked configuration field**

Add below `oi_delay_minutes` in
`configs/experiments/dual_horizon_derivatives.yaml`:

```yaml
funding_tail_strategy: monthly_archive_after_period_close
```

Add to `DualHorizonAcquisition` in `acquisition.py`:

```python
funding_tail_strategy: Literal["monthly_archive_after_period_close"]
```

Include it in `source_plan_payload(config)["config_identity"]`:

```python
"funding_tail_strategy": config.funding_tail_strategy,
```

- [ ] **Step 4: Implement the inclusive Funding month grid**

Add this helper next to `calendar_months`:

```python
def funding_months_through_cutoff(
    start: datetime, as_of: datetime
) -> tuple[tuple[int, int], ...]:
    months = list(calendar_months(start, as_of))
    cutoff_month = (as_of.year, as_of.month)
    if cutoff_month not in months:
        months.append(cutoff_month)
    return tuple(months)
```

Replace both Funding loops in `build_source_plan` with:

```python
for asset in config.assets:
    for year, month in funding_months_through_cutoff(
        config.macro_start, config.as_of
    ):
        objects.append(_make_monthly_funding(asset, year, month, raw_root))
```

Do not remove `daily_funding_url`; it is an existing public adapter API, but it
must have no caller in `build_source_plan`.

- [ ] **Step 5: Run focused and static gates**

```powershell
uv run pytest tests/unit/data/test_acquisition.py `
  tests/unit/data/test_source_plan.py `
  tests/unit/test_cli_dual_horizon.py -q
uv run ruff check src/bian_quant/data/acquisition.py `
  tests/unit/data/test_acquisition.py tests/unit/data/test_source_plan.py `
  tests/unit/test_cli_dual_horizon.py
uv run ruff format --check src/bian_quant/data/acquisition.py `
  tests/unit/data/test_acquisition.py tests/unit/data/test_source_plan.py `
  tests/unit/test_cli_dual_horizon.py
uv run mypy src/bian_quant/data/acquisition.py
```

Expected: all commands exit 0.

- [ ] **Step 6: Commit**

```powershell
git add configs/experiments/dual_horizon_derivatives.yaml `
  src/bian_quant/data/acquisition.py tests/unit/data/test_acquisition.py `
  tests/unit/data/test_source_plan.py tests/unit/test_cli_dual_horizon.py
git commit -m "fix(data): plan delayed monthly Funding tail"
```

---

### Task 2: Classify temporary Funding-tail unavailability

**Files:**
- Create: `src/bian_quant/data/acquisition_failures.py`
- Create: `tests/unit/data/test_acquisition_failures.py`

- [ ] **Step 1: Write failing stable-classification tests**

Create `tests/unit/data/test_acquisition_failures.py`:

```python
from pathlib import Path
from urllib.error import HTTPError

from bian_quant.data.acquisition import DualHorizonAcquisition, build_source_plan
from bian_quant.data.acquisition_failures import classify_acquisition_failure

CONFIG = Path("configs/experiments/dual_horizon_derivatives.yaml")


def _http_404(url: str) -> HTTPError:
    return HTTPError(url, 404, "Not Found", hdrs=None, fp=None)


def test_cutoff_month_funding_404_is_temporary() -> None:
    config = DualHorizonAcquisition.from_yaml(CONFIG)
    source = next(
        item
        for item in build_source_plan(config)
        if item.identity_key
        == "funding|BTCUSDT|native|monthly|2026-07-01T00:00:00+00:00"
    )
    result = classify_acquisition_failure(source, config, _http_404(source.url))
    assert result.error_code == "FUNDING_TAIL_ARCHIVE_NOT_YET_AVAILABLE"
    assert result.http_status == 404
    assert result.attempt_count == 1
    assert result.temporary


def test_historical_funding_404_is_required_source_failure() -> None:
    config = DualHorizonAcquisition.from_yaml(CONFIG)
    source = next(
        item
        for item in build_source_plan(config)
        if item.identity_key
        == "funding|BTCUSDT|native|monthly|2025-07-01T00:00:00+00:00"
    )
    result = classify_acquisition_failure(source, config, _http_404(source.url))
    assert result.error_code == "RAW_DOWNLOAD_FAILED"
    assert result.http_status == 404
    assert not result.temporary


def test_local_integrity_code_is_preserved() -> None:
    config = DualHorizonAcquisition.from_yaml(CONFIG)
    source = build_source_plan(config)[0]
    result = classify_acquisition_failure(
        source,
        config,
        ValueError("RAW_HASH_MISMATCH: stored bytes changed"),
    )
    assert result.error_code == "RAW_HASH_MISMATCH"
    assert result.attempt_count == 0
    assert not result.temporary
```

- [ ] **Step 2: Run the test and confirm RED**

```powershell
uv run pytest tests/unit/data/test_acquisition_failures.py -q
```

Expected: import failure for `acquisition_failures`.

- [ ] **Step 3: Implement immutable failure evidence**

Create `src/bian_quant/data/acquisition_failures.py`:

```python
from __future__ import annotations

from urllib.error import HTTPError

from pydantic import BaseModel, ConfigDict

from bian_quant.data.acquisition import (
    DualHorizonAcquisition,
    SourceDataset,
    SourceGranularity,
    SourceObject,
)


class AcquisitionFailureEvidence(BaseModel):
    model_config = ConfigDict(frozen=True)

    identity_key: str
    error_code: str
    message: str
    http_status: int | None
    attempt_count: int
    temporary: bool


def is_cutoff_month_funding(
    source: SourceObject, config: DualHorizonAcquisition
) -> bool:
    return (
        source.dataset == SourceDataset.FUNDING
        and source.granularity == SourceGranularity.MONTHLY
        and (source.period_start.year, source.period_start.month)
        == (config.as_of.year, config.as_of.month)
    )


def classify_acquisition_failure(
    source: SourceObject,
    config: DualHorizonAcquisition,
    error: Exception,
) -> AcquisitionFailureEvidence:
    message = str(error)
    http_status = error.code if isinstance(error, HTTPError) else None
    if http_status == 404 and is_cutoff_month_funding(source, config):
        code = "FUNDING_TAIL_ARCHIVE_NOT_YET_AVAILABLE"
        temporary = True
        attempts = 1
    elif isinstance(error, HTTPError):
        code = "RAW_DOWNLOAD_FAILED"
        temporary = False
        attempts = 1
    else:
        prefix = message.split(":", 1)[0]
        stable = {
            "RAW_ARTIFACT_INCOMPLETE",
            "RAW_HASH_MISMATCH",
            "RAW_IDENTITY_MISMATCH",
            "RAW_DOWNLOAD_FAILED",
        }
        code = prefix if prefix in stable else "RAW_DOWNLOAD_FAILED"
        temporary = False
        attempts = 0 if prefix in stable - {"RAW_DOWNLOAD_FAILED"} else config.download_attempts
    return AcquisitionFailureEvidence(
        identity_key=source.identity_key,
        error_code=code,
        message=message,
        http_status=http_status,
        attempt_count=attempts,
        temporary=temporary,
    )
```

- [ ] **Step 4: Run focused and static gates**

```powershell
uv run pytest tests/unit/data/test_acquisition_failures.py -q
uv run ruff check src/bian_quant/data/acquisition_failures.py `
  tests/unit/data/test_acquisition_failures.py
uv run ruff format --check src/bian_quant/data/acquisition_failures.py `
  tests/unit/data/test_acquisition_failures.py
uv run mypy src/bian_quant/data/acquisition_failures.py
```

Expected: all commands exit 0.

- [ ] **Step 5: Commit**

```powershell
git add src/bian_quant/data/acquisition_failures.py `
  tests/unit/data/test_acquisition_failures.py
git commit -m "feat(data): classify temporary Funding tail gaps"
```

---

### Task 3: Project canonical frames through the evidence cutoff

**Files:**
- Create: `src/bian_quant/data/evidence_cutoff.py`
- Create: `tests/unit/data/test_evidence_cutoff.py`

- [ ] **Step 1: Write failing cutoff and path tests**

Create `tests/unit/data/test_evidence_cutoff.py`:

```python
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd

from bian_quant.data.acquisition import (
    SourceDataset,
    SourceGranularity,
    SourceObject,
)
from bian_quant.data.evidence_cutoff import (
    canonical_plan_path,
    canonical_snapshot_id,
    clip_to_evidence_cutoff,
)
from bian_quant.data.hashing import dataframe_content_hash

AS_OF = datetime(2026, 7, 26, 19, 59, 59, 999000, tzinfo=UTC)


def _funding_source() -> SourceObject:
    return SourceObject(
        dataset=SourceDataset.FUNDING,
        asset="BTCUSDT",
        interval="native",
        granularity=SourceGranularity.MONTHLY,
        period_start=datetime(2026, 7, 1, tzinfo=UTC),
        url="https://example.test/BTCUSDT-fundingRate-2026-07.zip",
        relative_path=Path("funding/BTCUSDT/native/2026-07.zip"),
    )


def test_cutoff_requires_event_and_availability() -> None:
    frame = pd.DataFrame(
        {
            "asset": ["BTCUSDT"] * 3,
            "event_time": pd.to_datetime(
                [
                    "2026-07-26T16:00:00Z",
                    "2026-07-26T19:00:00Z",
                    "2026-07-27T00:00:00Z",
                ],
                utc=True,
            ),
            "available_time": pd.to_datetime(
                [
                    "2026-07-26T16:00:00Z",
                    "2026-07-26T20:00:00Z",
                    "2026-07-27T00:00:00Z",
                ],
                utc=True,
            ),
            "funding_rate": [0.1, 0.2, 0.3],
        }
    )
    result = clip_to_evidence_cutoff(_funding_source(), frame, as_of=AS_OF)
    assert list(result.eligible["funding_rate"]) == [0.1]
    assert result.evidence.eligible_rows == 1
    assert result.evidence.post_cutoff_rows_excluded == 2
    assert result.evidence.earliest_excluded_event_time == pd.Timestamp(
        "2026-07-26T19:00:00Z"
    )
    assert result.evidence.latest_excluded_available_time == pd.Timestamp(
        "2026-07-27T00:00:00Z"
    )


def test_post_cutoff_append_cannot_change_eligible_hash() -> None:
    base = pd.DataFrame(
        {
            "asset": ["BTCUSDT"],
            "event_time": pd.to_datetime(["2026-07-26T16:00:00Z"], utc=True),
            "available_time": pd.to_datetime(["2026-07-26T16:00:00Z"], utc=True),
            "funding_rate": [0.1],
        }
    )
    tail = pd.DataFrame(
        {
            "asset": ["BTCUSDT"],
            "event_time": pd.to_datetime(["2026-07-27T00:00:00Z"], utc=True),
            "available_time": pd.to_datetime(["2026-07-27T00:00:00Z"], utc=True),
            "funding_rate": [0.9],
        }
    )
    first = clip_to_evidence_cutoff(_funding_source(), base, as_of=AS_OF)
    second = clip_to_evidence_cutoff(
        _funding_source(), pd.concat([base, tail], ignore_index=True), as_of=AS_OF
    )
    assert dataframe_content_hash(
        first.eligible, sort_by=["asset", "event_time"]
    ) == dataframe_content_hash(
        second.eligible, sort_by=["asset", "event_time"]
    )


def test_canonical_path_is_plan_namespaced() -> None:
    path = canonical_plan_path(
        Path("var/lake/canonical/binance-futures-um"),
        plan_hash="a" * 64,
        relative_path=Path("funding/BTCUSDT/native/2026-07.zip"),
    )
    assert path.as_posix().endswith(
        "plan=aaaaaaaaaaaaaaaa/funding/BTCUSDT/native/2026-07.parquet"
    )


def test_canonical_id_is_plan_namespaced() -> None:
    first = canonical_snapshot_id(
        _funding_source(), content_sha="b" * 64, plan_hash="a" * 64
    )
    second = canonical_snapshot_id(
        _funding_source(), content_sha="b" * 64, plan_hash="c" * 64
    )
    assert first.startswith("canonical-funding-bbbbbbbbbbbbbbbb-")
    assert first != second
```

- [ ] **Step 2: Run the test and confirm RED**

```powershell
uv run pytest tests/unit/data/test_evidence_cutoff.py -q
```

Expected: import failure for `evidence_cutoff`.

- [ ] **Step 3: Implement the cutoff projection and evidence model**

Create `src/bian_quant/data/evidence_cutoff.py`:

```python
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
    value = getattr(pd.to_datetime(frame[column], utc=True), operation)()
    return value.to_pydatetime()


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
        earliest_excluded_available_time=_optional_time(
            excluded, "available_time", "min"
        ),
        latest_excluded_available_time=_optional_time(
            excluded, "available_time", "max"
        ),
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
    identity = hashlib.sha256(
        f"{source.identity_key}|{plan_hash}".encode("utf-8")
    ).hexdigest()[:12]
    return f"canonical-{source.dataset.value}-{content_sha[:16]}-{identity}"
```

- [ ] **Step 4: Run focused and static gates**

```powershell
uv run pytest tests/unit/data/test_evidence_cutoff.py -q
uv run ruff check src/bian_quant/data/evidence_cutoff.py `
  tests/unit/data/test_evidence_cutoff.py
uv run ruff format --check src/bian_quant/data/evidence_cutoff.py `
  tests/unit/data/test_evidence_cutoff.py
uv run mypy src/bian_quant/data/evidence_cutoff.py
```

Expected: all commands exit 0.

- [ ] **Step 5: Commit**

```powershell
git add src/bian_quant/data/evidence_cutoff.py `
  tests/unit/data/test_evidence_cutoff.py
git commit -m "feat(data): enforce evidence cutoff projection"
```

---

### Task 4: Integrate temporary failures, causal coverage, and immutable outputs

**Files:**
- Modify: `src/bian_quant/data/dual_horizon.py`
- Modify: `src/bian_quant/data/derivatives_quality.py`
- Modify: `tests/unit/data/test_dual_horizon_real_archives.py`
- Modify: `tests/integration/data/test_dual_horizon_pipeline.py`

- [ ] **Step 1: Write failing causal-quality and artifact tests**

Add to `tests/unit/data/test_dual_horizon_real_archives.py`:

```python
def test_metrics_row_unavailable_at_cutoff_is_not_observed() -> None:
    config = DualHorizonAcquisition.from_yaml(CONFIG)
    source = next(
        item
        for item in build_source_plan(config)
        if item.identity_key
        == "metrics_oi|BTCUSDT|native|daily|2026-07-26T00:00:00+00:00"
    )
    times = pd.date_range(source.period_start, periods=240, freq="5min")
    frame = pd.DataFrame(
        {
            "asset": "BTCUSDT",
            "event_time": times,
            "available_time": times + timedelta(minutes=5),
            "sum_open_interest": 100.0,
            "sum_open_interest_value": 200.0,
        }
    )
    report = _quality_report(source, frame, config)
    assert report.observed_rows == 239
    assert report.expected_rows == 239
    assert report.findings == ()
```

Update `_miniature_config` in
`tests/integration/data/test_dual_horizon_pipeline.py` with:

```python
funding_tail_strategy="monthly_archive_after_period_close",
```

Change the missing local object count from 45 to 39. Extend the passing pipeline
test with:

```python
    acquisition = json.loads(
        result.acquisition_artifact.read_text(encoding="utf-8")
    )
    quality = json.loads(result.quality_artifact.read_text(encoding="utf-8"))
    assert acquisition["funding_tail_strategy"] == (
        "monthly_archive_after_period_close"
    )
    assert acquisition["cutoff_evidence"] == quality["cutoff_evidence"]
    assert all(item["asset"] for item in quality["coverage_reports"])
    assert all(item["identity_key"] for item in quality["coverage_reports"])
    assert any(
        item["dataset"] == "funding"
        and item["post_cutoff_rows_excluded"] > 0
        for item in acquisition["cutoff_evidence"]
    )
    assert all(
        manifest.max_event_time <= config.as_of for manifest in result.snapshots
    )
    assert all(
        manifest.max_available_time <= config.as_of for manifest in result.snapshots
    )
```

Add a downloader that raises a cutoff-month 404 and this test:

```python
from urllib.error import HTTPError


def test_cutoff_month_funding_404_persists_temporary_error(tmp_path: Path) -> None:
    config = _miniature_config(tmp_path)
    inner = FixtureDownloader(FIXTURES)

    class TailUnavailableDownloader:
        def acquire(self, source, current_config):
            if (
                source.dataset.value == "funding"
                and source.period_start.month == current_config.as_of.month
            ):
                raise HTTPError(source.url, 404, "Not Found", hdrs=None, fp=None)
            return inner.acquire(source, current_config)

    result = prepare_dual_horizon(
        config,
        code_sha="e" * 40,
        downloader=TailUnavailableDownloader(),
    )
    assert result.status == DualHorizonStatus.BLOCKED
    assert result.error_code == "FUNDING_TAIL_ARCHIVE_NOT_YET_AVAILABLE"
    payload = json.loads(result.acquisition_artifact.read_text(encoding="utf-8"))
    failed = [item for item in payload["results"] if item["status"] == "failed"]
    assert len(failed) == 3
    assert {item["error_code"] for item in failed} == {
        "FUNDING_TAIL_ARCHIVE_NOT_YET_AVAILABLE"
    }
    assert all(item["http_status"] == 404 for item in failed)
    assert all(item["attempt_count"] == 1 for item in failed)
    assert all(item["temporary"] is True for item in failed)
    assert result.snapshots == ()
```

- [ ] **Step 2: Run the focused tests and confirm RED**

```powershell
uv run pytest tests/unit/data/test_dual_horizon_real_archives.py `
  tests/integration/data/test_dual_horizon_pipeline.py -q
```

Expected: failures show event-only coverage, legacy canonical paths, absent
cutoff evidence, and unstructured HTTP errors.

- [ ] **Step 3: Make quality eligibility depend on both clocks**

Add backward-compatible source identity fields to `CoverageReport` in
`derivatives_quality.py`:

```python
asset: str | None = None
identity_key: str | None = None
```

In `_quality_report`, replace the event-only `in_period` selection with:

```python
in_period = source_frame.loc[
    (source_frame["event_time"] <= config.as_of)
    & (source_frame["available_time"] <= config.as_of)
]
```

For Metrics/OI, compute the primary five-minute availability boundary before
calling `inspect_metrics`:

```python
metrics_event_cutoff = config.as_of - timedelta(
    minutes=min(config.oi_delay_minutes)
)
metrics_period_end = min(
    natural_end,
    metrics_event_cutoff + timedelta(microseconds=1),
)
expected_rows = None
if metrics_right_closed:
    expected_rows = max(
        0,
        math.floor(
            (min(natural_end, metrics_event_cutoff) - source.period_start)
            .total_seconds()
            / 300
        ),
    )
report = inspect_metrics(
    in_period,
    period_start=source.period_start,
    period_end=metrics_period_end,
    threshold=config.coverage.metrics_oi,
    expected_rows=expected_rows,
)
```

Keep source-period mismatch checks against the complete parsed source frame;
expected post-cutoff rows are not mismatches. Before returning, attach the exact
source identity:

```python
return report.model_copy(
    update={"asset": source.asset, "identity_key": source.identity_key}
)
```

- [ ] **Step 4: Integrate structured acquisition failures**

Import `AcquisitionFailureEvidence` and `classify_acquisition_failure`. Change
`acquire_one` to return the exception object:

```python
def acquire_one(
    source: SourceObject,
) -> tuple[SourceObject, AcquisitionObjectResult | None, Exception | None]:
    try:
        return source, downloader.acquire(source, config), None
    except Exception as error:
        return source, None, error
```

On a failed outcome, serialize:

```python
failure = classify_acquisition_failure(source, config, error)
acquisition_failures.append(failure)
acquisition_results.append(
    {
        "identity_key": source.identity_key,
        "status": "failed",
        **failure.model_dump(mode="json", exclude={"identity_key"}),
    }
)
blocked_periods.append(source.identity_key)
```

After all work, compute the run error code exactly:

```python
temporary_only = bool(acquisition_failures) and all(
    item.temporary for item in acquisition_failures
) and set(blocked_periods) == {
    item.identity_key for item in acquisition_failures
}
run_error_code = (
    "FUNDING_TAIL_ARCHIVE_NOT_YET_AVAILABLE"
    if temporary_only and not any(report.blocking for report in coverage_reports)
    else ("DATA_PIPELINE_BLOCKED" if blocked_periods else None)
)
```

Return `run_error_code` from `DualHorizonResult`.

- [ ] **Step 5: Clip before append, canonical write, and catalog registration**

Import `canonical_plan_path`, `canonical_snapshot_id`, and
`clip_to_evidence_cutoff`. After parsing the complete source and creating its
quality report, run:

```python
cutoff_slice = clip_to_evidence_cutoff(source, frame, as_of=config.as_of)
cutoff_evidence.append(cutoff_slice.evidence)
eligible_frame = cutoff_slice.eligible
if eligible_frame.empty:
    raise ValueError(
        f"EVIDENCE_CUTOFF_VIOLATION: no eligible rows for {source.identity_key}"
    )
canonical_path = canonical_plan_path(
    config.canonical_root,
    plan_hash=plan_hash,
    relative_path=source.relative_path,
)
content_sha = write_canonical_partition(eligible_frame, canonical_path)
canonical_id = canonical_snapshot_id(
    source,
    content_sha=content_sha,
    plan_hash=plan_hash,
)
```

Append only `eligible_frame` to `ohlcv_frames`, `funding_frames`, or
`metrics_frames`. Build the canonical `DatasetManifest` from `eligible_frame`,
not the complete source frame, and use `canonical_id` as its `snapshot_id`.
Remove the later OHLCV-only event-time filter; all three combined frames are
already cutoff-bound.

- [ ] **Step 6: Persist identical sorted cutoff evidence in both artifacts**

Before serialization:

```python
cutoff_payload = [
    item.model_dump(mode="json")
    for item in sorted(cutoff_evidence, key=lambda item: item.identity_key)
]
```

Add these fields to both `acquisition_data` and `quality_data`:

```python
"funding_tail_strategy": config.funding_tail_strategy,
"cutoff_evidence": cutoff_payload,
```

Keep the existing result sorting, disk measurements, append-only artifact paths,
and all-or-nothing snapshot publication.

- [ ] **Step 7: Make the fixture monthly Funding archive exercise a tail**

In `FixtureDownloader._payload_for`, replace the three-row Funding branch with:

```python
elif source.dataset == SourceDataset.FUNDING:
    rows = [header]
    event = start
    natural_end = (
        start.replace(year=start.year + 1, month=1)
        if start.month == 12
        else start.replace(month=start.month + 1)
    )
    while event < natural_end:
        rows.append(f"{int(event.timestamp() * 1000)},8,0.0001")
        event += timedelta(hours=8)
```

This creates a complete miniature monthly archive so the integration test proves
post-cutoff clipping and evidence persistence.

- [ ] **Step 8: Run focused, full, and static gates**

```powershell
uv run pytest tests/unit/data/test_dual_horizon_real_archives.py `
  tests/unit/data/test_evidence_cutoff.py `
  tests/unit/data/test_acquisition_failures.py `
  tests/integration/data/test_dual_horizon_pipeline.py -q
uv run pytest -q
uv run ruff check src tests
uv run ruff format --check src tests
uv run mypy src/bian_quant
git diff --check
```

Expected: the focused suite passes; the full suite passes with only the four
marked network tests deselected; Ruff, format, strict mypy, and diff check exit
0.

- [ ] **Step 9: Commit**

```powershell
git add src/bian_quant/data/dual_horizon.py `
  src/bian_quant/data/derivatives_quality.py `
  tests/unit/data/test_dual_horizon_real_archives.py `
  tests/integration/data/test_dual_horizon_pipeline.py
git commit -m "fix(data): clip monthly Funding evidence causally"
```

---

### Task 5: Verify CLI, network compatibility, migration notes, and packaging

**Files:**
- Modify: `tests/network/test_dual_horizon_binance.py` only if imports or exact
  source selection need formatting changes
- Modify: `docs/implementation-notes.md`

- [ ] **Step 1: Run the deterministic dry-run and inspect exact scope**

```powershell
$sha = git rev-parse HEAD
uv run python -c "from pathlib import Path; from bian_quant.data.acquisition import DualHorizonAcquisition, source_plan_payload; p=source_plan_payload(DualHorizonAcquisition.from_yaml(Path('configs/experiments/dual_horizon_derivatives.yaml'))); print(p['config_identity']); print(p['counts'])"
```

Expected output contains the locked cutoff and strategy plus:

```text
{'total': 3117, 'by_dataset': {'funding': 183, 'metrics_oi': 2268, 'ohlcv': 666}, 'by_granularity': {'monthly': 615, 'daily': 2502}}
```

- [ ] **Step 2: Run the fixed network smoke test**

```powershell
uv run pytest tests/network/test_dual_horizon_binance.py -q -m network
```

Expected: the fixed 2021-07 monthly Funding object, fixed OHLCV object, and fixed
Metrics/OI object verify and parse; the test does not request the full matrix.

- [ ] **Step 3: Record the migration contract**

Append a dated section to `docs/implementation-notes.md` containing these exact
facts:

```markdown
## 2026-07-31 Funding monthly-tail amendment

- The evidence cutoff remains `2026-07-26T19:59:59.999Z`.
- Funding now uses monthly archives through the cutoff month; the source plan
  contains 3,117 objects and no Funding daily objects.
- A cutoff-month HTTP 404 is persisted as
  `FUNDING_TAIL_ARCHIVE_NOT_YET_AVAILABLE` and is resumable.
- Canonical outputs are clipped by both event and availability time and live
  below a `plan=` directory named by the first 16 source-plan hash characters;
  prior blocked canonical files remain immutable.
- REST Funding, imputation, changed assets, changed windows, and changed holdout
  boundaries remain out of scope.
```

- [ ] **Step 4: Run Windows quality and distribution gates**

```powershell
uv sync --frozen --extra dev
powershell -ExecutionPolicy Bypass -File scripts/check.ps1
uv build
```

Expected: Ruff, formatting, strict mypy, default pytest, wheel build, and sdist
build all exit 0.

- [ ] **Step 5: Verify both distributions in isolated environments**

Use SHA-specific paths so prior verification environments remain immutable:

```powershell
$sha = (git rev-parse --short HEAD)
uv venv "var/plan035-wheel-verify-$sha"
uv pip install --python "var/plan035-wheel-verify-$sha/Scripts/python.exe" `
  dist/bian_quant-0.1.0-py3-none-any.whl
& "var/plan035-wheel-verify-$sha/Scripts/python.exe" -c `
  "from bian_quant.data.acquisition_failures import classify_acquisition_failure; from bian_quant.data.evidence_cutoff import clip_to_evidence_cutoff; print('ok')"
& "var/plan035-wheel-verify-$sha/Scripts/bian-quant.exe" --help

uv venv "var/plan035-sdist-verify-$sha"
uv pip install --python "var/plan035-sdist-verify-$sha/Scripts/python.exe" `
  dist/bian_quant-0.1.0.tar.gz
& "var/plan035-sdist-verify-$sha/Scripts/python.exe" -c `
  "from bian_quant.data.acquisition_failures import classify_acquisition_failure; from bian_quant.data.evidence_cutoff import clip_to_evidence_cutoff; print('ok')"
& "var/plan035-sdist-verify-$sha/Scripts/bian-quant.exe" --help
```

Expected: both import commands print `ok`; both CLI commands print help and exit
0.

- [ ] **Step 6: Commit**

```powershell
git add docs/implementation-notes.md tests/network/test_dual_horizon_binance.py
git commit -m "docs: record monthly Funding tail migration"
```

If the network test file did not change, the commit contains only
`docs/implementation-notes.md`.

---

### Task 6: Resume real Task 10 acquisition, analysis, and bounded evidence

**Files:**
- Create after a passed run: `docs/evidence/dual-horizon-data-summary.json`
- Create after a passed run: `docs/evidence/dual-horizon-data-summary.md`
- Create after a passed run: `docs/evidence/dual-horizon-factor-summary.json`
- Create after a passed run: `docs/evidence/dual-horizon-factor-summary.md`
- Modify after a passed run: `docs/implementation-notes.md`

- [ ] **Step 1: Check only the three cutoff-month Funding URLs**

```powershell
uv run python -c "from pathlib import Path; from bian_quant.data.acquisition import DualHorizonAcquisition, SourceDataset, build_source_plan; c=DualHorizonAcquisition.from_yaml(Path('configs/experiments/dual_horizon_derivatives.yaml')); print('\n'.join(x.url for x in build_source_plan(c) if x.dataset == SourceDataset.FUNDING and (x.period_start.year, x.period_start.month) == (c.as_of.year, c.as_of.month)))"
```

For each printed URL, request the object through the normal downloader, not a
separate unverified client. If Binance still returns 404, run the full command
once to persist the temporary state, verify exactly three failures with
`FUNDING_TAIL_ARCHIVE_NOT_YET_AVAILABLE`, write the run ID to the SDD ledger,
and stop Task 6 without analysis, evidence commits, Task 7, or push.

- [ ] **Step 2: Run bounded acquisition when the monthly archives exist**

```powershell
$sha = git rev-parse HEAD
uv run bian-quant prepare-dual-horizon `
  --config configs/experiments/dual_horizon_derivatives.yaml `
  --code-sha $sha `
  --download
```

Expected: 3,117 planned objects, all required objects verified, four snapshots
published, and no post-cutoff canonical or research row. `var/` remains ignored.

- [ ] **Step 3: Prove resumability without deleting any runtime data**

Run the same command again with the same SHA and config:

```powershell
uv run bian-quant prepare-dual-horizon `
  --config configs/experiments/dual_horizon_derivatives.yaml `
  --code-sha $sha `
  --download
```

Expected: every verified raw object is `skipped`; source-plan hash, coverage,
cutoff evidence, snapshot IDs, and snapshot content hashes match the first passed
run.

- [ ] **Step 4: Run analysis and preserve the holdout boundary**

```powershell
uv run bian-quant analyze-dual-horizon `
  --config configs/experiments/dual_horizon_derivatives.yaml `
  --code-sha $sha
```

Expected: one append-only run directory contains all seven decision artifacts.
Zero candidates is valid. Do not run `evaluate-holdout` unless the factor report
lists a Candidate; if it does, record the candidate ID/version and use the
existing candidate-only command exactly once.

- [ ] **Step 5: Write bounded data and factor evidence**

Create the four `docs/evidence/dual-horizon-*` files from the passed acquisition
and analysis artifacts. The data JSON contains these exact keys and values from
the authoritative artifacts:

- `code_sha`: the 40-character SHA passed to both commands;
- `acquisition_run_id`: `data-acquisition.json["run_id"]`;
- `source_plan_hash`: `data-acquisition.json["plan_hash"]`;
- `funding_tail_strategy`: literal `monthly_archive_after_period_close`;
- `planned_objects`: integer `3117`;
- `snapshot_ids`: a name-to-ID mapping containing exactly `macro-1d`,
  `macro-4h`, `micro-1h`, and `micro-4h`;
- `coverage`: every persisted coverage report grouped by dataset, asset, and
  source period without recomputation;
- `cutoff_evidence`: an exact copy of `data-quality.json["cutoff_evidence"]`;
- `excluded_periods`: an exact sorted copy from the quality artifact;
- `persistent_bytes` and `peak_working_bytes`: the non-negative integers from
  the acquisition artifact;
- `funding_status` and `oi_status`: both literal `real` only because the passed
  run verified their required sources.

Validate that `code_sha` and `source_plan_hash` have lengths 40 and 64,
respectively; the snapshot key set is exact; `persistent_bytes` is positive;
`peak_working_bytes` is non-negative; and the evidence file's cutoff list equals
the runtime quality artifact before staging it.

The factor JSON must contain the analysis run ID, current Macro state and
fit-through timestamp, counts of researching/observed/candidate/approved
factors, every factor's gate reasons, and holdout access history. The Markdown
files explain the same facts and state engineering status separately from
promotion status.

- [ ] **Step 6: Validate Git boundaries and commit only bounded evidence**

```powershell
git check-ignore -v var/lake/raw var/lake/canonical var/lake/research var/artifacts
git diff --diff-filter=D --name-status fd5995b..HEAD
git status --short
```

Expected: no tracked file is deleted; runtime data is ignored; only the four
evidence files and implementation-note update are uncommitted.

```powershell
git add docs/evidence/dual-horizon-data-summary.json `
  docs/evidence/dual-horizon-data-summary.md `
  docs/evidence/dual-horizon-factor-summary.json `
  docs/evidence/dual-horizon-factor-summary.md `
  docs/implementation-notes.md
git commit -m "docs: record monthly-tail dual-horizon evidence"
```

---

### Task 7: Run final cross-platform review, push, and stop

**Files:**
- Modify: `docs/implementation-notes.md` only if a verified environment
  deviation must be recorded

- [ ] **Step 1: Run final Windows and network gates from a clean tree**

```powershell
git status --short --branch
uv sync --frozen --extra dev
powershell -ExecutionPolicy Bypass -File scripts/check.ps1
uv run pytest -q -m network
uv build
```

Expected: clean worktree and all commands exit 0.

- [ ] **Step 2: Run the WSL2 Ubuntu gate**

```powershell
wsl.exe -d Ubuntu-24.04 -- bash -lc "cd /mnt/f/bianV2-research-implementation && env UV_PROJECT_ENVIRONMENT=.venv-wsl uv sync --frozen --extra dev && env UV_PROJECT_ENVIRONMENT=.venv-wsl bash scripts/check.sh"
```

Expected: the same static and default suite passes under Ubuntu 24.04.

- [ ] **Step 3: Verify storage, causality, and repository safety**

```powershell
$persistent = (Get-ChildItem var/lake,var/artifacts -Recurse -File | Measure-Object Length -Sum).Sum
[pscustomobject]@{
  PersistentBytes = $persistent
  PersistentGB = [math]::Round($persistent / 1GB, 3)
}
git diff --check
git diff --diff-filter=D --name-status fd5995b..HEAD
git status --short --branch
```

Expected: persistent data is at most 2.5 GB, no tracked deletion is listed, diff
check passes, and the implementation branch is clean. Do not delete old blocked
evidence to reduce storage.

- [ ] **Step 4: Run the required whole-branch independent review**

Generate a review package from `fd5995b` through `HEAD`. The reviewer must check
the approved parent design, the monthly-tail amendment, both implementation
plans, the SDD ledger, the full diff, and the recorded gates. Resolve every
Critical or Important finding through the bounded fix/re-review loop before
push. Record Minor rulings in the ledger.

- [ ] **Step 5: Push the implementation branch and verify equality**

```powershell
git push origin codex/research-platform-implementation
$local = git rev-parse HEAD
$remote = git rev-parse origin/codex/research-platform-implementation
if ($local -ne $remote) { throw "local/remote SHA mismatch" }
$local
```

Expected: local and remote SHA match.

- [ ] **Step 6: Report and stop**

Report every new commit, Windows/WSL2/network/build/install counts, source and
snapshot IDs, coverage and cutoff evidence, storage bytes, current Macro state,
factor lifecycle counts, and whether holdout was opened. Do not start Plan 04.

---

## Amendment exit gate

- [ ] Config identity locks `monthly_archive_after_period_close`.
- [ ] Source plan has exactly 3,117 objects, including 183 monthly and zero
      daily Funding objects.
- [ ] Cutoff-month pre-publication 404s are temporary and resumable.
- [ ] Canonical paths are source-plan namespaced; old blocked data is unchanged.
- [ ] Every eligible row satisfies both `event_time <= as_of` and
      `available_time <= as_of`.
- [ ] Cutoff evidence is identical in acquisition and quality artifacts.
- [ ] Funding coverage through `as_of` reaches 99 percent for all three assets.
- [ ] Four snapshots and three OI delay views are immutable and reproducible.
- [ ] Analysis completes even with zero candidates; holdout remains protected.
- [ ] Windows, WSL2, network, distribution, isolated-install, storage,
      Git-boundary, and independent-review gates pass.
- [ ] Branch is pushed; Plan 04 is not started.
