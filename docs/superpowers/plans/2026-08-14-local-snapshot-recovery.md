# Local Canonical Snapshot Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (- [ ]) syntax for tracking.

**Goal:** 仅用本机已有 Canonical 数据生成与当前代码身份一致的双周期 research snapshots，并只运行一次 development-only 筛选。

**Architecture:** 新的 data/local_snapshot_recovery.py 从 Catalog 精确解析 Canonical 输入，先给出零写入 preflight，再只通过既有 snapshot builders 发布新的内容寻址快照。research 保留 strict resolver，且把已通过的 source evidence 与本次解析的 snapshot IDs 精确绑定。

**Tech Stack:** Python 3.11、pandas、PyArrow、Pydantic v2、SQLite、pytest、Ruff、mypy。

---

## 强制边界

每个 Task 前先阅读 docs/AILY_EXECUTION_RULES.md、docs/superpowers/specs/2026-08-14-local-snapshot-recovery-design.md 和本计划，并运行：

~~~powershell
git status --short --branch
git log --oneline -5
git diff --stat
git diff --check
~~~

- .superpowers/ 是用户文件，绝不触碰。
- 只允许新建内容寻址 research Parquet、新 Catalog 行、当前运行 artifact 和本计划中的文档；不得修改旧 Parquet、manifest、Catalog 行、evidence、Raw 或 Canonical 文件。
- 禁止网络、下载器、API Key、账户、订单、WebSocket、paper、live、evaluate_candidate_holdout 和 holdout-access.sqlite。
- 不得放宽 resolve_dual_horizon_snapshots() 对 assets、macro_start、micro_start、as_of、code_sha 的精确匹配；不得手工编辑 SQLite 或挑选“最近”快照。
- preflight 有缺失、歧义、哈希不符、截止点违规或质量阻塞时，只写真实的 blocked evidence 并停止。

## 文件和契约边界

| 文件 | 变更 | 唯一职责 |
|---|---|---|
| src/bian_quant/data/popular_universe_artifacts.py | 新建 | 本地热门池 artifact 构建；只消费内存 Canonical 帧。 |
| src/bian_quant/data/local_snapshot_recovery.py | 新建 | Canonical preflight、恢复运行与 snapshot builder 适配。 |
| src/bian_quant/data/dual_horizon.py | 修改 | 复用抽出的热门池构建器，不改 Raw pipeline 行为。 |
| src/bian_quant/research/operations.py | 修改 | source evidence 与解析 snapshot IDs 绑定。 |
| tests/unit/data/test_local_snapshot_recovery.py | 新建 | preflight、哈希、截止点、幂等和不可变性。 |
| tests/integration/data/test_local_snapshot_recovery.py | 新建 | Canonical → recovery → strict resolver → development。 |
| tests/unit/research/test_operations.py | 修改 | 无关 source evidence 不能授权 analysis。 |
| docs/contracts/local-snapshot-recovery-contract.md | 新建 | 状态、错误码、血缘与禁止项。 |
| docs/evidence/2026-08-14-local-snapshot-recovery-run.md | 新建 | 本机真实运行证据。 |
| docs/implementation-notes.md | 修改 | 只追加真实状态。 |

