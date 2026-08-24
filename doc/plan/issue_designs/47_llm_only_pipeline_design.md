# 设计文档 47 — 主路径仅 LLM 解析（去除规则降级）

> 触发：2026-08-17 评审——主路径（任务解析 / 规划 / 竞品识别 / 维度分析）是"LLM 优先 + 代码规则兜底"双轨，
> 规则版在"无 Key 可复现、离线可用"上价值已被 benchmark 确定性机制取代，反而成为"宣称 LLM 驱动、实则可被规则短路"的
> 叙事包袱。决策：**主路径只保留 LLM 解析**，删除规则降级分支；相关测试先删除或最小化修改。
> 前置：设计文档 44（规划 LLM 化 `_strategy_from_llm` 已存在）、46（CLI 默认 `use_llm=True` 已对齐库入口）。

## 1. 问题现状

- 全项目贯穿"LLM 优先，失败自动降级规则"（`analyzers/base.py:4`），导致**两条逻辑并存、行为分裂**：
  同一任务在"有 Key"与"无 Key"下产出不同口径结果，验收难以讲清"到底哪条是真"。
- 具体规则降级点（本次范围，**仅"LLM 解析 → 代码规则"这条线**）：

| 层 | 位置 | 规则逻辑 |
|---|---|---|
| 任务解析 | `core/task_parser.py:109` `parse_task()` | `except → _parse_task_rule`（:122）；规则版 `_parse_task_rule`（:125）/ `_extract_dimensions`（:183）/ `_extract_custom_sources`（:203）/ `_infer_resolution`（:137）+ 关键词/触发词常量 |
| 规划 | `core/strategic_loop.py:95` `plan()` | `except → _plan_with_rules`（:109）；`_plan_with_rules`（:111）/ `_build_gaps`（:258）/ `_allocate_budget`（:318）/ `_FOCUS_KEYWORDS`/`DIMENSION_PRIORITY` 提权；`_plan_memory_context`（:140）内部 `parse_task(use_llm=False)` 规则预判竞品 |
| 竞品识别 | `core/competitor_registry.py:126` | 子串匹配 → ASCII 提取兜底（:149）/ `split_compare_text` 对比拆分规则（:97）/ `resolve_competitors`（:118） |
| 发现 | `core/competitor_discoverer.py` | `_FALLBACK_CANDIDATES` 内置清单（:25）/ `_registry_hits`（:100）/ `_dedupe_with_llm` 失败回退规则去重（:130） |
| 分析 | `analyzers/base.py:125` | `except → _analyze_with_rules`（:140）；`_analyze_with_rules`（:351）/ `_rule_extract`（:383） |
| 分析子类 | 6 个分析器 | `feature:39` / `pricing:118` / `performance:92` / `ecosystem:63` / `sentiment:61` 的 `_rule_extract` + `fallback_analyzer.py`（37 行） |
| 入口 | `facade/api.py:1083/1091`、`web_app.py:116` | `_disambiguate_with_history` 规则版兜底、`_last_competitor_from_history` 规则扫描、Web 硬编码 `parse_task(llm=None, use_llm=False)` |

- **不变量**：本次不触碰"功能降级"（RAG 向量不可用降词袋 `knowledge_base/*`、记忆检索失败静默 `memory/*`、
  榜单直连失败回退页面 `gap_executor.py:212`、LLM 重试/多模型 fallback `llm/client.py`）——它们是健壮性设计，
  去掉会在缺依赖/断网时崩，属范围外。

## 2. 目标设计

1. **主路径单轨**：`parse_task` / `plan` / `analyze` 只走 LLM；LLM 不可用/失败 → 抛 `LLMUnavailableError`，
   由入口明确报错（CLI 提示配置 Key，Web 返回 4xx/5xx），**不再静默降级规则**。
2. **竞品识别归 LLM**：竞品名/链接由 LLM 结构化输出；`competitor_registry` 保留为**名称规范化映射表**（数据），
   删除"ASCII 提取造竞品"与"对比拆分"的启发式。
3. **注入防护不短路**：`detect_injection` 命中（base.py:181）不再降级规则，改为**返回不可信结果 + 低置信 PARTIAL**。
4. **基准确定性由 mock LLM 承担**：`BenchmarkMockLLM` 升级为"走 LLM 版解析/规划/分析"的确定性 mock，
   替代原"靠规则版保证可复现"的机制（见 §4.2）。

## 3. 模块/接口设计

### 3.1 `core/task_parser.py` — LLM only

```python
def parse_task(task: str, llm: LLMClient, use_llm: bool = True) -> TaskParseResult:
    """仅 LLM 解析；LLM 不可用/解析失败抛 LLMUnavailableError，不降级规则。"""
```

