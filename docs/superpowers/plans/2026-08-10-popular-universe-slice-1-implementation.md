# Popular Universe Slice 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (- [ ]) syntax for tracking.

**Goal:** Make the 16-asset popular-universe acquisition complete without requesting verifiably pre-listing archives, while preserving post-listing data and quality gates.

**Architecture:** A versioned availability manifest records verified archive periods at asset, data-set, and month/day granularity. An offline bootstrap creates it from raw objects. The existing tuple-returning plan API remains intact; a companion audit supplies manifest lineage and omitted-period evidence to artifacts.

**Tech Stack:** Python 3.11, Pydantic v2, PyYAML, pandas, Typer, pytest, Ruff, mypy.

---

## File structure

- Create: src/bian_quant/data/archive_availability.py — immutable manifest, canonical hash, verified-raw bootstrap, and source-plan audit types.
- Modify: src/bian_quant/data/acquisition.py — configuration, manifest loading, object-level period filtering.
- Modify: src/bian_quant/data/dual_horizon.py — acquisition, quality, and snapshot lineage.
- Modify: src/bian_quant/cli.py — offline bootstrap command.
- Create: configs/data/popular_universe_archive_availability.yaml — reviewed production evidence.
- Modify: configs/experiments/popular_universe_100u.yaml — manifest reference.
- Create: tests/unit/data/test_archive_availability.py — models and bootstrap.
- Modify: tests/unit/data/test_source_plan.py — crop and hash behavior.
- Modify: tests/integration/data/test_dual_horizon_pipeline.py — artifact behavior and post-boundary 404.
- Create: tests/integration/data/test_popular_universe_availability_real_raw.py — local actual-raw regression.

### Task 1: Availability models and offline bootstrap

**Files:**
- Create: src/bian_quant/data/archive_availability.py
- Create: tests/unit/data/test_archive_availability.py

- [x] **Step 1: Write failing model tests**

    def test_duplicate_availability_key_is_rejected() -> None:
        with pytest.raises(ValueError, match="duplicate availability entry"):
            ArchiveAvailabilityManifest.model_validate(
                {"rule_version": "popular-universe-availability-v1", "entries": [ENTRY, ENTRY]}
            )

    def test_hash_is_stable_when_yaml_key_order_changes(tmp_path: Path) -> None:
        assert _load_written_manifest(tmp_path, ordered=False).content_sha256 == (
            _load_written_manifest(tmp_path, ordered=True).content_sha256
        )

- [ ] **Step 2: Run the test to verify it fails**

  Run: uv run pytest tests/unit/data/test_archive_availability.py -q

  Expected: collection fails because the archive_availability module does not exist.

