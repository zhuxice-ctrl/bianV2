# Point-in-Time Data Platform Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build immutable Raw, deterministic Canonical, and point-in-time Research data layers for BTC/ETH core research and later migration assets.

**Architecture:** Adapters save source bytes and manifests before parsing. Canonical writers validate timezone-aware three-time records, store partitioned Parquet, and register content hashes in SQLite. Research queries filter by `available_time`, so future observations cannot enter a decision dataset.

**Tech Stack:** Pydantic, pandas, PyArrow, DuckDB, SQLite, Typer, pytest/Hypothesis.

---

### Task 1: Define market, dataset, and quality contracts

**Files:**
- Create: `src/bian_quant/data/__init__.py`
- Create: `src/bian_quant/data/contracts.py`
- Test: `tests/unit/data/test_contracts.py`

- [ ] **Step 1: Write failing contract tests**

Create `tests/unit/data/test_contracts.py`:

```python
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from bian_quant.data.contracts import DatasetLayer, MarketRecord, QualitySeverity


def test_market_record_requires_available_time_after_event_time() -> None:
    with pytest.raises(ValidationError):
        MarketRecord(
            asset="BTCUSDT",
            event_time=datetime(2026, 1, 1, 1, tzinfo=UTC),
            available_time=datetime(2026, 1, 1, 0, tzinfo=UTC),
            ingested_at=datetime(2026, 1, 2, tzinfo=UTC),
            source="legacy_csv",
        )


def test_contract_enums_are_stable() -> None:
    assert DatasetLayer.RAW.value == "raw"
    assert QualitySeverity.BLOCKING.value == "blocking"
```

- [ ] **Step 2: Confirm failure**

```bash
uv run pytest tests/unit/data/test_contracts.py -q
```

Expected: missing module.

- [ ] **Step 3: Implement contracts**

Create empty `src/bian_quant/data/__init__.py` and create `src/bian_quant/data/contracts.py`:

```python
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, model_validator


class DatasetLayer(StrEnum):
    RAW = "raw"
    CANONICAL = "canonical"
    RESEARCH = "research"


class QualitySeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    BLOCKING = "blocking"


class MarketRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    asset: str
    event_time: datetime
    available_time: datetime
    ingested_at: datetime
    source: str

    @model_validator(mode="after")
    def validate_times(self) -> "MarketRecord":
        for value in (self.event_time, self.available_time, self.ingested_at):
            if value.tzinfo is None:
                raise ValueError("all timestamps must be timezone-aware")
        if self.available_time < self.event_time:
            raise ValueError("available_time must not precede event_time")
        if self.ingested_at < self.available_time:
            raise ValueError("ingested_at must not precede available_time")
        return self


class DatasetManifest(BaseModel):
    snapshot_id: str
    layer: DatasetLayer
    name: str
    content_sha256: str
    row_count: int
    min_event_time: datetime | None
    max_event_time: datetime | None
    parent_snapshot_ids: list[str]
    config_json: str


class QualityFinding(BaseModel):
    code: str
    severity: QualitySeverity
    message: str
    rows: list[int] = []
```

- [ ] **Step 4: Run tests and commit**

```bash
uv run pytest tests/unit/data/test_contracts.py -q
git add src/bian_quant/data tests/unit/data
git commit -m "feat(data): define point-in-time data contracts"
```

### Task 2: Implement the dataset catalog and content identity

**Files:**
- Create: `src/bian_quant/data/catalog.py`
- Create: `src/bian_quant/data/hashing.py`
- Test: `tests/unit/data/test_catalog.py`
- Test: `tests/unit/data/test_hashing.py`

- [ ] **Step 1: Write failing deterministic hash and catalog tests**

Create `tests/unit/data/test_hashing.py`:

