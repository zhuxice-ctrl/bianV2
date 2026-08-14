# Aily 执行前必读规则

适用范围：本仓库中所有由 Aily 执行、修改、验证或交接的任务。开始任何任务前，必须先完整阅读本文档、对应设计/计划文档，以及当前 Git 状态。

## 0. 每次任务的固定开场指令

后续任务必须以以下文字开场：

> 执行前先阅读 `docs/AILY_EXECUTION_RULES.md`、本任务的设计文档和实施计划。确认当前分支、未提交文件、契约边界与验收命令后再修改。不得仅以 `py_compile` 或 `ast.parse` 作为完成证明；必须运行计划规定的 pytest、Ruff、mypy 和 diff 检查，并如实记录结果。

## 1. Git 与工作区纪律

1. 先运行：`git status --short --branch`、`git log --oneline -5`、`git diff --stat`。
2. 未跟踪文件默认视为用户文件，不删除、不暂存、不格式化；本仓库的 `.superpowers/` 必须排除。
3. 不覆盖、删除或恢复文件，除非先确认它属于当前任务，并说明恢复来源与原因。
4. 不自动合并 `main`、不自动删除分支、不自动推送，除非任务明确授权。
5. 一个纵向切片至少独立提交一次；数据契约/纯服务、消费者契约/UI、真实证据可以分提交。提交前必须运行 `git diff --check`。
6. 推送前确认远端分支和本地分支指向；TLS 或网络失败必须如实报告，不能把“未刷新远端”写成“已同步”。

## 2. 修改前必须定位模块职责

修改任何模块前，必须先完成：

```powershell
rg -n "被修改的函数名|被修改的类型名" src tests dashboard
git show HEAD:<目标文件路径>
```

目的：确认所有调用方，并保存原始公共 API。禁止因复制/保存错误将一个模块的完整内容写入另一个模块。

当前核心职责如下：

| 层 | 允许职责 | 禁止职责 |
|---|---|---|
| `data/` | 本地数据读取、Canonical/Raw 适配、时间可用性、不可变数据记录 | Dashboard、策略、交易所网络、回测评分 |
| `regimes/` | 纯市场状态/周期评分、因果证据哈希 | 读取 Parquet、调用 API、写页面 |
| `signals/` | 标准化信号协议与适配 | 直接决定 UI、绕过回测 |
| `backtest/` | 消费信号/周期状态，计算成交、成本和权益 | 自行读取数据湖、定义市场状态服务 |
| `reporting/` | 组合已完成的本地产物为稳定响应 | 重新实现策略、网络下载、交易 |
| `dashboard/` | 只读取 API 并渲染 | 读取文件、计算指标、创建订单 |
| `paper/` | 仅批准产物的公共数据模拟与追加式审计 | 反向污染研究、下单、密钥、私有端点 |

依赖只允许从左向右：`data adapter → pure regime/signal → backtest → reporting → dashboard`。禁止反向导入。

## 3. 契约优先与向后兼容

1. 后端响应模型是唯一 wire contract；页面只能消费该模型。
2. 现有 `research-terminal-v1` 字段不可删除、重命名或变为可空。新增字段必须有默认值，并在空响应、异常 fallback、passed、blocked 和 empty 场景完整存在。
3. 新增横切证据时，先定义不可变数据契约，再定义纯服务参数，最后添加 reporting/UI 适配器。
4. 每个新字段都要同步更新：Pydantic 模型、契约文档、终端聚合器、服务器 fallback、页面、契约测试。
5. `None`、缺失和错误必须有不同但稳定的语义；缺失数据不能伪造 `passed`，局部模块错误不能无故把父研究运行改为 `blocked`。
6. 修改公共函数签名后，必须全仓搜索调用点并运行导入/聚合器测试。不得只修改一个调用方。

## 4. 时间因果与可复现性