- `use_llm` 参数保留（兼容既有调用/消融开关），`False` 或无 `llm` 时直接抛 `LLMUnavailableError`。
- 删除：`_parse_task_rule`、`_extract_dimensions`、`_dimensions_in`、`_extract_custom_sources`、`_infer_resolution`、
  `DIMENSION_KEYWORDS`、`_RESTRICT_MARKERS`、`_DISCOVERY_MARKERS`、`_SOURCE_URL_PATTERNS`。
- 保留：`_parse_task_llm`（含 `resolution` 枚举校验、`custom_sources` 提取）、`TaskParseResult`、`ResolutionDecision`。

### 3.2 `core/strategic_loop.py` — plan 仅 LLM

```python
def plan(self, task: str, memory: IFourLayerMemory | None = None) -> CompetitorStrategy:
    """仅 LLM 结构化规划（complete_json + PLAN_SCHEMA）；失败抛 LLMUnavailableError。"""
```

- 删除：`_plan_with_rules`、`_build_gaps`、`_allocate_budget`、`_FOCUS_KEYWORDS` 提权逻辑。
- 保留：`_strategy_from_llm`（含 `_coerce_priority`/`_llm_budget` 越界收敛、非法输入回退校验——注意
  `_strategy_from_llm` 校验失败当前回退规则，改为**抛错**）；`DIMENSION_PRIORITY` 作为 LLM 缺失时的默认优先级（数据）。
- `_plan_memory_context`（:140）：内部 `parse_task(use_llm=False)` 规则预判竞品 → 改为从 `parse_task(llm=...)`
  或直接传 `primary_competitor`，失败静默省略（记忆召回本就是可选增强）。

### 3.3 `core/competitor_registry.py` — 注册表降级为映射

- `resolve_competitor(name)`：删除 ASCII 提取兜底（:149），未命中 → 抛 `ValueError`（由上层 LLM 结果兜底）。
- `resolve_competitors` / `split_compare_text`：删除对比拆分规则，改为上游 `parse_task` 的 `competitors` 列表直接映射。
- 保留：`COMPETITOR_REGISTRY` 数据 + `canonicalize`（把 LLM 输出/用户名的别名归一化为规范名）。

### 3.4 `core/competitor_discoverer.py`

- 删除：`_FALLBACK_CANDIDATES`、`_registry_hits` 分支（保留注册表优先命中作为"已知竞品直接返回"仍是可接受的
  **数据查询**，不算规则解析；若希望彻底 LLM 化，可删除并在 `_search` 缺 `web_tool` 时抛错）。
- `_dedupe_with_llm`：删除规则去重回退，LLM 失败抛 `LLMUnavailableError`。
- `_to_competitors`/`_extract_links`（结构转换）保留。

### 3.5 `analyzers/base.py` + 6 个子类

```python
def analyze(self, observation, gap, context) -> DimensionResult:
    """仅 LLM 链式分析；LLMUnavailableError / 注入命中返回不可信 PARTIAL，不降级规则。"""
```

- 删除：`_analyze_with_rules`、`_rule_extract`（基类 + 6 个子类）、`fallback_analyzer.py` 整文件。
- `analyze()` 的 `except` 分支：`LLMUnavailableError` 与注入命中（`detect_injection`）→ 返回
  `DimensionResult(status=PARTIAL, confidence=0.1, summary="LLM 不可用/内容不可信")`（**保留结构化返回**，
  不抛错炸掉整条流水线；无规则可降，但报告仍可标注"该维度未分析"）。
- `analyzers/registry.py`：未注册维度不再回退 `FallbackAnalyzer` → 抛 `ValueError`（LLM 时代维度由规划枚举约束，
  理论上不会出现未注册维度）。
- 子类构造函数 `use_llm` 参数保留（开关语义），规则路径代码删除。

### 3.6 入口层

- `facade/api.py`：`_disambiguate_with_history`（:1083）改 `parse_task(llm=self._llm, use_llm=self._use_llm)`，
  异常捕获后直接返回原 task（消歧是可选增强）；`_last_competitor_from_history`（:1091）保留（历史扫描是数据查询，
  非解析决策）。
- `web_app.py:116`：硬编码 `parse_task(task, llm=None, use_llm=False)` 改为走真实配置（`llm=self._agent 侧持有`）或
  捕获 `LLMUnavailableError` 返回可读错误（Web 普查任务不能因规则删除而崩溃）。

## 4. 接入方式

### 4.1 无 Key 语义

- CLI：`analyze`/`compare`/`discover` 无 Key → 打印"需要配置 LLM_API_KEY"退出码 2（对齐 benchmark real 模式，
  benchmark.py:1105"不静默回退 mock"）。
