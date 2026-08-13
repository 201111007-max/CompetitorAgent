# 设计文档 31 — 失败类型统计（聚合口径 + 分布报告）

> 对应 `implementation_plan.md` §12.3 #11（P2）「无失败类型统计」。
> 触发：2026-08-13 简历达标审计——8 条标准中"有失败类型统计"仅半满足：有幻觉率 + 逐实例清单，但**无显式失败类型分类与聚合**。
> 依赖：`evaluation/accuracy_eval.py`、`evaluation/strategy_eval.py`、`evaluation/benchmark.py`。

## 1. 问题现状

- `AccuracyMetrics`（`evaluation/accuracy_eval.py:31`）有 `hallucination_rate` + `hallucination_instances`（逐条幻觉清单），但没有**失败根因归类**——"这个 case 为什么没命中？"无法一眼回答。
- `StrategyMetrics`（`evaluation/strategy_eval.py`）有 `per_case`（hit/rank/cost/efficiency），`confusion_matrix`（`benchmark.py:490-497`）只统计"最优源 vs 首选源"，均非失败类型聚合。
- 底层信号已存在但未聚合：gap 状态机 `OPEN→PARTIAL→CONFIRMED→CLOSED/BLOCKED`（`domain_types/info_gap.py:18`）、`collect.fail` 埋点（`gap_executor.py:126`）、`[PARTIAL]`/`[N/A]` 状态（`markdown_renderer.py:12`）、`real_trace`（`benchmark.py:324`）。
- 缺一份「失败类型 → 计数 → 占比 → 样本」的汇总，无法支撑简历/面试的"失败类型统计"，也无法指导归因优化（哪些失败是源挂了、哪些是幻觉、哪些是数据缺失）。

## 2. 目标设计

1. **失败类型分类**：新增 `FailureType` 枚举，把每个未命中 case / 每类缺陷归入五类之一：
   - `source_unavailable`：源抓取失败/降级后仍无有效数据（`DataSourceUnavailableError`、fail_urls 全灭、BLOCKED）；
   - `hallucination`：预测字段无真值支持（命中现有幻觉判定，`hallucination_instances`）；
   - `no_data`：源有响应但内容不含目标信息（页面没有价格/功能 → 低置信/`[N/A]`）；
   - `parse_failure`：源有内容但抽取/归一化错误（prediction 非空但 F1 < 1 且非幻觉——结构对上、值不对）；
   - `budget_exhausted`：预算/迭代耗尽提前终止（`terminal_state` 或 `[PARTIAL]` 由预算触停）。
2. **聚合统计**：`BenchmarkReport` 增 `failure_stats`——`{type: count}` + 占比 + 逐条 `FailureRecord`（case_id/dimension/type/evidence/detail），Markdown/CSV 落盘。
3. **分布报告**：评测报告新增「失败类型分布」表 + 占比条；CSV 增 failure 行；供后续针对性补 fixture 与归因优化。

## 3. 模块/接口设计

### 3.1 `evaluation/failure.py`（新增）

```python
class FailureType(str, Enum):
    SOURCE_UNAVAILABLE = "source_unavailable"
    HALLUCINATION = "hallucination"
    NO_DATA = "no_data"
    PARSE_FAILURE = "parse_failure"
    BUDGET_EXHAUSTED = "budget_exhausted"

@dataclass
class FailureRecord:
    case_id: str
    dimension: str
    failure_type: FailureType
    detail: str = ""
    evidence_urls: list[str] = field(default_factory=list)

def classify_case(case, prediction: dict, ground_truth: dict,
                  report, status_hints: dict) -> list[FailureRecord]:
    """单 case 归类：幻觉→HALLUCINATION；源失败/BLOCKED→SOURCE_UNAVAILABLE；
       页面无目标信息→NO_DATA；有预测但 F1<1→PARSE_FAILURE；预算触停→BUDGET_EXHAUSTED。"""
```

### 3.2 `evaluation/benchmark.py` 聚合

- `BenchmarkReport` 增字段：

```python
@dataclass
class BenchmarkReport:
    ...
    failure_stats: dict[str, int] = field(default_factory=dict)   # type → count
    failure_records: list[dict[str, Any]] = field(default_factory=list)  # 逐条样本
```

- `Benchmark.run()`（`benchmark.py:385`）末尾调用 `_classify_failures(acc_eval_cases, strat_eval_cases, reports)`：
  - 遍历 accuracy 未命中 case（F1<1 或 hallucination_instances 命中）→ 分类；
  - 遍历 strategy 未命中 case（hit=False）→ `SOURCE_UNAVAILABLE`（首候选失败）或 `PARSE_FAILURE`（有源但未选最优）；
  - 从 `real_trace` + 报告维度状态（BLOCKED / `[N/A]` / `terminal_state`）补 `NO_DATA` / `BUDGET_EXHAUSTED`；
  - 聚合计数 + 占比，去重写入 `failure_stats` / `failure_records`。

### 3.3 渲染与导出

- `_write_markdown`（`benchmark.py:516`）增「## 失败类型分布」：`| 类型 | 计数 | 占比 |` + 逐条样本表（case/维度/原因/证据 URL）。
- `_write_csv`（`benchmark.py:503`）增 `failure.{type}` 行。
- `BenchmarkReport.to_dict()`（`benchmark.py:92`）同步携带 `failure_stats` / `failure_records`（供设计文档 28 的结构化导出复用）。

## 4. 接入方式

```
Benchmark.run() → 收集每个 case 的 report / prediction / ground_truth / trace
  → _classify_failures(...) → BenchmarkReport.failure_stats / failure_records
  → _write_markdown / _write_csv 渲染分布
门禁可选：源失败类占比过高（>30%）提示"fixture 或降级链需关注"，不硬性拦（避免误报）
```

- 不改既有 26 用例语义；纯评测侧增强，主流程零改动。

## 5. 验证方式

- **单测（classify_case）**：分别构造 5 类场景（源 404 / 幻觉字段 / 页面无价格 / 抽取值错 / 预算触停）→ 各归入正确 `FailureType`。
- **单测（聚合）**：混合 10 个构造 case → `_classify_failures` 计数/占比正确、`failure_records` 条数吻合、去重无重复。
- **集成**：mock LLM + 固定页面，含 fail_urls（模拟源失败）与答案缺失 case → 报告含「失败类型分布」表，`SOURCE_UNAVAILABLE`/`NO_DATA` 计数符合预期。
- **回归**：既有指标（字段准确率/幻觉率/F1）数值不变；全量测试绿；`benchmark --csv` 输出含 failure 行。

## 6. 实现优先级与工作量

- 优先级：**中低**（P2；不改变功能交付，补齐简历/面试"失败类型统计"证据与归因能力）。
- 工作量：约 0.5-1 天。
  - `FailureType` + `classify_case`：0.25 天；
  - `_classify_failures` 聚合 + `BenchmarkReport` 字段：0.25 天；
  - 渲染 + CSV + 测试：0.25-0.5 天。
- 前置：无（`accuracy_eval` / `strategy_eval` / `benchmark` 均已就绪）；与设计文档 30（消融对比）共享 `BenchmarkReport`，可同批落地。