- [x] **Step 3: Implement the immutable data contract**

    class ArchiveAvailabilityEntry(BaseModel):
        model_config = ConfigDict(frozen=True)
        asset: str
        dataset: SourceDataset
        granularity: SourceGranularity
        first_available_period: datetime
        evidence_identity_key: str
        evidence_url: str
        evidence_content_sha256: str
        first_event_time: datetime

    class ArchiveAvailabilityManifest(BaseModel):
        model_config = ConfigDict(frozen=True)
        rule_version: Literal["popular-universe-availability-v1"]
        entries: tuple[ArchiveAvailabilityEntry, ...]

        @property
        def content_sha256(self) -> str:
            encoded = json.dumps(
                self.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
            return hashlib.sha256(encoded).hexdigest()

        def entry_for(
            self, asset: str, dataset: SourceDataset, granularity: SourceGranularity
        ) -> ArchiveAvailabilityEntry:
            matches = [
                entry
                for entry in self.entries
                if (entry.asset, entry.dataset, entry.granularity)
                == (asset, dataset, granularity)
            ]
            if len(matches) != 1:
                raise ValueError("ARCHIVE_AVAILABILITY_MISSING")
            return matches[0]

  Validate UTC timestamps, normalize monthly periods to the first UTC day of that month and daily periods to UTC midnight. Reject duplicate asset/dataset/granularity keys. entry_for raises ValueError with ARCHIVE_AVAILABILITY_MISSING if absent.

- [x] **Step 4: Write failing raw-bootstrap boundary tests**

    def test_bootstrap_uses_monthly_source_period_not_first_event_time(tmp_path: Path) -> None:
        raw_root = _seed_verified_monthly_ohlcv(tmp_path, "APTUSDT", "2022-10")
        manifest = bootstrap_archive_availability(raw_root, assets=("APTUSDT",))
        entry = manifest.entry_for(
            "APTUSDT", SourceDataset.OHLCV, SourceGranularity.MONTHLY
        )
        assert entry.first_available_period == datetime(2022, 10, 1, tzinfo=UTC)
        assert entry.first_event_time > entry.first_available_period

    def test_bootstrap_rejects_unverified_evidence(tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="ARCHIVE_AVAILABILITY_EVIDENCE_MISSING"):
            bootstrap_archive_availability(_seed_incomplete_raw(tmp_path), assets=("APTUSDT",))

- [x] **Step 5: Implement bootstrap with no network calls**

    def bootstrap_archive_availability(
        raw_root: Path, *, assets: tuple[str, ...]
    ) -> ArchiveAvailabilityManifest:
        candidates = _verified_candidates(raw_root, assets=assets)
        entries = tuple(_entry_from_candidate(item) for item in _earliest_by_key(candidates))
        _require_expected_keys(entries, assets=assets)
        return ArchiveAvailabilityManifest(
            rule_version="popular-universe-availability-v1", entries=entries
        )

  Discover only zip.manifest.json files. Reconstruct RawSourceIdentity from each stored RawSourceManifest and call reuse_verified_artifact on its sibling zip. Derive month/day granularity from source_period, dispatch to the existing canonicalizer, and preserve minimum event_time only as evidence. Do not import or call BinanceDownloader, urlopen, or any network client.

- [ ] **Step 6: Verify and commit Task 1**

  Run: uv run pytest tests/unit/data/test_archive_availability.py -q

  Expected: PASS.

  Run: git add src/bian_quant/data/archive_availability.py tests/unit/data/test_archive_availability.py; git commit -m "feat(data): bootstrap archive availability manifest"

### Task 2: Crop popular plans without changing the locked three-asset plan

**Files:**
- Modify: src/bian_quant/data/acquisition.py
- Modify: tests/unit/data/test_source_plan.py

- [x] **Step 1: Write failing source-plan tests**

    def test_popular_plan_keeps_first_existing_month_and_excludes_prior_months(tmp_path: Path) -> None:
        config = _popular_config_with_availability(tmp_path, apt_month="2022-10")
        keys = {item.identity_key for item in build_source_plan(config)}
        assert "ohlcv|APTUSDT|1d|monthly|2022-09-01T00:00:00+00:00" not in keys
        assert "ohlcv|APTUSDT|1d|monthly|2022-10-01T00:00:00+00:00" in keys

    def test_three_asset_plan_stays_locked() -> None:
        assert len(build_source_plan(DualHorizonAcquisition.from_yaml(CONFIG))) == 3117

- [ ] **Step 2: Run the tests to verify failure**

  Run: uv run pytest tests/unit/data/test_source_plan.py -q

  Expected: FAIL because availability configuration and filtering are absent.

- [x] **Step 3: Add configuration and audit helper**

    @dataclass(frozen=True)
    class SourcePlanAudit:
        objects: tuple[SourceObject, ...]
        availability_manifest_sha256: str | None
        pre_listing_exclusions: tuple[dict[str, object], ...]

    def build_source_plan_audit(config: DualHorizonAcquisition) -> SourcePlanAudit:
        candidates = _build_unfiltered_source_plan(config)
        if config.archive_availability_path is None:
            return SourcePlanAudit(candidates, None, ())
        manifest = ArchiveAvailabilityManifest.from_yaml(config.archive_availability_path)
        kept, excluded = _filter_pre_listing_periods(candidates, manifest)
        return SourcePlanAudit(tuple(kept), manifest.content_sha256, tuple(excluded))

    def build_source_plan(config: DualHorizonAcquisition) -> tuple[SourceObject, ...]:
        return build_source_plan_audit(config).objects

  Add archive_availability_path: Path | None = None to DualHorizonAcquisition. Require it when universe_policy is present and reject it for the fixed three-asset configuration. Generate candidate objects using the current loops, then filter only an object whose period_start is earlier than its matching frozen availability period. Record every omitted candidate with identity_key, asset, dataset, granularity, and reason PRE_LISTING_EXCLUDED. Objects on or after the boundary stay in plan.

- [x] **Step 4: Add plan identity coverage**

  Extend source_plan_payload with availability_manifest_sha256 and pre_listing_exclusions while retaining all established count and objects fields. Add a test that changing an evidence SHA changes the popular plan payload. This changes the pipeline plan hash without changing the legacy three-asset plan.

- [ ] **Step 5: Verify and commit Task 2**

  Run: uv run pytest tests/unit/data/test_source_plan.py tests/unit/data/test_acquisition.py -q

  Expected: PASS, including the 3,117-object legacy plan.

  Run: git add src/bian_quant/data/acquisition.py tests/unit/data/test_source_plan.py tests/unit/data/test_acquisition.py; git commit -m "feat(data): crop popular archive plan by availability"

### Task 3: Bootstrap CLI, reviewed manifest, and artifact lineage

**Files:**
- Modify: src/bian_quant/cli.py
- Modify: src/bian_quant/data/dual_horizon.py
- Create: configs/data/popular_universe_archive_availability.yaml
- Modify: configs/experiments/popular_universe_100u.yaml
- Modify: tests/integration/data/test_dual_horizon_pipeline.py

- [x] **Step 1: Write failing artifact tests**

    def test_artifacts_persist_manifest_hash_and_exclusions(tmp_path: Path) -> None:
        result = prepare_dual_horizon(
            _miniature_popular_config_with_availability(tmp_path),
            code_sha="a" * 40,
            downloader=FixtureDownloader(FIXTURES),
        )
        artifact = json.loads(result.acquisition_artifact.read_text(encoding="utf-8"))
        assert artifact["availability_manifest_sha256"]
        assert {row["reason"] for row in artifact["pre_listing_exclusions"]} == {
            "PRE_LISTING_EXCLUDED"
        }

    def test_post_boundary_404_remains_blocking(tmp_path: Path) -> None:
        result = prepare_dual_horizon(
            _miniature_popular_config_with_availability(tmp_path),
            code_sha="b" * 40,
            downloader=PostBoundary404Downloader(),
        )
        assert result.status == DualHorizonStatus.BLOCKED

- [ ] **Step 2: Run integration tests to verify failure**

  Run: uv run pytest tests/integration/data/test_dual_horizon_pipeline.py -q

  Expected: FAIL because availability fields are absent from pipeline artifacts.

- [x] **Step 3: Add a strictly offline bootstrap command**

    @app.command("bootstrap-archive-availability")
    def bootstrap_archive_availability(
        config: Annotated[Path, typer.Option("--config")],
        output: Annotated[Path, typer.Option("--output")],
    ) -> None:
        cfg = DualHorizonAcquisition.from_yaml(config)
        manifest = _bootstrap(cfg.raw_root, assets=cfg.assets)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            yaml.safe_dump(manifest.model_dump(mode="json"), sort_keys=True),
            encoding="utf-8",
        )
        typer.echo(manifest.content_sha256)

  Reject non-popular configs. It writes only the requested YAML and prints its hash.