不修改 factors/*、regimes/*、backtest/*、reporting/*、dashboard/*、research_protocol.py 或 wire contract。依赖方向保持 data → research/factors → reporting → dashboard。

每个 Canonical input 必须同时满足：

~~~text
Catalog name == canonical-{source.dataset.value}-{source.interval}
manifest.layer == canonical
manifest.config_json.identity_key == source.identity_key
唯一匹配，路径为文件，Parquet hash == manifest.content_sha256
event_time <= as_of 且 available_time <= as_of
~~~

四个主 snapshot 使用相同、非空、稳定排序的 Canonical snapshot ID 作为 parent lineage。三个 metrics-oi-delay-{5,10,15}m 的 parent 集合精确等于四个新主 snapshot ID 集合。

主 snapshot config_json 包含 resolver 的五个 identity 字段，再加：

~~~python
{
    "source_mode": "local-canonical-recovery-v1",
    "canonical_input_snapshot_ids": list(parent_snapshot_ids),
    "canonical_input_set_sha256": input_set_sha256,
    "popular_universe_artifact_ids": artifact_ids,
}
~~~

稳定错误码为 CANONICAL_INPUT_MISSING:<identity_key>、CANONICAL_INPUT_AMBIGUOUS:<identity_key>、CANONICAL_FILE_MISSING:<snapshot_id>、CANONICAL_CONTENT_HASH_MISMATCH:<snapshot_id>、CANONICAL_CUTOFF_VIOLATION:<identity_key> 和已有质量检查的 blocking code。

### Task 1: 抽取热门池 artifact 构建器

**Files:**

- Create: src/bian_quant/data/popular_universe_artifacts.py
- Modify: src/bian_quant/data/dual_horizon.py:377-608
- Test: tests/integration/data/test_dual_horizon_pipeline.py

- [ ] **Step 1: 写失败测试**

用同一 fixture 的 OHLCV/Funding/Metrics 和 config，比较当前 pipeline 与公共 build_popular_universe_artifacts() 的返回值及 popular-universe/*.json 原始 bytes：

~~~python
assert extracted.artifacts == existing.artifacts
assert extracted.shortages == existing.shortages
assert sorted(path.read_bytes() for path in extracted_dir.glob("*.json")) == sorted(
    path.read_bytes() for path in existing_dir.glob("*.json")
)
~~~

- [ ] **Step 2: 确认失败**

~~~powershell
uv run pytest -p no:cov tests/integration/data/test_dual_horizon_pipeline.py -q
~~~

Expected: 公共模块和函数尚不存在。

- [ ] **Step 3: 最小实现**

将 PopularUniverseBuildResult、listing 元数据、checkpoint 校验、shortage 检测和日循环完整迁入新模块。公共函数名与类型固定为 build_popular_universe_artifacts(config: DualHorizonAcquisition, ohlcv: pd.DataFrame, funding: pd.DataFrame, metrics: pd.DataFrame) -> PopularUniverseBuildResult，以及 has_funding_days_shortage(artifact: dict[str, object], partial_assets: list[str]) -> bool。

保留 UTF-8、stable JSON、原子 .tmp → replace、UTC 日边界和 POPULAR_UNIVERSE_INSUFFICIENT 语义。dual_horizon.py 仅导入新 API，并删除旧的重复实现；不得改变 artifact schema。

- [ ] **Step 4: 验证并提交**

~~~powershell
uv run pytest -p no:cov tests/integration/data/test_dual_horizon_pipeline.py -q
uv run ruff check src/bian_quant/data/popular_universe_artifacts.py src/bian_quant/data/dual_horizon.py tests/integration/data/test_dual_horizon_pipeline.py
uv run ruff format --check src/bian_quant/data/popular_universe_artifacts.py src/bian_quant/data/dual_horizon.py tests/integration/data/test_dual_horizon_pipeline.py
git add src/bian_quant/data/popular_universe_artifacts.py src/bian_quant/data/dual_horizon.py tests/integration/data/test_dual_horizon_pipeline.py
git diff --cached --check
git commit -m "refactor(data): share popular universe artifacts"
~~~

### Task 2: Canonical 只读 preflight 和契约

**Files:**

- Create: src/bian_quant/data/local_snapshot_recovery.py
- Create: tests/unit/data/test_local_snapshot_recovery.py
- Create: docs/contracts/local-snapshot-recovery-contract.md

- [ ] **Step 1: 写失败测试**

在 tmp_path 创建真实 Catalog/Parquet 的最小 Canonical source-plan inputs，覆盖 READY、缺失、重复 identity、篡改文件、future available_time 与无写入性：

~~~python
result = preflight_local_snapshot_recovery(config)
assert result.status is LocalSnapshotRecoveryStatus.READY
assert result.parent_snapshot_ids == tuple(sorted(expected_snapshot_ids))
assert result.blocked_reasons == ()
assert "CANONICAL_INPUT_AMBIGUOUS:" in ambiguous.blocked_reasons[0]
assert "CANONICAL_CONTENT_HASH_MISMATCH:" in tampered.blocked_reasons[0]
assert "CANONICAL_CUTOFF_VIOLATION:" in future_row.blocked_reasons[0]
assert bytes_before == bytes_after
~~~

bytes_before 与 bytes_after 是所有已有 Canonical/旧 research 文件的 SHA-256 映射；同时断言未创建 Parquet、delay_catalog.sqlite 或 Holdout ledger。

- [ ] **Step 2: 确认失败**

~~~powershell
uv run pytest -p no:cov tests/unit/data/test_local_snapshot_recovery.py -q
~~~

Expected: 恢复模块尚不存在。

- [ ] **Step 3: 实现只读 API**

~~~python
class LocalSnapshotRecoveryStatus(StrEnum):
    READY = "ready"
    BLOCKED = "blocked"
    RECOVERED = "recovered"

@dataclass(frozen=True)
class CanonicalRecoveryInput:
    source: SourceObject
    entry: CatalogEntry
    frame: pd.DataFrame
    cutoff: CutoffEvidence

@dataclass(frozen=True)
class LocalSnapshotRecoveryPreflight:
    status: LocalSnapshotRecoveryStatus
    inputs: tuple[CanonicalRecoveryInput, ...]
    parent_snapshot_ids: tuple[str, ...]
    input_set_sha256: str | None
    blocked_reasons: tuple[str, ...]

~~~

在上面类型之后，实现 preflight_local_snapshot_recovery(config: DualHorizonAcquisition) -> LocalSnapshotRecoveryPreflight。遍历 build_source_plan_audit(config).objects，只从 DatasetCatalog(config.catalog_path) 的同名条目按 identity_key 精确选一个 Canonical entry。验证文件、完整 hash、必需列、clip_to_evidence_cutoff 与既有 OHLCV/Funding/OI 质量检查。任何 post_cutoff_rows_excluded != 0 必须阻塞，不能截断后继续。输入 set hash 只由 source identity、canonical snapshot ID 与 content SHA 的 canonical JSON 计算。

本函数不得调用 publish_snapshot、register、mkdir、write_text、downloader 或网络。同步写契约文档，逐项列出 types、状态、错误码、lineage、幂等与禁止项，不得声称真实恢复完成。

- [ ] **Step 4: 验证并提交**

~~~powershell
uv run pytest -p no:cov tests/unit/data/test_local_snapshot_recovery.py tests/unit/data/test_snapshots.py -q
uv run ruff check src/bian_quant/data/local_snapshot_recovery.py tests/unit/data/test_local_snapshot_recovery.py
uv run ruff format --check src/bian_quant/data/local_snapshot_recovery.py tests/unit/data/test_local_snapshot_recovery.py
uv run mypy src/bian_quant
git add src/bian_quant/data/local_snapshot_recovery.py tests/unit/data/test_local_snapshot_recovery.py docs/contracts/local-snapshot-recovery-contract.md
git diff --cached --check
git commit -m "feat(data): preflight local snapshot recovery"
~~~

### Task 3: 受血缘约束的恢复与 research gate

**Files:**

- Modify: src/bian_quant/data/local_snapshot_recovery.py
- Modify: src/bian_quant/research/operations.py:108-115,562-581
- Modify: tests/unit/data/test_local_snapshot_recovery.py
- Modify: tests/unit/research/test_operations.py
- Create: tests/integration/data/test_local_snapshot_recovery.py

- [ ] **Step 1: 写失败测试**

~~~python
result = recover_local_dual_horizon_snapshots(config, code_sha=CODE_SHA)
assert result.status is LocalSnapshotRecoveryStatus.RECOVERED
assert {item.name for item in result.snapshots} == set(REQUIRED_SNAPSHOTS)
assert resolve_dual_horizon_snapshots(config, code_sha=CODE_SHA).snapshot_ids == result.snapshot_ids
assert not (config.artifact_root / "holdout-access.sqlite").exists()
~~~

第二次调用必须返回同一 IDs 且新文件 bytes 不变。建立一个同 code_sha、但 acquisition JSON 的 snapshot_ids 不相等的 passed source run；analysis 必须返回 blocked/SOURCE_EVIDENCE_MISSING。改成精确 ID 集才可继续 development。集成测试完整运行 preflight → recover → resolve → analyze_cataloged_dual_horizon，不得 monkeypatch 网络。

- [ ] **Step 2: 确认失败**

~~~powershell
uv run pytest -p no:cov tests/unit/data/test_local_snapshot_recovery.py tests/unit/research/test_operations.py tests/integration/data/test_local_snapshot_recovery.py -q
~~~

Expected: 恢复 API 与 source-evidence/snapshot binding 不存在。

- [ ] **Step 3: 最小实现**

~~~python
@dataclass(frozen=True)
class LocalSnapshotRecoveryResult:
    run_id: str
    status: LocalSnapshotRecoveryStatus
    snapshots: tuple[DatasetManifest, ...]
    delay_snapshot_ids: dict[int, str]
    acquisition_artifact: Path
    quality_artifact: Path
    blocked_reasons: tuple[str, ...]

~~~

在上面类型之后，实现 recover_local_dual_horizon_snapshots(config: DualHorizonAcquisition, *, code_sha: str) -> LocalSnapshotRecoveryResult。先运行 preflight。非 READY 时创建新的 dual_horizon_derivatives run，并写 schema 完整的 blocked acquisition/quality JSON（source_mode="local-canonical-recovery-v1"、真实原因、空 snapshot IDs），将 run 标为 BLOCKED 后返回，绝不写 research Catalog。

READY 时按 dataset 合并已验证帧，分别以 event_time >= macro_start 与 event_time >= micro_start 产生 macro/micro OHLCV；调用 Task 1 公共热门池构建器，shortage 即 blocked；以同一 Canonical parent tuple 和固定 identity JSON 调用既有 build_macro_snapshots、build_micro_snapshots，仅四个成功后调用 build_delay_views。成功 evidence 必须含状态、source mode、主/延迟 snapshot IDs、Canonical IDs/set hash、cutoff evidence、热门池 IDs、质量报告及空 partial exclusions。

将 _load_acquisition_evidence 改为：

~~~python
~~~

将 _load_acquisition_evidence 的完整签名改为 _load_acquisition_evidence(config: DualHorizonAcquisition, *, code_sha: str, required_snapshot_ids: tuple[str, ...]) -> tuple[dict[str, Any], dict[str, Any]]。调用处传 snapshots.snapshot_ids。只接受 acquisition/quality 都 passed 且 acquisition snapshot_ids 集合和长度与 required 完全一致的 run；否则继续搜索，最终抛 AnalysisBlocked("SOURCE_EVIDENCE_MISSING")。不得改 resolver、Holdout、Candidate 或 wire model。

- [ ] **Step 4: 验证并提交**

~~~powershell
uv run pytest -p no:cov tests/unit/data/test_local_snapshot_recovery.py tests/unit/data/test_snapshots.py tests/unit/research/test_operations.py tests/integration/data/test_local_snapshot_recovery.py -q
uv run ruff check src/bian_quant/data/local_snapshot_recovery.py src/bian_quant/research/operations.py tests/unit/data/test_local_snapshot_recovery.py tests/unit/research/test_operations.py tests/integration/data/test_local_snapshot_recovery.py
uv run ruff format --check src/bian_quant/data/local_snapshot_recovery.py src/bian_quant/research/operations.py tests/unit/data/test_local_snapshot_recovery.py tests/unit/research/test_operations.py tests/integration/data/test_local_snapshot_recovery.py
uv run mypy src/bian_quant
git add src/bian_quant/data/local_snapshot_recovery.py src/bian_quant/research/operations.py tests/unit/data/test_local_snapshot_recovery.py tests/unit/research/test_operations.py tests/integration/data/test_local_snapshot_recovery.py
git diff --cached --check
git commit -m "feat(data): recover cataloged local snapshots"
~~~

### Task 4: 真实离线恢复、证据和停止门

**Files:**

- Create: docs/evidence/2026-08-14-local-snapshot-recovery-run.md
- Modify: docs/implementation-notes.md

- [ ] **Step 1: 运行 preflight**

~~~powershell
@'
from pathlib import Path
from bian_quant.data.acquisition import DualHorizonAcquisition
from bian_quant.data.local_snapshot_recovery import preflight_local_snapshot_recovery
root = Path.cwd()
config = DualHorizonAcquisition.from_yaml(root / "configs/experiments/popular_universe_100u.yaml")
result = preflight_local_snapshot_recovery(config)
print(result.status, len(result.inputs), result.parent_snapshot_ids, result.input_set_sha256)
print(result.blocked_reasons)
'@ | uv run python -
~~~

执行前后对既有 research Parquet、旧 manifest 和主 Catalog 行取 SHA-256；非 READY 时只记录 blocked 原因与基线不变，不调用恢复。

- [ ] **Step 2: 仅在 READY 时恢复并运行 development**

~~~powershell
@'
from pathlib import Path
import subprocess
from bian_quant.data.acquisition import DualHorizonAcquisition
from bian_quant.data.local_snapshot_recovery import recover_local_dual_horizon_snapshots
from bian_quant.research.operations import analyze_cataloged_dual_horizon
root = Path.cwd()
code_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
config = DualHorizonAcquisition.from_yaml(root / "configs/experiments/popular_universe_100u.yaml")
recovery = recover_local_dual_horizon_snapshots(config, code_sha=code_sha)
print(recovery.status, recovery.run_id, [item.snapshot_id for item in recovery.snapshots])
print(recovery.delay_snapshot_ids, recovery.blocked_reasons)
if recovery.status.value == "recovered":
    analysis = analyze_cataloged_dual_horizon(config, code_sha=code_sha)
    print(analysis.run_id, analysis.status, analysis.candidate_factor_ids, analysis.error_code)
'@ | uv run python -
~~~

无论 development 结果是 passed、blocked、零 Candidate 或有 Candidate，都不得访问 Holdout 或执行 paper/live。

- [ ] **Step 3: 写证据、门禁、提交和推送**

证据只记录本机真实值：分支、SHA、时间、preflight、Canonical IDs/set hash、新主/延迟 IDs、运行 IDs、analysis 状态和全部门禁。必须有：

~~~text
network_downloads=false
old_artifacts_unchanged=true|false
holdout_accessed=false
paper_trading=false
live_trading=false
~~~

~~~powershell
uv run pytest -p no:cov tests/unit/data/test_snapshots.py tests/unit/data/test_local_snapshot_recovery.py tests/integration/data/test_dual_horizon_pipeline.py tests/integration/data/test_local_snapshot_recovery.py tests/unit/research/test_operations.py tests/unit/factors/test_derivatives_factors.py tests/integration/factors/test_dual_horizon_screening.py tests/unit/research/test_dual_horizon.py -q
uv run ruff check src/bian_quant/data/popular_universe_artifacts.py src/bian_quant/data/local_snapshot_recovery.py src/bian_quant/data/dual_horizon.py src/bian_quant/research/operations.py tests/unit/data/test_local_snapshot_recovery.py tests/integration/data/test_local_snapshot_recovery.py tests/unit/research/test_operations.py
uv run ruff format --check src/bian_quant/data/popular_universe_artifacts.py src/bian_quant/data/local_snapshot_recovery.py src/bian_quant/data/dual_horizon.py src/bian_quant/research/operations.py tests/unit/data/test_local_snapshot_recovery.py tests/integration/data/test_local_snapshot_recovery.py tests/unit/research/test_operations.py
uv run mypy src/bian_quant
git diff --check
git add docs/evidence/2026-08-14-local-snapshot-recovery-run.md docs/implementation-notes.md
git diff --cached --check
git commit -m "docs(data): record local snapshot recovery"
git push -u origin codex/relative-funding-pressure-factor
~~~

门禁失败时先补最小回归测试、直接修复并重跑受影响门禁；同一外部状态连续三次无法推进时，保留原始输出后停止。推送后停止；本计划不授权 main 合并、删分支、Holdout、paper 或交易。

## 自审计和验收

- [x] 只读 preflight、新不可变 snapshot、旧 artifact 保护、strict resolver、development-only 和真实 evidence 都有对应 Task。
- [x] 类型、字段、错误码和函数签名在全计划一致，不含未定项或“适当处理”式占位。
- [x] 新 API 位于 data 层，research 只消费 Catalog/source evidence，不存在反向依赖。
- [ ] 旧 snapshot、manifest、Catalog 行和 Parquet 的哈希逐项不变。
- [ ] 四个主 snapshot 严格匹配当前 identity 并共享同一非空 Canonical lineage。
- [ ] delay lineage 精确等于新四主 snapshot ID 集合，source evidence 精确绑定已解析 IDs。
- [ ] 无网络、Holdout、paper 或 live 行为；所有声明都有实际 evidence。