```python
import pandas as pd

from bian_quant.data.hashing import dataframe_content_hash


def test_hash_is_independent_of_input_row_order() -> None:
    frame = pd.DataFrame({"asset": ["ETH", "BTC"], "value": [2.0, 1.0]})

    assert dataframe_content_hash(frame, sort_by=["asset"]) == dataframe_content_hash(
        frame.iloc[::-1], sort_by=["asset"]
    )
```

Create `tests/unit/data/test_catalog.py`:

```python
from datetime import UTC, datetime
from pathlib import Path

from bian_quant.data.catalog import DatasetCatalog
from bian_quant.data.contracts import DatasetLayer, DatasetManifest


def test_catalog_rejects_snapshot_id_reuse_with_different_content(tmp_path: Path) -> None:
    catalog = DatasetCatalog(tmp_path / "registry.sqlite")
    base = DatasetManifest(
        snapshot_id="legacy-v1",
        layer=DatasetLayer.CANONICAL,
        name="ohlcv_4h",
        content_sha256="a" * 64,
        row_count=1,
        min_event_time=datetime(2026, 1, 1, tzinfo=UTC),
        max_event_time=datetime(2026, 1, 1, tzinfo=UTC),
        parent_snapshot_ids=[],
        config_json="{}",
    )
    catalog.register(base, path=tmp_path / "one.parquet")

    changed = base.model_copy(update={"content_sha256": "b" * 64})

    try:
        catalog.register(changed, path=tmp_path / "two.parquet")
    except ValueError as error:
        assert "snapshot_id already exists" in str(error)
    else:
        raise AssertionError("catalog allowed evidence replacement")
```

- [ ] **Step 2: Confirm failure**

```bash
uv run pytest tests/unit/data/test_hashing.py tests/unit/data/test_catalog.py -q
```

- [ ] **Step 3: Implement content hash**

Create `src/bian_quant/data/hashing.py`:

```python
import hashlib

import pandas as pd


def dataframe_content_hash(frame: pd.DataFrame, *, sort_by: list[str]) -> str:
    stable = frame.sort_values(sort_by).reset_index(drop=True)
    payload = stable.to_json(orient="table", date_format="iso", double_precision=15)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
```

- [ ] **Step 4: Implement SQLite catalog**

Create `src/bian_quant/data/catalog.py`:

```python
import sqlite3
from pathlib import Path

from bian_quant.data.contracts import DatasetManifest


class DatasetCatalog:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS datasets (
                    snapshot_id TEXT PRIMARY KEY,
                    layer TEXT NOT NULL,
                    name TEXT NOT NULL,
                    content_sha256 TEXT NOT NULL,
                    path TEXT NOT NULL,
                    manifest_json TEXT NOT NULL
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)

    def register(self, manifest: DatasetManifest, *, path: Path) -> None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT content_sha256 FROM datasets WHERE snapshot_id = ?",
                (manifest.snapshot_id,),
            ).fetchone()
            if row is not None and row[0] != manifest.content_sha256:
                raise ValueError("snapshot_id already exists with different content")
            connection.execute(
                "INSERT OR IGNORE INTO datasets VALUES (?, ?, ?, ?, ?, ?)",
                (
                    manifest.snapshot_id,
                    manifest.layer.value,
                    manifest.name,
                    manifest.content_sha256,
                    str(path),
                    manifest.model_dump_json(),
                ),
            )
```

- [ ] **Step 5: Run tests and commit**

```bash
uv run pytest tests/unit/data/test_hashing.py tests/unit/data/test_catalog.py -q
git add src/bian_quant/data tests/unit/data
git commit -m "feat(data): add immutable dataset catalog"
```

### Task 3: Import legacy CSVs into deterministic Canonical Parquet

**Files:**
- Create: `src/bian_quant/data/legacy.py`
- Create: `src/bian_quant/data/writer.py`
- Modify: `src/bian_quant/cli.py`
- Test: `tests/integration/data/test_legacy_import.py`

- [ ] **Step 1: Write a failing import test**

