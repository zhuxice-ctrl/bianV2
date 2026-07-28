# Kimi 执行交接

请把以下指令与 `docs/superpowers/plans/` 整个目录一起交给 Kimi。

## 可直接复制的执行指令

```text
你将实施 bianV2 量化研究平台。

1. 先读取：
   - docs/superpowers/specs/2026-07-29-quant-research-platform-design.md
   - docs/superpowers/plans/2026-07-29-quant-research-platform-master-plan.md
   - docs/superpowers/plans/2026-07-29-00-foundation-baseline.md

2. 从 codex/research-platform-design 当前计划提交创建：
   codex/research-platform-implementation
   禁止直接修改 main 或 round8-archive。

3. 严格按 00→06 顺序执行。当前只执行 Plan 00；Plan 00 出口门全部通过并由我确认后，才能开始 Plan 01。

4. 每个任务必须遵守：
   - 先写失败测试并展示预期失败；
   - 实现最小代码；
   - 展示目标测试和全局质量检查结果；
   - 创建一个聚焦 commit；
   - 勾选已完成步骤；
   - 报告偏差、风险和下一任务。

5. 不允许：
   - 修改黄金结果来让测试通过；
   - 删除失败实验或覆盖历史 run_id；
   - 用随机时间切分；
   - 在默认测试中下载网络数据或模型权重；
   - 接入真实下单、API 密钥或实盘交易；
   - 跳过阶段出口门；
   - 一次性重写整个仓库。

6. 发现计划与真实仓库冲突时停止相关任务，在 docs/implementation-notes.md 记录：证据、影响、建议修改。未获确认不得扩大范围。

每次回复使用以下格式：

阶段 / 任务：
完成内容：
修改文件：
失败测试证据：
通过测试证据：
提交 SHA：
计划偏差：
风险与待确认项：
下一步：
```

## 首次验收点

Kimi 完成 Plan 00 后，应交付：

- 干净的 `codex/research-platform-implementation` 分支。
- 锁定的 Python/uv 环境与质量脚本。
- `src/bian_quant` 基础包和 CLI。
- 可复现的 BTC/ETH/BNB PA 黄金基线。
- 明确说明 165 次实验报告缺失生成脚本，只属于归档证据。
- `uv run pytest -q`、Ruff、mypy 与 `git diff --check` 的通过输出。

在这些项目全部通过前，不批准进入数据平台实施。
