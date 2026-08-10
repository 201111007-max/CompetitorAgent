# 设计文档 03 — benchmark 静态 fixture 自证

> 对应 `implementation_plan.md` 第 11 节问题 3（P0）

## 1. 问题现状

- `evaluation/benchmark.py:77-90` 的 `Benchmark.run()` 只读取 JSON fixture 里**预先写好的 `prediction`/`chosen_sources`**，从不调用 agent、不调用 LLM、不抓网页。
- `accuracy_eval.py:81-137` 和 `strategy_eval.py:40-74` 只是对 fixture 字符串做归一化比对。
- 门禁阈值（`test_benchmark_integration.py:43-60`）断言的是**手写 fixture 本身**，必然通过，无法反映系统真实质量。

## 2. 目标设计

让 benchmark **真正运行系统**，评估真实质量：

1. **真实执行**：对每个评测用例，实际调用 `CompetitorAnalysisAPI.analyze()`（真实 LLM + 真实/模拟采集）。
2. **真实指标**：基于真实输出计算字段准确率、幻觉率、策略命中率。
3. **可复现**：支持 mock 采集（固定网页内容）保证确定性，但 LLM 走真实调用。

## 3. 模块/接口设计

### 3.1 Benchmark 重构（`evaluation/benchmark.py`）

```python
class Benchmark:
    def __init__(self, api: CompetitorAnalysisAPI, cases: list[EvalCase]):
        ...

    def run(self) -> BenchmarkReport:
        for case in self.cases:
            report = self._api.analyze(case.task)   # 真实执行
            pred = extract_prediction(report)        # 从真实报告提取
            metrics = self._evaluator.evaluate(case, pred)
        return aggregate(metrics)
```

- `EvalCase`：`task` + `ground_truth`（竞品、维度、字段期望值）。
- `extract_prediction(report)`：从 `DimensionResult` 提取可比对字段。

### 3.2 评测器（`evaluation/accuracy_eval.py` / `strategy_eval.py`）

- 输入改为**真实报告**而非 fixture。
- 保留归一化比对逻辑，但数据来源改为真实输出。

### 3.3 门禁测试（`tests/evaluation/test_benchmark_integration.py`）

- 改为**真实跑 benchmark**，用可控的 mock 采集 + 真实 LLM（或 mock LLM 但断言调用链）。
- 门禁阈值反映真实质量，而非 fixture 自证。

### 3.4 确定性控制

- 采集层可注入 `FakeExtractor`（固定网页内容）保证可复现。
- LLM 层支持 `--llm real|mock` 开关：CI 用 mock（断言链路正确），本地/发布用 real（评估真实质量）。

## 4. 接入方式

```
pytest tests/evaluation/  → 真实跑 Benchmark.run()
  → 每个 case: api.analyze(task) → extract_prediction → evaluate
  → 汇总指标 → 门禁断言
```

## 5. 验证方式

- **单元测试**：`extract_prediction` 从已知报告正确提取字段。
- **集成测试**：mock 采集 + mock LLM 跑通 benchmark 全流程。
- **真实评测**：本地 `--llm real` 跑真实 LLM，记录真实指标。

## 6. 实现优先级与工作量

- 优先级：**高**（P0，评测可信度）。
- 工作量：约 1-2 天。
- 建议先重构 `Benchmark.run()` 为真实执行，再调整门禁测试。