Create `tests/integration/data/test_legacy_import.py`:

```python
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from bian_quant.data.legacy import import_legacy_ohlcv


def test_legacy_import_sets_bar_close_as_available_time(tmp_path: Path) -> None:
    source = tmp_path / "BTCUSDT_4h.csv"
    pd.DataFrame(
        [{"datetime": "2026-01-01T00:00:00Z", "open": 1, "high": 2, "low": 1, "close": 2, "volume": 3}]
    ).to_csv(source, index=False)

    frame = import_legacy_ohlcv(
        source,
        asset="BTCUSDT",
        interval="4h",
        ingested_at=datetime(2026, 1, 2, tzinfo=UTC),
    )

    assert frame.loc[0, "event_time"] == pd.Timestamp("2026-01-01T00:00:00Z")
    assert frame.loc[0, "available_time"] == pd.Timestamp("2026-01-01T04:00:00Z")
```

- [ ] **Step 2: Confirm failure**

```bash
uv run pytest tests/integration/data/test_legacy_import.py -q
```

- [ ] **Step 3: Implement importer and writer**

Create `src/bian_quant/data/legacy.py`:

```python
from datetime import datetime
from pathlib import Path

import pandas as pd

INTERVALS = {"1h": pd.Timedelta(hours=1), "4h": pd.Timedelta(hours=4), "1d": pd.Timedelta(days=1)}


def import_legacy_ohlcv(
    path: Path, *, asset: str, interval: str, ingested_at: datetime
) -> pd.DataFrame:
    if interval not in INTERVALS:
        raise ValueError(f"unsupported interval: {interval}")
    frame = pd.read_csv(path)
    event_time = pd.to_datetime(frame.pop("datetime"), utc=True)
    frame.insert(0, "asset", asset)
    frame.insert(1, "interval", interval)
    frame.insert(2, "event_time", event_time)
    frame.insert(3, "available_time", event_time + INTERVALS[interval])
    frame.insert(4, "ingested_at", pd.Timestamp(ingested_at))
    frame.insert(5, "source", "legacy_csv")
    return frame.sort_values(["asset", "event_time"]).reset_index(drop=True)
```

Create `src/bian_quant/data/writer.py`:

```python
from pathlib import Path

import pandas as pd


def write_parquet(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(path, engine="pyarrow", index=False, compression="zstd")
```

- [ ] **Step 4: Add CLI command**

Add to `src/bian_quant/cli.py`:

```python
from datetime import datetime

from bian_quant.data.legacy import import_legacy_ohlcv
from bian_quant.data.writer import write_parquet


@app.command("import-legacy")
def import_legacy(
    source: Path,
    asset: str,
    interval: str,
    output: Path,
    ingested_at: datetime,
) -> None:
    frame = import_legacy_ohlcv(
        source, asset=asset, interval=interval, ingested_at=ingested_at
    )
    write_parquet(frame, output)
    typer.echo(str(output))
```

- [ ] **Step 5: Test deterministic import twice**

```bash
uv run pytest tests/integration/data/test_legacy_import.py -q
uv run bian-quant import-legacy data/BTCUSDT_4h.csv BTCUSDT 4h var/lake/canonical/legacy-v1/BTCUSDT_4h.parquet --ingested-at 2026-07-29T00:00:00+00:00
sha256sum var/lake/canonical/legacy-v1/BTCUSDT_4h.parquet
```

Run the import again and confirm the SHA-256 is unchanged.

- [ ] **Step 6: Commit**

```bash
git add src/bian_quant/data src/bian_quant/cli.py tests/integration/data
git commit -m "feat(data): import legacy OHLCV snapshot"
```

### Task 4: Add blocking data-quality checks

**Files:**
- Create: `src/bian_quant/data/quality.py`
- Test: `tests/unit/data/test_quality.py`

- [ ] **Step 1: Write failing quality tests**

Create `tests/unit/data/test_quality.py`:

```python
import pandas as pd

from bian_quant.data.quality import inspect_ohlcv


def test_impossible_ohlc_is_blocking() -> None:
    frame = pd.DataFrame(
        [{"open": 10, "high": 9, "low": 8, "close": 10, "volume": 1, "event_time": "2026-01-01T00:00:00Z"}]
    )

    report = inspect_ohlcv(frame, expected_frequency="1h")

    assert report.blocking
    assert "OHLC_RELATION" in {finding.code for finding in report.findings}


def test_missing_bar_is_reported() -> None:
    frame = pd.DataFrame(
        [
            {"open": 1, "high": 1, "low": 1, "close": 1, "volume": 1, "event_time": "2026-01-01T00:00:00Z"},
            {"open": 1, "high": 1, "low": 1, "close": 1, "volume": 1, "event_time": "2026-01-01T02:00:00Z"},
        ]
    )

    report = inspect_ohlcv(frame, expected_frequency="1h")

    assert "TIME_GAP" in {finding.code for finding in report.findings}
```

- [ ] **Step 2: Implement report and checks**

Create `src/bian_quant/data/quality.py`:

```python
from pydantic import BaseModel
import pandas as pd

from bian_quant.data.contracts import QualityFinding, QualitySeverity


class QualityReport(BaseModel):
    findings: list[QualityFinding]

    @property
    def blocking(self) -> bool:
        return any(item.severity == QualitySeverity.BLOCKING for item in self.findings)


def inspect_ohlcv(frame: pd.DataFrame, *, expected_frequency: str) -> QualityReport:
    findings: list[QualityFinding] = []
    invalid = ~(
        (frame["high"] >= frame[["open", "close", "low"]].max(axis=1))
        & (frame["low"] <= frame[["open", "close", "high"]].min(axis=1))
    )
    if invalid.any():
        findings.append(
            QualityFinding(
                code="OHLC_RELATION",
                severity=QualitySeverity.BLOCKING,
                message="OHLC ordering is impossible",
                rows=frame.index[invalid].tolist(),
            )
        )
    if (frame["volume"] < 0).any():
        findings.append(
            QualityFinding(
                code="NEGATIVE_VOLUME",
                severity=QualitySeverity.BLOCKING,
                message="volume must be non-negative",
            )
        )
    times = pd.to_datetime(frame["event_time"], utc=True).sort_values()
    expected = pd.Timedelta(expected_frequency)
    if len(times) > 1 and (times.diff().dropna() > expected).any():
        findings.append(
            QualityFinding(
                code="TIME_GAP",
                severity=QualitySeverity.WARNING,
                message="one or more bars are missing",
            )
        )
    return QualityReport(findings=findings)
```

- [ ] **Step 3: Run tests and commit**

```bash
uv run pytest tests/unit/data/test_quality.py -q
git add src/bian_quant/data/quality.py tests/unit/data/test_quality.py
git commit -m "feat(data): enforce OHLCV quality gates"
```

### Task 5: Implement causal resampling and point-in-time queries

**Files:**
- Create: `src/bian_quant/data/resample.py`
- Create: `src/bian_quant/data/query.py`
- Test: `tests/unit/data/test_resample.py`
- Test: `tests/unit/data/test_point_in_time.py`

- [ ] **Step 1: Write leakage sentinel tests**

Create `tests/unit/data/test_point_in_time.py`:

```python
import pandas as pd

from bian_quant.data.query import as_known_at


def test_future_available_row_is_excluded() -> None:
    frame = pd.DataFrame(
        {
            "event_time": pd.to_datetime(["2026-01-01T00:00:00Z", "2026-01-01T01:00:00Z"]),
            "available_time": pd.to_datetime(["2026-01-01T01:00:00Z", "2026-01-01T02:00:00Z"]),
            "close": [100.0, 999.0],
        }
    )

    known = as_known_at(frame, pd.Timestamp("2026-01-01T01:30:00Z"))

    assert known["close"].tolist() == [100.0]
```

