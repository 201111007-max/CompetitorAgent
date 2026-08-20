# 设计文档 29 — 评测盲区覆盖（生态 / 口碑 / 时间线维度）

> 对应 `implementation_plan.md` §12.3 #9（P2）「评测盲区」。
> 依赖：设计文档 03（真实执行版 benchmark）、24（Ecosystem/Sentiment 分析器）、25（榜单）、26（时间线）。

## 1. 问题现状

- `evaluation/benchmark.py` 的 `DIMENSION_KINDS` 只覆盖 `pricing / feature / performance` 三类字段抽取（`plan_price` / `feature_present` / `benchmark_score`）。
- fixture（`tests/evaluation/fixtures/accuracy_cases.json`、`strategy_cases.json`）对 `ecosystem` / `sentiment` / `roadmap`（含时间线）无 accuracy 用例——而这恰是当前最弱、且本批设计文档要补的分析器维度。
- 评测指南 `competitor_agent/docs/evaluation_guide.md` 的 ground truth 标注格式未含生态/口碑/时间线字段。

## 2. 目标设计

1. **扩展维度字段抽取**：`DIMENSION_KINDS` 增加 `ecosystem` / `sentiment` 两类（`ecosystem_mcp_server` / `ecosystem_plugin` / `sentiment_polarity` / `sentiment_top`），`extract_prediction` 支持从真实报告的结构化 payload（设计文档 24 的 `EcosystemResult` / `SentimentResult`）抽取可比对字段。
2. **新增 fixture 用例**：生态（MCP server 数量/是否支持某 IDE/插件市场信号）、口碑（正负极性）、时间线（版本/价格变化事件，配合设计文档 26）三类 accuracy + 少量 strategy 用例；沿用确定性采集（`page` + `BenchmarkExtractor`）。
3. **评测指南同步**：`evaluation_guide.md` 增新字段的 ground truth 标注格式与口径。
4. **门禁口径**：新维度用同一套 字段准确率 / 幻觉率 / F1 指标；对"信号不足 → `[PARTIAL]` 不编造"行为加一条幻觉下限断言（`ecosystem`/`sentiment` 空数据不得产出具体结论）。

## 3. 模块/接口设计

### 3.1 `evaluation/benchmark.py` 扩展

```python
DIMENSION_KINDS: dict[str, str] = {
    "pricing": "plan_price",
    "feature": "feature_present",
    "performance": "benchmark_score",
    "ecosystem": "ecosystem_signal",     # ← 新增
    "sentiment": "sentiment_signal",     # ← 新增
    "roadmap": "timeline_event",         # ← 新增（设计文档 26）
}
```

- `extract_prediction(report, dimension, ground_truth)` 分支：`ecosystem_signal` → 报告 `ecosystem` 维度的 `mcp_servers` / `plugins` / `ide_support`；`sentiment_signal` → `polarity_ratio` / `positives` / `negatives`；`timeline_event` → 时间线事件（`TimelineMemory.events` 快照或报告内嵌时间线）。
- 字段比对用集合/子集匹配（`mcp_servers ⊆ ground_truth`、极性 ∈ {pos, neg, neu}），沿用现有 AccuracyEvaluator 的 F1/幻觉统计。

### 3.2 fixture 新增

- `tests/evaluation/fixtures/accuracy_cases.json` 增 `ecosystem_cases` / `sentiment_cases` / `timeline_cases`（或拆文件 `ecosystem_cases.json` 等，`FIXTURES_DIR` 下并列）。每个用例保持"task + competitor + dimension + ground_truth + page + fail_urls"结构。
- 含边界用例：生态数据缺失 → 期望 `[PARTIAL]` 无具体结论；口碑只有 1 条信号 → 期望低置信不编造；时间线首次分析无 prev → 无事件。

### 3.3 `docs/evaluation_guide.md`

- 补：`ecosystem_signal` / `sentiment_signal` / `timeline_event` 的 ground truth 标注格式（JSON 示例）、判定口径（子集命中、极性命中）、与设计文档 24/25/26 产出字段的映射。

## 4. 接入方式

```
Benchmark.run() 读新 fixture（自动发现 accuracy_cases*.json）
  → 对 ecosystem/sentiment/roadmap 用例真实 analyze（mode 按用例）
  → extract_prediction 新分支 → AccuracyEvaluator（同一指标）
门禁：新增新维度 accuracy ≥ 0.80、生态/口碑空数据幻觉率 ≤ 0.02（强化"不编造"护栏）
```

- 不改变既有 17+9 用例的语义；新维度只在对应 fixture 存在时参与统计。

## 5. 验证方式

- **单测（extract_prediction 新分支）**：构造含 `EcosystemResult` / `SentimentResult` payload 的 mock 报告 → 抽取与 ground_truth 比对正确；空 payload → 空抽取不报错。
- **单测（fixture 加载）**：新增 fixture 可被 `Benchmark.load` 发现并解析；缺字段用例安全跳过或报明确错误。
- **集成**：mock LLM + 确定性采集跑通 1 条 ecosystem + 1 条 sentiment accuracy 用例，`AccuracyMetrics` 计算正确、幻觉率包含空数据护栏断言。
- **回归**：既有 26 用例全绿、HARNESS_VERSION 数字 +1（`0.3.0 → 0.4.0`，防"上个数字误导"）。

## 6. 实现优先级与工作量

- 优先级：**中低**（P2；评测覆盖影响"宣称质量"的可信度，但排在功能落地之后）。
- 工作量：约 1.5-2 天。
  - `DIMENSION_KINDS` + `extract_prediction` 新分支：0.5 天；
  - fixture 用例（生态/口碑/时间线各 4-6 条）+ 边界：0.5-1 天；
  - 评测指南 + 门禁 + 回归：0.5 天。
- 前置：设计文档 24（分析器产出结构化 payload）、25（榜单）、26（时间线）先落地，否则新维度无真实输出可测。