1. 所有决策必须满足 `available_time <= decision_time`；时区必须为 UTC-aware。
2. 新增数据或周期输入时，必须添加前缀因果测试：改变 t 之后的输入，不得改变 t 及之前的状态、信号、乘数、成交或权益。
3. 回测信号必须在已收盘 bar 决策，在下一根 bar 开盘成交；不允许使用未来 close、未来标签或未来热门池记录。
4. 所有 audit artifact 使用 canonical JSON、UTF-8、稳定键排序和 SHA-256。没有实际产物、哈希或真实运行结果时，不能声称“已完成验证”。
5. Funding、OI、OHLCV 等不同可用延迟必须在数据适配层显式处理，不能在页面或回测中临时修正。

## 5. 测试不是语法检查

`py_compile` 和 `ast.parse` 只证明语法可解析，不能证明导入、类型、契约、运行时或因果性正确。它们不能替代以下门禁：

```powershell
uv run pytest -p no:cov <本任务测试文件> -q
uv run ruff check <本任务源码和测试文件>
uv run ruff format --check <本任务源码和测试文件>
uv run mypy src/bian_quant
git diff --check
```

如任务涉及 API 或页面，还必须运行实际聚合器/API 冒烟：

```powershell
uv run python -c "from pathlib import Path; from bian_quant.reporting.research_terminal import build_research_terminal_response; root=Path.cwd(); r=build_research_terminal_response(root/'configs/experiments/popular_universe_100u.yaml', repo_root=root); print(r.schema_version, r.state.value)"
```

规则：

- 测试收集失败即为失败，不可报“部分测试通过”。
- Ruff/mypy 任一失败即为失败，不可报“代码已写入”。
- 全量测试受环境限制时，记录原始错误；只报告实际通过的聚焦集，不虚构全绿。
- 格式化只作用于当前任务文件；不得为了通过检查批量重写仓库既有格式漂移。

## 6. 测试与文件归属

1. `data` 适配器测试放在 `tests/unit/data/`；纯市场周期测试放在 `tests/unit/regimes/`；回测测试放在 `tests/unit/backtest/`；契约/聚合器测试放在 `tests/unit/reporting/`；页面烟雾测试放在 `tests/integration/dashboard/`。
2. 不要把服务代码复制到测试目录或把 regime 测试误放到 backtest。
3. 测试断言必须与因果范围相同：比较前缀时，两侧都必须按同一截止时间过滤，不能拿“完整前缀”与“截断后的全部未来信号”比较。
4. 每发现一个运行时回归，先写或修正能复现它的最小测试，再修复生产代码。

## 7. 错误处理与真实证据

1. Reporting 层可以防御性降级，但禁止用宽泛 `except Exception` 静默吞掉关键逻辑错误后仍报告研究成功。
2. fallback 响应必须通过同一 Pydantic 契约或相同字段测试。
3. 证据文档只记录已经运行过的命令、真实 SHA、真实指标、真实状态和真实未解决项。
4. 文档里的模块路径、测试路径、commit SHA、环境和命令必须与工作区一致；提交前执行 `rg` 复核引用。
5. 当实现被修复时，同步更新旧的“沙箱限制”“待验证”“pending push”等失效表述，保留历史事实但不能让当前结论矛盾。

## 8. 安全边界

当前项目是研究和只读观察平台：

- 禁止 API Key、私有接口、订单、杠杆、账户、持仓、WebSocket 和实盘资金逻辑；
- 禁止在 Dashboard 或 reporting 中触发数据下载、研究运行或交易；
- 禁止未经人工批准打开 Holdout、晋级 Approved 或开始 paper trading；
- 研究页面必须继续展示 `READ-ONLY · RESEARCH ONLY · NO LIVE TRADING`。

## 9. 交付前检查清单

- [ ] 当前分支、提交和未跟踪文件已确认。
- [ ] 修改前已搜索调用方；公共 API 未意外丢失。
- [ ] 新能力位于正确层，依赖方向正确。
- [ ] 契约、fallback、文档、页面和测试同步更新。
- [ ] 点时约束和前缀因果测试通过。
- [ ] 聚焦 pytest、Ruff、format、mypy、diff 检查实际通过。
- [ ] API/聚合器和页面冒烟（如适用）通过。
- [ ] 证据文档只包含已验证事实。
- [ ] 未自动越过 Holdout、paper、live 或 main 合并边界。