Create `tests/unit/data/test_resample.py` with four 1h bars and assert the 4h bar uses first open, maximum high, minimum low, last close, summed volume, and `available_time` equal to the latest source `available_time`.

- [ ] **Step 2: Implement query and resampling**

Create `src/bian_quant/data/query.py`:

```python
import pandas as pd


def as_known_at(frame: pd.DataFrame, decision_time: pd.Timestamp) -> pd.DataFrame:
    if decision_time.tzinfo is None:
        raise ValueError("decision_time must be timezone-aware")
    return frame.loc[pd.to_datetime(frame["available_time"], utc=True) <= decision_time].copy()
```

Create `src/bian_quant/data/resample.py`:

```python
import pandas as pd


def resample_ohlcv(frame: pd.DataFrame, *, rule: str) -> pd.DataFrame:
    indexed = frame.set_index(pd.to_datetime(frame["event_time"], utc=True))
    result = indexed.resample(rule, label="left", closed="left").agg(
        {
            "asset": "first",
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
            "available_time": "max",
            "ingested_at": "max",
            "source": "first",
        }
    )
    return result.dropna(subset=["open", "high", "low", "close"]).rename_axis("event_time").reset_index()
```

- [ ] **Step 3: Run tests and commit**

```bash
uv run pytest tests/unit/data/test_point_in_time.py tests/unit/data/test_resample.py -q
git add src/bian_quant/data tests/unit/data
git commit -m "feat(data): add causal queries and resampling"
```

### Task 6: Add immutable Binance public archive ingestion

**Files:**
- Create: `src/bian_quant/data/adapters/__init__.py`
- Create: `src/bian_quant/data/adapters/binance_archive.py`
- Create: `configs/universe/core.yaml`
- Test: `tests/unit/data/adapters/test_binance_archive.py`

- [ ] **Step 1: Write URL and raw-byte tests without network access**

Create `tests/unit/data/adapters/test_binance_archive.py`:

```python
from pathlib import Path

from bian_quant.data.adapters.binance_archive import archive_url, save_raw_bytes


def test_monthly_futures_kline_url() -> None:
    assert archive_url("BTCUSDT", "1h", 2025, 1).endswith(
        "/futures/um/monthly/klines/BTCUSDT/1h/BTCUSDT-1h-2025-01.zip"
    )


def test_raw_bytes_are_append_only(tmp_path: Path) -> None:
    target = tmp_path / "sample.zip"
    save_raw_bytes(target, b"first")
    try:
        save_raw_bytes(target, b"changed")
    except FileExistsError:
        pass
    else:
        raise AssertionError("raw evidence was overwritten")
```

- [ ] **Step 2: Implement adapter**

Create `src/bian_quant/data/adapters/binance_archive.py`:

```python
from pathlib import Path
from urllib.request import urlopen

BASE = "https://data.binance.vision/data/futures/um/monthly/klines"


def archive_url(asset: str, interval: str, year: int, month: int) -> str:
    filename = f"{asset}-{interval}-{year:04d}-{month:02d}.zip"
    return f"{BASE}/{asset}/{interval}/{filename}"


def save_raw_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(payload)


def download_month(path: Path, *, asset: str, interval: str, year: int, month: int) -> None:
    with urlopen(archive_url(asset, interval, year, month), timeout=60) as response:
        save_raw_bytes(path, response.read())
```

Create empty adapter `__init__.py` and `configs/universe/core.yaml`:

```yaml
core_assets:
  - BTCUSDT
  - ETHUSDT
base_interval: 1h
derived_intervals:
  - 4h
  - 1d
migration_asset_count_min: 5
migration_asset_count_max: 8
```

- [ ] **Step 3: Run offline tests**

```bash
uv run pytest tests/unit/data/adapters/test_binance_archive.py -q
```