- Web：`/api/analyze` 返回错误事件（`LLMUnavailableError` → SSE `error` 事件 + 前端提示）。
- 库调用：抛 `LLMUnavailableError`，由调用方决定。

### 4.2 benchmark 确定性重设计（最大成本点）

- `BenchmarkMockLLM`（`evaluation/benchmark.py`）：当前刻意让 `parse_task`/`plan` 回退规则版保证无 Key 确定性
  （:222/:226）。改造：mock LLM 改为**在 LLM 版接口上确定性返回**——
  - 解析 prompt → 返回空竞品让 `parse_task` 用 `_parse_task_llm` 正常收场，或让 `_parse_task_llm` 对空输入返回 `unknown`；
  - 规划 prompt → 返回合法 `PLAN_SCHEMA`（competitor 取自用例）；
  - 分析 prompt → 维持现有"按维度抽取规范化 JSON"逻辑（其确定性不依赖规则版，只依赖固定页面）。
- 即：**把"确定性"从规则版转移到 mock LLM 的固定返回**，CI 无 Key 仍可复现，但走的是 LLM 版代码路径。
- `evaluation/ablation.py:51`：删除 `no-llm-rule` 变体（5 变体 → 4：full / no-rag / no-memory / no-rag+no-memory）。

### 4.3 测试处理（先删除 / 最小化修改）

| 类别 | 处理 | 说明 |
|---|---|---|
| 规则版专用单测（删除） | `test_task_parser.py` 规则版用例、`test_strategic_loop_llm.py` 规则回退用例、`test_analyzers.py`/`test_pricing_modeling.py` 等 `_rule_extract` 分支、`test_competitor_registry.py` ASCII 兜底/对比拆分、`fallback_analyzer` 相关 | 删除后补"LLM 版"等价用例（mock LLM 断言） |
| 集成/e2e（最小化修改） | `test_analyze_flow`/`test_budget_termination`/`test_checkpoint_resume`/`test_discovery_flow`/`test_team_flow` 等 `use_llm=False` 处改 `use_llm=True` + 注入 `BenchmarkMockLLM`（tests/conftest.py 的 `mock_llm` fixture 已存在） | 断言不变，仅改开关 |
| benchmark 门禁（重写） | `test_benchmark_integration.py` 门禁阈值保持，但确定性来源从规则版切到 mock LLM | 与 §4.2 同步 |
| 保留（不受影响） | RAG/记忆/安全（url_guard/注入）/行为评测/评测体系里不依赖规则解析的用例 | 零改动 |
| CLI | `test_cli.py` 无 Key 分支改为断言报错/退出码 2 | 最小化 |

### 4.4 文档收口

- README / `docs/usage.md`："无 Key 也能出报告"改为"需要配置 API Key"；`docs/api.md` 补 `LLMUnavailableError` 语义。
- `implementation_plan.md` §11.5 删"LLM→规则降级链"亮点，改述"主路径单轨 LLM + mock 确定性评测"。
- 本文件在 `issue_designs/README.md` 索引登记。

## 5. 验证方式

- **单测（新增）**：
  - `parse_task` 无 Key 抛 `LLMUnavailableError`；mock LLM 返回合法/畸形 JSON 的两种结果；
  - `plan()` mock LLM 非法枚举 → 抛错（不再回退规则）；
  - 6 分析器 `analyze` mock LLM 失败/注入命中 → `PARTIAL` 低置信（不炸流水线）；
  - `resolve_competitor` 未命中抛 `ValueError`。
- **集成**：`mock_llm` fixture 下跑通 `analyze`/`compare`/`discover` 完整链路，报告维度齐全。
- **回归**：全量 `pytest` 通过（删除/改造后的集合）；`ruff`/`mypy` 通过；benchmark 门禁（mock）不变。
- **实测**：有 Key 环境 `analyze("Claude Code")` 出报告；无 Key 环境 CLI 报错退出码 2。

## 6. 实现优先级与工作量

| 阶段 | 内容 | 预计 |
|---|---|---|
| P0-1 | 删除 `task_parser`/`strategic_loop`/`competitor_registry`/`discoverer` 规则版 + 对应单测 | 0.5 天 |
| P0-2 | 删除 6 个 `_rule_extract` + `fallback_analyzer`，`base.py` 注入命中改 PARTIAL | 0.5 天 |
| P1 | benchmark mock 确定性迁移 + 消融去 `no-llm-rule` | 1 天 |
| P2 | facade/web 入口、集成/e2e 测试最小化修改、文档收口 | 0.5 天 |

- 依赖：44（`_strategy_from_llm`/`complete_json`）、46（`use_llm` 默认已 True）。
- 风险：无 Key 环境从"可出报告"变为"报错"——产品行为反转，需与用户确认是否接受；benchmark 无 Key CI 依赖 mock 迁移成功。
