# 设计文档 37 — 真实 LLM 评测报告（深度补充）

> 对应 `implementation_plan.md` §16.1 评测行（"38 用例大量跑 mock LLM，真实 LLM 质量未量化"）。
> 触发：2026-08-14 深度复查——`benchmark --llm mock`（确定性、CI 可复现）验证的是 **harness 正确性**，
> 而非**真实 LLM 端到端质量**；`--llm real` 通道已存在（evaluation_guide.md §4）但从未产出一份真实质量报告。
> 依赖：`evaluation/benchmark.py`（`BenchmarkMockLLM` 替换点）、`evaluation/accuracy_eval.py`、`evaluation/strategy_eval.py`、`evaluation/failure.py`、`llm/client.py`（含设计文档 36 的稳定性）。

## 1. 问题现状

- 评测体系（设计文档 03/29/30/31）指标口径完备，但默认 `mock` 模式用 `BenchmarkMockLLM` 确定性解析——**字段准确率 1.0 / 幻觉率 0 是 harness 自洽，不是真实模型水平**。
- `--llm real` 已存在但从未跑通产出报告：① LLM 层无重试/超时（设计文档 36），长用例易中途降级规则，混淆"真实 LLM 质量"与"链路抖动"；② 无真实质量报告落盘规范（路径/格式/指标集）。
- 影响：评测体系的"字段准确率 90%+"仅覆盖 mock 口径，真实模型质量无数据——mock 数字不能代表能力。

## 2. 目标设计

1. **真实质量报告**：`benchmark --llm real --out reports/benchmark_real_<date>.csv` 产出真实 LLM 的字段准确率/幻觉率/工具选择/成本效率/失败分布，落盘 Markdown + CSV（与 mock 报告同构，可并列对比）。
2. **mock vs real 对比**：报告并列 mock/real 两列，标注差异（真实幻觉率/成本），直接回应"评测是不是自证"。
3. **成本核算**：复用 `llm._log_call` 的 cost_usd，报告含单用例成本与总成本（上限护栏，超预算中止——复用 `BudgetController`）。
4. **稳定性前置**：依赖设计文档 36 的重试/超时/fallback，确保 real 报告反映**模型质量**而非网络抖动。

## 3. 模块/接口设计

### 3.1 `evaluation/benchmark.py` 增强

- `--llm real` 已存在：确保 `BenchmarkMockLLM` 替换为真实 `LLMClient`（经 `build_benchmark_api(llm=LLMClient(...))`），并对每个 case 复用同一实例（连接复用）。
- 新增 `--tag normal` 等可选子集过滤（先跑 normal 子集控制成本）；默认全量 38 用例。
- `BenchmarkReport` 增 `llm_mode: str`（"mock"/"real"）、`cost_usd: float`、`per_case_cost`；`_write_markdown`/`_write_csv` 输出含成本列与模式标注。

### 3.2 报告入口与规范

- `reports/benchmark_real_<date>.md/.csv`（复用 `--out`，无 `--out` 默认落 `reports/`）。
- Markdown 结构对齐 mock 报告（指标明细/均值方差/幻觉清单/失败分布/成本），新增「mock vs real」对比段。
- `evaluation_guide.md` 增"真实评测"小节：命令、前置（有 Key）、成本提示、结果口径（real 是质量、mock 是回归）。

### 3.3 成本护栏

- real 模式默认 `cost_limit_usd`（如 $1.0），超限中止并标注"预算中止"（复用 `BudgetController` + 设计文档 31 的 `budget_exhausted` 失败分类）。

## 4. 接入方式

```
python -m competitor_agent.evaluation.benchmark --llm real --out reports/benchmark_real.csv
  → build_benchmark_api(llm=LLMClient(retry/fallback 来自 LLMConfig))（设计文档 36）
  → 逐 case 真实 analyze → extract_prediction/accuracy/strategy/failure 聚合
  → BenchmarkReport(llm_mode="real", cost_usd, per_case_cost)
  → reports/benchmark_real_<date>.md/.csv（含 mock vs real 对比）
无 Key / 网络不可用 → 明确报错提示"请配置 LLM Key 后重试"，不静默回退 mock（防误读）
```

- 主流程零改动：纯评测侧命令 + 报告增强；mock 模式行为完全不变（CI 回归不受影响）。

## 5. 验证方式

- **单测（报告字段）**：`BenchmarkReport` 含 llm_mode/cost 字段，mock 与 real 渲染分支正确。
- **集成（real 冒烟）**：有 Key 时 `--llm real` 跑 2-3 条 normal 用例 → 报告含真实字段准确率/幻觉率/成本、mock vs real 表；无 Key 时该测试 `skipif`（不卡 CI）。
- **回归**：mock 评测全绿（618 基线不受影响）；`--llm mock` 输出与现状逐字节兼容（不破坏既有断言）。

## 6. 实现优先级与工作量

- 优先级：**高**（补齐"评测深但只测了 mock"的最后信任环）。
- 工作量：约 0.5 天（主体是报告字段/渲染/成本护栏，评测链路已就绪）。
  - `llm_mode`/cost 字段 + 渲染：0.25 天；
  - 成本护栏 + real 冒烟测试 + 指南：0.25 天。
- 前置：设计文档 36（先有重试/超时/fallback，real 结果才可信）> 37；与 30/31 共享 `BenchmarkReport`/`failure_stats`，同批可复用真实报告做消融的 real 列。
