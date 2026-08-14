# Relative Funding Pressure Factor — Development Evidence

## 运行身份

| 项目 | 实际值 |
|---|---|
| 分支 | `codex/relative-funding-pressure-factor` |
| 运行前代码提交 | `b68b268` |
| UTC 运行日期 | 2026-08-14 |
| 开发运行 ID | `033e6f9f-e37e-4b5f-8e62-f5988a1bc833` |
| 配置 | `configs/experiments/popular_universe_100u.yaml` |
| 研究范围 | development-only；不访问 Holdout |

## 实际命令与结果

```powershell
@'
from pathlib import Path
from bian_quant.data.acquisition import DualHorizonAcquisition
from bian_quant.research.operations import analyze_cataloged_dual_horizon
import subprocess

root = Path.cwd()
code_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
config = DualHorizonAcquisition.from_yaml(
    root / "configs" / "experiments" / "popular_universe_100u.yaml"
)
result = analyze_cataloged_dual_horizon(config, code_sha=code_sha)
print(f"run_id={result.run_id}")
print(f"status={result.status}")
print(f"candidates={result.candidate_factor_ids}")
print(f"artifact_dir={result.artifact_dir}")
print(f"error_code={result.error_code}")
'@ | uv run python -
```

实际输出：

```text
run_id=033e6f9f-e37e-4b5f-8e62-f5988a1bc833
status=blocked
candidates=()
artifact_dir=var\artifacts\dual-horizon-popular-v1\033e6f9f-e37e-4b5f-8e62-f5988a1bc833
error_code=SNAPSHOT_MISSING:macro-1d
```

因此本次没有可用的 `micro-4h`/`micro-1h` snapshot ID、内容哈希、因子逐折统计、BH 结果、冗余结果、增量结果或 `relative_funding_pressure` lifecycle artifact 可记录。缺失发生在 snapshot 解析阶段，早于 development 因子计算；未下载数据、未创建 Holdout ledger、未调用 `evaluate_candidate_holdout`，也未调用 paper/backtest/交易代码。

## 实现与契约

- 因子：`relative_funding_pressure@1.0.0`，方向 `two_sided`，`missing_policy="preserve"`。
- 公式：`clip((funding_rate - cross_sectional_median) / (1.4826 * cross_sectional_mad), -5, 5)`。
- 输入来自已锁定 research snapshot 的 `funding_rate`、`funding_available_time`、`funding_interval_hours`；因子层不读路径或 Parquet。
- 同一决策时点少于两个有效资产时给出 `INSUFFICIENT_PEER_COVERAGE`；陈旧、未来或无效 Funding 给出 `FUNDING_UNAVAILABLE_OR_GAPPED`；零 MAD 给出 `ZERO_CROSS_SECTIONAL_MAD`。
- 前缀因果测试覆盖未来 Funding 值、未来可用时间和未来横截面追加；既有八因子、Funding-alignment market cycle、ETH/100U 回测和 `research-terminal-v1` 未被修改。

## 实际质量门

| 命令 | 结果 |
|---|---|
| 聚焦 pytest | `67 passed, 7 skipped` |
| Ruff check | 通过 |
| Ruff format --check | 8 个 Task 文件均已格式化 |
| `uv run mypy src/bian_quant` | 通过，93 个源文件 |
| `git diff --check` | 通过 |

使用的 pytest 命令：

```powershell
uv run pytest -p no:cov tests/unit/factors/test_derivatives_factors.py tests/integration/factors/test_dual_horizon_screening.py tests/unit/research/test_dual_horizon.py tests/unit/research/test_operations.py tests/unit/data/test_snapshots.py tests/unit/reporting/test_research_terminal.py tests/integration/dashboard/test_research_page.py -q
```

## 结论与停止门

代码级门禁通过，但真实 development 运行因 `SNAPSHOT_MISSING:macro-1d` 被阻止。该结果不是 Candidate、Approved、Holdout、paper 或 live 的授权，也不支持关于因子表现、覆盖率或收益的结论。下一步只能由人工决定是否在独立数据可用性切片中恢复缺失的本地 snapshot；在此之前停止本因子的真实筛选和所有晋级流程。