- [ ] **Step 4: Run one explicit network smoke test**

Add a `@pytest.mark.network` test that downloads one known small monthly ZIP to `tmp_path`, then run:

```bash
uv run pytest -q -m network tests/unit/data/adapters/test_binance_archive.py
```

Expected: downloaded file begins with ZIP magic bytes `PK`. If Binance changes the archive contract, stop and record the upstream response; do not weaken raw immutability.

- [ ] **Step 5: Commit**

```bash
git add src/bian_quant/data/adapters configs/universe tests/unit/data/adapters
git commit -m "feat(data): ingest immutable Binance archive files"
```

### Task 7: Add Funding and OI archive ingestion

**Files:**
- Create: `src/bian_quant/data/adapters/binance_derivatives.py`
- Test: `tests/unit/data/adapters/test_binance_derivatives.py`

- [ ] **Step 1: Write exact archive-contract tests**

Assert these URLs:

```text
https://data.binance.vision/data/futures/um/monthly/fundingRate/BTCUSDT/BTCUSDT-fundingRate-2025-01.zip
https://data.binance.vision/data/futures/um/daily/metrics/BTCUSDT/BTCUSDT-metrics-2025-01-02.zip
```

Use in-memory ZIP fixtures to assert Funding parsing produces `event_time` from the funding timestamp and OI parsing produces `sum_open_interest`, `sum_open_interest_value`, long/short ratios, and source row timestamp. Assert unexpected columns fail with `DERIVATIVES_SCHEMA_CHANGED` instead of being ignored.

- [ ] **Step 2: Implement separate archive URL builders**

Create `funding_url(asset, year, month)` and `metrics_url(asset, date)`. Reuse the Raw append-only writer. Download matching `.CHECKSUM` files when available and verify the archive before parsing.

- [ ] **Step 3: Implement conservative availability rules**

- Funding: `available_time` equals the archive row's funding timestamp; downstream bars may consume it only at or after that instant.
- OI metrics: `available_time = event_time + 5 minutes`, recorded as assumption `BINANCE_METRICS_MAX_PUBLICATION_DELAY_5M`.
- Both use the actual local fetch time as `ingested_at` in Raw manifests; historical Canonical rebuilds reuse the saved Raw manifest time.

Changing an availability assumption requires a new Canonical snapshot ID and invalidates dependent Research snapshots.

- [ ] **Step 4: Add network smoke tests**

Mark them `network`; download the two 2025-01 fixtures above, verify ZIP magic and checksum when published, parse at least one row, and record source schema in test diagnostics.

```bash
uv run pytest tests/unit/data/adapters/test_binance_derivatives.py -q
uv run pytest tests/unit/data/adapters/test_binance_derivatives.py -q -m network
```

- [ ] **Step 5: Commit**

```bash
git add src/bian_quant/data/adapters/binance_derivatives.py tests/unit/data/adapters/test_binance_derivatives.py
git commit -m "feat(data): ingest funding and OI archives"
```

### Task 8: Add free external proxy adapters with revision-risk labels

**Files:**
- Create: `src/bian_quant/data/adapters/fear_greed.py`
- Create: `src/bian_quant/data/adapters/defillama.py`
- Create: `src/bian_quant/data/adapters/fred.py`
- Create: `src/bian_quant/data/external_policy.py`
- Test: `tests/unit/data/adapters/test_external.py`

- [ ] **Step 1: Write source parsing tests from frozen JSON/CSV fixtures**

Use local response fixtures for:

```text
https://api.alternative.me/fng/?limit=0&format=json
https://stablecoins.llama.fi/stablecoincharts/all
https://fred.stlouisfed.org/graph/fredgraph.csv?id=WALCL
```

Assert timestamps are UTC, numeric fields are parsed without locale dependence, original payload bytes are stored first, and HTTP/schema errors never generate empty successful datasets.

- [ ] **Step 2: Implement explicit evidence classes**

