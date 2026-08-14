# Local Data Availability Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (- [ ]) syntax for tracking.

**Goal:** 仅从已验证的本地 Raw artifacts 补齐当前 popular-universe source plan 缺失的 Canonical 输入，并以真实 preflight 证明恢复仍被唯一的未授权 TONUSDT Funding Raw 缺口阻止。

**Architecture:** data/local_availability_repair.py 只消费 current source plan、已验证 Raw artifact、Canonical builder 和 Catalog。它为当前 plan path 缺失的 source 创建新的内容寻址 Canonical Parquet/manifest/Catalog 行，绝不修改旧条目或 research snapshots。local_snapshot_recovery.py 仍是唯一的 research snapshot publisher；本计划结束时只重跑其 preflight。

**Tech Stack:** Python 3.11、pandas、PyArrow、Pydantic v2、SQLite、pytest、Ruff、mypy。

---

## 已确认事实

2026-08-14 的真实 preflight 通过 14,879 份 Canonical 输入，仍有 17 项 blocker：

- 16 个 daily 1D OHLCV Canonical 输入缺失，日期均为 2026-07-26，资产为 ADAUSDT、APTUSDT、AVAXUSDT、BCHUSDT、BNBUSDT、BTCUSDT、DOGEUSDT、ETHUSDT、LINKUSDT、LTCUSDT、NEARUSDT、SOLUSDT、SUIUSDT、TONUSDT、TRXUSDT、XRPUSDT。
- TONUSDT 2026-07 monthly Funding 的 Raw ZIP 和 sidecar manifest 均不存在。

抽样核对确认：上述 16 个 OHLCV source 的 Raw ZIP 与 manifest 已在 config.raw_root；因此它们可在完全离线模式修复。TONUSDT Funding 不在本计划授权范围。

## 强制规则与停止门

每个 Task 开始时完整阅读 docs/AILY_EXECUTION_RULES.md、docs/contracts/local-snapshot-recovery-contract.md、docs/evidence/2026-08-14-local-snapshot-recovery-run.md 和本计划，并运行：

~~~powershell
git status --short --branch
git log --oneline -5
git diff --stat
git diff --check
~~~

- .superpowers/ 是用户文件，禁止删除、暂存、格式化或修改。
- 禁止 HTTP、下载器、API Key、账户、订单、WebSocket、paper、live、Holdout、Candidate/Approved 状态变更和 main 合并。
- 不允许直接编辑 SQLite、复制旧 Catalog JSON、覆盖旧 Canonical/Raw 文件或复用旧 snapshot ID。
- 每项 Raw 必须先由 reuse_verified_artifact(path, expected=source.raw_identity) 验证。Raw ZIP 或 sidecar 缺失时记录 RAW_ARTIFACT_INCOMPLETE 并停止该项；不得重建 sidecar、不得猜测哈希。
- 只允许 publish Canonical layer；不得调用 recover_local_dual_horizon_snapshots 或 analyze_cataloged_dual_horizon，直到最终 preflight 为 READY。
- 任一新 Canonical entry 必须放在 current plan hash 对应的 canonical_plan_path，manifest config 只含 identity_key 和来自已验证 Raw manifest 的 raw_sha256。

## 文件边界

| 文件 | 变更 | 职责 |
|---|---|---|
| src/bian_quant/data/acquisition.py | 修改 | 公开 source_plan_hash(SourcePlanAudit)，由所有 data adapter 共用。 |
| src/bian_quant/data/dual_horizon.py | 修改 | 改用公开 hash helper；不改变 acquisition、下载或 research publishing。 |
| src/bian_quant/data/local_snapshot_recovery.py | 修改 | 改用公开 hash helper；不改变 strict resolver 或 recovery 行为。 |
| src/bian_quant/data/local_availability_repair.py | 新建 | 已验证本地 Raw → 新 Canonical 的窄适配器。 |
| tests/unit/data/test_local_availability_repair.py | 新建 | 验证、缺失 Raw 停止、幂等、冲突和旧文件不变。 |
| tests/unit/data/test_local_snapshot_recovery.py | 修改 | 验证 shared source_plan_hash 后仍能选中 current plan path。 |
| docs/contracts/local-data-availability-repair-contract.md | 新建 | 输入、输出、错误、写入及停止契约。 |
| docs/evidence/2026-08-15-local-data-availability-repair-run.md | 新建 | 真实离线修复和 preflight 结果。 |
| docs/implementation-notes.md | 修改 | 仅追加实际结果。 |

不修改 factors、regimes、backtest、reporting、dashboard、paper、research resolver 或任何 wire contract。依赖继续是 data → research/factors → reporting → dashboard。

### Task 1: 提取共享 source-plan identity

**Files:**