- [x] **Step 4: Persist audit lineage**

  Construct plan_audit once in prepare_dual_horizon and use plan_audit.objects for acquisition. Add availability_manifest_sha256 and pre_listing_exclusions to data-acquisition.json and data-quality.json. Add availability_manifest_sha256 to snapshot_config_dict. Never add PRE_LISTING_EXCLUDED entries to blocked_periods.

- [ ] **Step 5: Generate, inspect, and reference the production manifest**

  Run: uv run bian-quant bootstrap-archive-availability --config configs/experiments/popular_universe_100u.yaml --output configs/data/popular_universe_archive_availability.yaml

  Expected: one SHA-256 and every required asset/dataset/granularity key. Inspect that every evidence URL and SHA originate from var/lake/raw/binance-futures-um-popular-v1, then add archive_availability_path: configs/data/popular_universe_archive_availability.yaml to the popular experiment YAML.

- [ ] **Step 6: Verify and commit Task 3**

  Run: uv run pytest tests/integration/data/test_dual_horizon_pipeline.py tests/unit/data/test_archive_availability.py -q

  Expected: PASS; fixture rerun still passes, artifacts record lineage, and post-boundary 404 blocks.

  Run: git add src/bian_quant/cli.py src/bian_quant/data/dual_horizon.py configs/data/popular_universe_archive_availability.yaml configs/experiments/popular_universe_100u.yaml tests/integration/data/test_dual_horizon_pipeline.py; git commit -m "feat(data): audit popular archive availability"