Create:

```python
class RevisionRisk(StrEnum):
    POINT_IN_TIME = "point_in_time"
    PUBLICATION_DELAY_ASSUMED = "publication_delay_assumed"
    BACKFILLED_REVISED = "backfilled_revised"
```

Canonical rows carry `revision_risk` and `availability_assumption`. Apply:

- Fear & Greed: daily timestamp with conservative `available_time = event_time + 24 hours`; risk `PUBLICATION_DELAY_ASSUMED`.
- DeFiLlama stablecoin supply/TVL history: `available_time = event_time + 24 hours`; risk `BACKFILLED_REVISED` because historical API responses may be revised.
- FRED current CSV: risk `BACKFILLED_REVISED`; it is not point-in-time macro evidence.

- [ ] **Step 3: Enforce evidence ceiling**

`external_policy.py` must reject any factor promotion above `observed` when one of its required datasets has `BACKFILLED_REVISED`. A future vintage/ALFRED adapter may lift the ceiling only with an explicit new dataset spec and leakage tests.

- [ ] **Step 4: Add mocked retry and failure tests**

For each adapter, test HTTP 429, timeout, invalid JSON/CSV, schema change, and partial response. Raw bytes from invalid responses may be stored for diagnosis but cannot receive a Canonical snapshot ID.

- [ ] **Step 5: Run and commit**

```bash
uv run pytest tests/unit/data/adapters/test_external.py -q
git add src/bian_quant/data/adapters src/bian_quant/data/external_policy.py tests/unit/data/adapters/test_external.py
git commit -m "feat(data): ingest labeled external proxies"
```

### Task 9: Build the point-in-time migration universe

**Files:**
- Create: `src/bian_quant/data/universe.py`
- Test: `tests/unit/data/test_universe.py`

- [ ] **Step 1: Write survivorship tests**

Use three synthetic assets: one listed before selection, one listed afterward with very high future volume, and one delisted before the next rebalance. Assert the future listing is absent from the earlier universe, the delisted asset remains in historical membership while eligible, and later data cannot rewrite an already published membership snapshot.

- [ ] **Step 2: Implement deterministic monthly selection**

At 00:00 UTC on the first day of each month:

1. Always include BTCUSDT and ETHUSDT as core assets.
2. Consider only perpetual contracts whose listing and delisting metadata were available at that time.
3. Require at least 180 completed daily bars before selection.
4. Exclude stablecoin/stablecoin pairs, leveraged tokens, wrapped duplicates, and assets with more than 1% missing 1h bars in the trailing 30 days.
5. Rank remaining assets by trailing 30-day median daily quote volume known at selection time.
6. Select the top eight; if fewer than five qualify, mark the migration universe insufficient and block cross-asset promotion rather than lowering the rule.

Persist each month as an immutable Research snapshot containing selection time, asset, rank, eligibility metrics, parent dataset IDs, and rule version.

- [ ] **Step 3: Run and commit**

```bash
uv run pytest tests/unit/data/test_universe.py -q
git add src/bian_quant/data/universe.py tests/unit/data/test_universe.py
git commit -m "feat(data): build point-in-time migration universe"
```

## Plan 01 exit gate

- [ ] Contracts reject naive or impossible timestamps.
- [ ] Dataset IDs cannot be reused with different content.
- [ ] Legacy import is byte-deterministic for fixed inputs and `ingested_at`.
- [ ] Blocking OHLC defects stop publication.
- [ ] Leakage sentinel excludes records unavailable at decision time.
- [ ] Resampling preserves causal availability.
- [ ] Raw downloader refuses overwrite and passes one explicit network smoke test.
- [ ] Funding and OI archives have explicit publication timing assumptions.
- [ ] Backfilled external sources carry a revision-risk ceiling and cannot silently become approved alpha.
- [ ] Historical migration membership is built from information available at each monthly selection date.
- [ ] Default test suite remains network-free.