- Modify: src/bian_quant/data/acquisition.py
- Modify: src/bian_quant/data/dual_horizon.py
- Modify: src/bian_quant/data/local_snapshot_recovery.py
- Test: tests/unit/data/test_local_snapshot_recovery.py

- [ ] **Step 1: 写失败测试**

以同一 SourcePlanAudit 断言新公开函数的值固定，并与双周期 pipeline 使用的计划 identity 一致：

~~~python
plan = SourcePlanAudit((source_a, source_b), "a" * 64, ())
payload = {
    "availability_manifest_sha256": plan.availability_manifest_sha256,
    "object_identity_keys": [source_a.identity_key, source_b.identity_key],
}
expected = hashlib.sha256(
    json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
).hexdigest()
assert source_plan_hash(plan) == expected
~~~

- [ ] **Step 2: 确认失败**

~~~powershell
uv run pytest -p no:cov tests/unit/data/test_local_snapshot_recovery.py -q
~~~

Expected: source_plan_hash 尚未公开。

- [ ] **Step 3: 实现单一 hash API**

在 acquisition.py 的 SourcePlanAudit 定义后加入：

~~~python
def source_plan_hash(plan: SourcePlanAudit) -> str:
    payload = {
        "availability_manifest_sha256": plan.availability_manifest_sha256,
        "object_identity_keys": [source.identity_key for source in plan.objects],
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
~~~

在 dual_horizon.py 和 local_snapshot_recovery.py 导入这个函数，删除各自的重复实现。所有调用都传完整 SourcePlanAudit，不得只传 source tuple，也不得改变 hash payload 的键、顺序或 separator。

- [ ] **Step 4: 验证并提交**

~~~powershell
uv run pytest -p no:cov tests/unit/data/test_local_snapshot_recovery.py tests/integration/data/test_dual_horizon_pipeline.py -q
uv run ruff check src/bian_quant/data/acquisition.py src/bian_quant/data/dual_horizon.py src/bian_quant/data/local_snapshot_recovery.py tests/unit/data/test_local_snapshot_recovery.py
uv run ruff format --check src/bian_quant/data/acquisition.py src/bian_quant/data/dual_horizon.py src/bian_quant/data/local_snapshot_recovery.py tests/unit/data/test_local_snapshot_recovery.py
uv run mypy src/bian_quant
git add src/bian_quant/data/acquisition.py src/bian_quant/data/dual_horizon.py src/bian_quant/data/local_snapshot_recovery.py tests/unit/data/test_local_snapshot_recovery.py
git diff --cached --check
git commit -m "refactor(data): share source plan identity"
~~~

### Task 2: 已验证 Raw 的 Canonical repair adapter

**Files:**

- Create: src/bian_quant/data/local_availability_repair.py
- Create: tests/unit/data/test_local_availability_repair.py
- Create: docs/contracts/local-data-availability-repair-contract.md

- [ ] **Step 1: 写失败测试**

以 tmp_path 建立两个 daily OHLCV SourceObject：第一个有完整 ZIP/RawSourceManifest，第二个只保留 ZIP。测试必须覆盖：

~~~python
result = repair_verified_local_canonical_inputs(config)
assert result.status is LocalAvailabilityRepairStatus.BLOCKED
assert result.repaired_snapshot_ids == (expected_snapshot_id,)
assert result.blocked_reasons == (
    f"RAW_ARTIFACT_INCOMPLETE:{missing_manifest_source.identity_key}",
)
assert old_catalog_bytes == catalog_path.read_bytes()
assert old_canonical_bytes == old_path.read_bytes()
~~~

再执行一次相同 repair，断言第一个 source 返回相同 Canonical ID、文件 bytes 和 Catalog row；不得新增第二个 ID。添加 content conflict fixture：current plan path 已有不同内容时，必须抛 CANONICAL_PARTITION_CONFLICT，不得覆盖。

- [ ] **Step 2: 确认失败**

~~~powershell
uv run pytest -p no:cov tests/unit/data/test_local_availability_repair.py -q
~~~

Expected: module 和 repair_verified_local_canonical_inputs 不存在。

- [ ] **Step 3: 实现固定契约**

创建以下类型：

~~~python
class LocalAvailabilityRepairStatus(StrEnum):
    REPAIRED = "repaired"
    BLOCKED = "blocked"

@dataclass(frozen=True)
class LocalAvailabilityRepairResult:
    status: LocalAvailabilityRepairStatus
    repaired_snapshot_ids: tuple[str, ...]
    blocked_reasons: tuple[str, ...]
    cutoff_evidence: tuple[CutoffEvidence, ...]

def repair_verified_local_canonical_inputs(
    config: DualHorizonAcquisition,
) -> LocalAvailabilityRepairResult:
    plan = build_source_plan_audit(config)
    plan_hash = source_plan_hash(plan)
    catalog = DatasetCatalog(config.catalog_path)
    # Iterate in source.identity_key order.
~~~

对每个 source，先计算 current canonical_plan_path。只有该路径尚未有已注册的同一 immutable manifest 时才处理；已有正确 row 必须跳过并保持原样。调用 reuse_verified_artifact(raw_path, expected=source.raw_identity)。异常转换为 RAW_ARTIFACT_INCOMPLETE:<identity_key>、RAW_HASH_MISMATCH:<identity_key> 或 RAW_IDENTITY_MISMATCH:<identity_key>，继续处理其余本地 source。

对已验证 source 按 dataset 调用已有 canonicalize_ohlcv_zip、canonicalize_funding_zip 或 canonicalize_metrics_zip；ingested_at 取 verified Raw manifest.fetched_at。调用 clip_to_evidence_cutoff，若 eligible 空则记录 EVIDENCE_CUTOFF_VIOLATION:<identity_key>；否则用 write_canonical_partition 写 current canonical_plan_path。使用 canonical_snapshot_id 和下面的不可变 manifest 注册：

~~~python
DatasetManifest(
    snapshot_id=canonical_snapshot_id(source, content_sha=content_sha, plan_hash=plan_hash),
    layer=DatasetLayer.CANONICAL,
    name=f"canonical-{source.dataset.value}-{source.interval}",
    content_sha256=content_sha,
    row_count=len(eligible_frame),
    min_event_time=eligible_frame["event_time"].min(),
    max_event_time=eligible_frame["event_time"].max(),
    min_available_time=eligible_frame["available_time"].min(),
    max_available_time=eligible_frame["available_time"].max(),
    parent_snapshot_ids=[f"raw-{verified.manifest.content_sha256}"],
    config_json=json.dumps(
        {"identity_key": source.identity_key, "raw_sha256": verified.manifest.content_sha256},
        sort_keys=True,
        separators=(",", ":"),
    ),
)
~~~

不得扫描旧 plan= 目录作为输入、不得写 research_root、不得创建 source evidence run。结果按 repaired snapshot ID 和 blocker 字典序稳定排序。

在契约文档中固定所有类型、Raw 验证顺序、当前 plan path、manifest 字段、可写目录、错误码和 TONUSDT 下载停止门。

- [ ] **Step 4: 验证并提交**

~~~powershell
uv run pytest -p no:cov tests/unit/data/test_local_availability_repair.py tests/unit/data/test_snapshots.py tests/unit/data/adapters/test_resumable_raw.py -q
uv run ruff check src/bian_quant/data/local_availability_repair.py tests/unit/data/test_local_availability_repair.py
uv run ruff format --check src/bian_quant/data/local_availability_repair.py tests/unit/data/test_local_availability_repair.py
uv run mypy src/bian_quant
git add src/bian_quant/data/local_availability_repair.py tests/unit/data/test_local_availability_repair.py docs/contracts/local-data-availability-repair-contract.md
git diff --cached --check
git commit -m "feat(data): repair verified local canonical inputs"
~~~

### Task 3: 真实离线 repair、preflight 与证据

**Files:**

- Create: docs/evidence/2026-08-15-local-data-availability-repair-run.md
- Modify: docs/implementation-notes.md

- [ ] **Step 1: 记录基线并运行 repair**

先生成 current plan path 下已有 Canonical 文件、主 Catalog 与 research_root 文件的 SHA-256 清单。只在屏幕输出或本 Task 的新 evidence 中保存该清单，绝不改旧 artifact。

~~~powershell
@'
from pathlib import Path
from bian_quant.data.acquisition import DualHorizonAcquisition
from bian_quant.data.local_availability_repair import repair_verified_local_canonical_inputs
root = Path.cwd()
config = DualHorizonAcquisition.from_yaml(root / "configs/experiments/popular_universe_100u.yaml")
result = repair_verified_local_canonical_inputs(config)
print(result.status)
print(result.repaired_snapshot_ids)
print(result.blocked_reasons)
print([item.model_dump(mode="json") for item in result.cutoff_evidence])
'@ | uv run python -
~~~

Expected: exactly 16 new daily 1D Canonical snapshot IDs and exactly one blocker, RAW_ARTIFACT_INCOMPLETE for TONUSDT July Funding. If the source inventory differs, record the exact observed results and do not invent this expected count.

- [ ] **Step 2: Re-run strict recovery preflight**

~~~powershell
@'
from pathlib import Path
from bian_quant.data.acquisition import DualHorizonAcquisition
from bian_quant.data.local_snapshot_recovery import preflight_local_snapshot_recovery
root = Path.cwd()
config = DualHorizonAcquisition.from_yaml(root / "configs/experiments/popular_universe_100u.yaml")
result = preflight_local_snapshot_recovery(config)
print(result.status)
print(len(result.inputs))
print(result.blocked_reasons)
'@ | uv run python -
~~~

Expected: BLOCKED only by RAW_LINEAGE_MISSING:funding|TONUSDT|native|monthly|2026-07-01T00:00:00+00:00. Do not call recovery_local_dual_horizon_snapshots when any blocker remains.

- [ ] **Step 3: Verify immutability, write evidence and gate**

Compare the baseline to the final SHA-256 map. Only the 16 new current-plan Canonical Parquet files and their new Catalog rows may differ; existing Canonical, research and old Catalog evidence must match byte-for-byte.

The evidence must contain real command output, repaired IDs, cutoff evidence, the remaining TONUSDT blocker, old-file comparison result, and:

~~~text
network_downloads=false
research_snapshot_publisher_called=false
development_analysis_called=false
holdout_accessed=false
paper_trading=false
live_trading=false
~~~

~~~powershell
uv run pytest -p no:cov tests/unit/data/test_local_availability_repair.py tests/unit/data/test_local_snapshot_recovery.py tests/unit/data/test_snapshots.py tests/integration/data/test_dual_horizon_pipeline.py tests/integration/data/test_local_snapshot_recovery.py tests/unit/research/test_operations.py -q
uv run ruff check src/bian_quant/data/acquisition.py src/bian_quant/data/dual_horizon.py src/bian_quant/data/local_snapshot_recovery.py src/bian_quant/data/local_availability_repair.py tests/unit/data/test_local_availability_repair.py tests/unit/data/test_local_snapshot_recovery.py
uv run ruff format --check src/bian_quant/data/acquisition.py src/bian_quant/data/dual_horizon.py src/bian_quant/data/local_snapshot_recovery.py src/bian_quant/data/local_availability_repair.py tests/unit/data/test_local_availability_repair.py tests/unit/data/test_local_snapshot_recovery.py
uv run mypy src/bian_quant
git diff --check
git add docs/evidence/2026-08-15-local-data-availability-repair-run.md docs/implementation-notes.md
git diff --cached --check
git commit -m "docs(data): record local availability repair"
git push -u origin codex/relative-funding-pressure-factor
~~~

## Operational checklist

### Before any edit

- [ ] Read the four required documents and confirm branch plus .superpowers/ status.
- [ ] Confirm all 16 daily OHLCV Raw ZIP files and sidecar manifests with reuse_verified_artifact.
- [ ] Confirm TONUSDT Funding ZIP and sidecar are both absent; no network call has occurred.
- [ ] Record current source plan hash and the 17 preflight blockers.

### For every Canonical repair

- [ ] Source identity belongs to the current source plan and current plan= directory.
- [ ] Raw sidecar hash and Raw identity pass verification.
- [ ] Canonicalizer matches the source dataset and preserves UTC available_time semantics.
- [ ] Eligible cutoff frame is nonempty.
- [ ] New Parquet content SHA matches immutable DatasetManifest.
- [ ] Parent lineage is exactly raw-<verified content SHA>.
- [ ] Catalog registration succeeds without replacing an existing row.

### Before stopping

- [ ] Exactly 16 local items repaired, or the evidence states the actual count and all reasons.
- [ ] Recovery preflight remains blocked only by TONUSDT Funding Raw lineage.
- [ ] No research snapshot, development analysis, Holdout ledger, paper or live action occurred.
- [ ] Existing artifact hashes were compared; new evidence includes raw terminal output.
- [ ] pytest, Ruff, format, mypy and git diff --check passed.
- [ ] Current branch pushed; main is not merged.

## Separate authorization gate: TONUSDT Funding

This plan does not authorize network access. After Task 3, create a new, narrow plan only if the user explicitly approves a download of this single object:

~~~text
funding|TONUSDT|native|monthly|2026-07-01T00:00:00+00:00
https://data.binance.vision/data/futures/um/monthly/fundingRate/TONUSDT/TONUSDT-fundingRate-2026-07.zip
~~~

That future plan must use the existing verified downloader to create the Raw ZIP and source manifest atomically, verify identity/content hash, publish only its current-plan Canonical partition, rerun strict preflight, and stop before research snapshot recovery unless the preflight is READY.

## Self-review

- [x] The 16 local repairs and the missing TONUSDT network acquisition are separated by an explicit authorization gate.
- [x] Every write uses existing immutable Raw/Canonical/Catalog paths; no hand-edited SQLite or historical artifact mutation is permitted.
- [x] New types, function names, error codes, tests, evidence and final commands are consistent across the plan.
- [x] The plan has no unspecified implementation step and does not authorize Holdout, paper, live, dashboard changes or main merge.