### Task 4: Real-data acceptance, without advancing to Slice 2

**Files:**
- Create: tests/integration/data/test_popular_universe_availability_real_raw.py

- [x] **Step 1: Add local real-raw regression**

    @pytest.mark.skipif(not RAW_ROOT.exists(), reason="popular raw archive not available locally")
    def test_bootstrap_has_all_required_keys() -> None:
        manifest = bootstrap_archive_availability(RAW_ROOT, assets=POPULAR_ASSETS)
        assert {(entry.asset, entry.dataset, entry.granularity) for entry in manifest.entries} == REQUIRED_KEYS

  REQUIRED_KEYS includes monthly and daily OHLCV, monthly Funding, and daily Metrics/OI for every seed asset. It excludes daily Funding because the production plan never requests it.

- [ ] **Step 2: Run the full offline gate**

  Run: uv run pytest tests/unit/data/test_archive_availability.py tests/unit/data/test_source_plan.py tests/integration/data/test_dual_horizon_pipeline.py tests/integration/data/test_popular_universe_availability_real_raw.py -q

  Run: uv run ruff check src/bian_quant/data/archive_availability.py src/bian_quant/data/acquisition.py src/bian_quant/data/dual_horizon.py src/bian_quant/cli.py tests/unit/data/test_archive_availability.py tests/unit/data/test_source_plan.py tests/integration/data/test_dual_horizon_pipeline.py tests/integration/data/test_popular_universe_availability_real_raw.py

  Run: uv run mypy src/bian_quant/data/archive_availability.py src/bian_quant/data/acquisition.py src/bian_quant/data/dual_horizon.py src/bian_quant/cli.py

  Expected: all commands succeed.

- [ ] **Step 3: Run the real Slice 1 command after the cutoff Funding archive is published**

  Run: $sha = git rev-parse HEAD; uv run bian-quant prepare-dual-horizon --config configs/experiments/popular_universe_100u.yaml --code-sha $sha --download

  Expected: exit code 0; both artifacts show passed; four snapshot IDs print; omitted periods are audit-only PRE_LISTING_EXCLUDED records.

- [ ] **Step 4: Verify acceptance artifacts and commit**

  Run: $root = 'var/artifacts/dual-horizon-popular-v1'; $acquisition = Get-ChildItem $root -Filter data-acquisition.json -Recurse | Sort-Object LastWriteTimeUtc -Descending | Select-Object -First 1; $quality = Get-ChildItem $root -Filter data-quality.json -Recurse | Sort-Object LastWriteTimeUtc -Descending | Select-Object -First 1; (Get-Content $acquisition.FullName -Raw | ConvertFrom-Json).status; (Get-Content $quality.FullName -Raw | ConvertFrom-Json).status

  Expected: both outputs are passed. Inspect all four cataloged snapshots and every daily popular-universe artifact; each member count must be 8 through 12.

  Run: git add tests/integration/data/test_popular_universe_availability_real_raw.py; git commit -m "test(data): verify popular archive availability"

  Report only Slice 1 status, the two artifact statuses, snapshot IDs, artifact directory, and any externally unavailable Funding-tail blocker. Do not start Slice 2.

## Plan self-review

- Coverage: Task 1 implements verified bootstrap; Task 2 provides per-asset/data-set/granularity plan cropping; Task 3 adds reviewed configuration and audit lineage; Task 4 validates unequal starts, 404 safety, real artifacts, and popular-pool member counts.
- Scope: no factor change, holdout, backtest, paper cycle, private endpoint, order, key, or execution logic appears in this plan.
- Interface consistency: ArchiveAvailabilityManifest, ArchiveAvailabilityEntry, SourcePlanAudit, build_source_plan_audit, and bootstrap_archive_availability are defined before later tasks use them.
