# 设计文档 42 — 行为级评测（工具自恢复 + 检索命中率）

> 触发：2026-08-15 第二轮评审——现有评测（`evaluation/benchmark.py` + `accuracy_eval.py`）测的是**结果字段**（field_accuracy/F1/
> hallucination_rate）与策略倾向（tool_selection_accuracy），**不测行为**：工具调用失败后 agent 能否自恢复（设计文档 38 回灌闭环
> 无定量证据）、RAG 混合检索是否真的比纯词袋好（设计文档 32 的 hybrid 价值无可证指标）。
> 依赖：设计文档 38（回灌/四类反馈）、32（`knowledge_base/retriever.py` hybrid/lexical）、`evaluation/benchmark.py`
> （`BenchmarkReport`/门禁）、`agent/react_loop.py`（ReAct 循环）、`evaluation/accuracy_eval.py`（结果级评测先例）。

## 1. 问题现状

- `BenchmarkReport`（`benchmark.py:92-141`）全维度都是**输出质量**：accuracy（字段/F1/幻觉率）、strategy（工具选择/成本/源序）、
  trace_completeness、failure_stats——**没有任何行为指标**。"agent 会从错误里自恢复"只有设计文档 38 的测试断言，无规模化证据。
- `Retriever.retrieve`（`knowledge_base/retriever.py:19-42`）提供 `strategy="hybrid"`（默认）与 `"lexical"`（消融），
  `search_hybrid`（competitor_store.py:150-185）在向量层不可用时**自动降级词袋**——但评测从不对比 hybrid vs lexical 的命中差异，
  "混合检索更准"无数据支撑，降级路径是否掉点也无从知晓。
- 影响：agent 行为可靠性（自恢复）与 RAG 收益是 agent 项目的核心卖点，当前无量化口径；面试被问"怎么证明工具调用可靠/RAG 有效"无数据。

## 2. 目标设计

1. **行为指标进报告**：`BenchmarkReport` 增 `react_recovery_rate`（工具错误自恢复率）与 `retrieval_hit_rate`（检索命中率，hybrid vs lexical 对比），进 `to_dict`/渲染/门禁。
2. **RecoveryEvaluator**（`evaluation/behavior_eval.py`）：对一组"会出错"的 ReAct 场景，跑 mock LLM 脚本化回放——第一轮输出非法参数/调用不存在工具 → 收到 Observation 回灌（设计文档 38）→ 第二轮输出合法调用/兜底 → 判**自恢复**；`recovery_rate = 恢复成功场景 / 总场景`。
3. **RetrievalEvaluator**：用评测夹具的 (query, 期望 chunk) 对，对每 query 分别跑 `retrieve(strategy="hybrid")` 与 `"lexical"`，算 `hit_rate@k`（top-k 命中期望 chunk 的比例）；断言 **hybrid ≥ lexical**（向量层在线时）且整体 hit_rate 过门禁。
4. **mock 下确定性可复现**：mock LLM 的脚本化回放是确定性的（无真实 Key 依赖），恢复率基线高（≥0.9）；真实 Key 模式叠加真实波动。

## 3. 模块/接口设计

### 3.1 新 `evaluation/behavior_eval.py`

```python
@dataclass
class BehaviorMetrics:
    react_recovery_rate: float = 0.0   # 工具错误后自恢复成功比例
    recovery_n: int = 0
    retrieval_hit_hybrid: float = 0.0  # hybrid 命中率@k
    retrieval_hit_lexical: float = 0.0 # lexical 命中率@k（消融对照）
    retrieval_n: int = 0

class RecoveryEvaluator:
    """ReAct 自恢复：脚本化 mock LLM 回放错误→回灌→重试→成功"""
    def __init__(self, llm=None, dispatcher=None) -> None:
        # 未注入时用 ScriptedLLM（先输出非法参数/不存在工具，收到 Observation 后输出合法调用）
    def run(self) -> float:  # 返回 react_recovery_rate

class RetrievalEvaluator:
    """RAG 命中：对 (query, expected_chunks) 夹具跑 hybrid/lexical 对比"""
    def __init__(self, retriever: Retriever | None = None, top_k: int = 3) -> None:
        # retriever 未注入时用真实 CompetitorStore + 夹具灌库（设计文档 32 可插拔 embed）
    def run(self) -> tuple[float, float]:  # (hit_hybrid, hit_lexical)
```

- `ScriptedLLM`：复用 `BenchmarkMockLLM`（benchmark.py:182-243）的确定性模式——首轮故意输出 `Args: 非法 JSON` / 不存在工具，
  后续轮根据 Observation 中"工具参数错误/工具不可用"关键词输出合法参数，最终 Final Answer。
- 夹具复用：`evaluation/benchmark.py` 的 AccuracyCase 数据源（真实竞品页面文本灌 store → 构造 (query, chunk) 对）。
- `RecoveryEvaluator.run` 驱动 `ReactLoop`（`agent/react_loop.py`），事件经 `event_sink` 收集判定"是否出现错误→是否恢复"。

### 3.2 `evaluation/benchmark.py` 扩展

```python
class BenchmarkReport:
    ...
    behavior: BehaviorMetrics = field(default_factory=BehaviorMetrics)  # 设计文档 42
    # to_dict() 增 "behavior": {react_recovery_rate, retrieval_hit_hybrid, retrieval_hit_lexical, n}
```

- `Benchmark.run` 完成后追加 `self._run_behavior_evals()`：mock 模式必跑（确定性）；real 模式跑 RetrievalEvaluator（不依赖 Key），
  RecoveryEvaluator 可选（有 Key 时跑脚本化+真实 LLM 混合）。

### 3.3 门禁与渲染

- 门禁（mock 判定）：`react_recovery_rate ≥ 0.9` 且 `retrieval_hit_hybrid ≥ retrieval_hit_lexical`（hybrid 不劣于 lexical）为过；
  向量层不可用时 hybrid 等价 lexical（equal，不判劣）。
- 渲染：benchmark 输出（CLI/报告 markdown）增"行为评测"节，展示两指标 + 恢复样本数。

## 4. 接入方式

```
evaluation/behavior_eval.py（RecoveryEvaluator + RetrievalEvaluator）
  ├─ RecoveryEvaluator：ScriptedLLM 回放错误 → ReactLoop 回灌（设计文档 38）→ 判定自恢复
  ├─ RetrievalEvaluator：夹具灌 store → Retriever hybrid vs lexical → hit_rate@k
  └─ Benchmark.run 末尾追加 → BenchmarkReport.behavior → to_dict/渲染/门禁
既有结果级指标（accuracy/strategy）不动；mock 下确定性，real 下叠加真实波动
```

- 零影响：现有评测夹具/门禁不变，仅新增一节与两字段。
- 依赖收敛：RecoveryEvaluator 依赖设计文档 38 的回灌闭环先落地（否则"自恢复"无从测起）。

## 5. 验证方式

- **单测（RecoveryEvaluator）**：ScriptedLLM 首轮非法参数/不存在工具 → Observation 回灌 → 第二轮合法 → `recovery_rate=1.0`；
  注入"永不恢复"脚本 → 该场景记失败（确定性）。
- **单测（RetrievalEvaluator）**：灌入 2 个已知 chunk，query 命中其一 → hybrid hit_rate@3 ≥ 期望值；lexical 对照可算；
  向量层不可用（`is_available()=False`）时 hybrid==lexical（不误判劣）。
- **集成（BenchmarkReport）**：`Benchmark.run`（mock）→ `report.behavior.react_recovery_rate ≥ 0.9`、`hit_hybrid ≥ hit_lexical`；
  `to_dict()` 含 `behavior` 字段。
- **回归**：既有 benchmark/accuracy 评测测试全绿（新增字段默认值不破坏断言）；`test_react.py`（设计文档 38）不受影响。

## 6. 实现优先级与工作量

- 优先级：**中高**（把"行为可靠性 + RAG 收益"变成可证指标；是设计文档 38/32 价值的量化闭环）。
- 工作量：约 1 天。
  - `behavior_eval.py` 两 Evaluator + ScriptedLLM：0.5 天；
  - `BenchmarkReport.behavior` + to_dict + 渲染/门禁：0.3 天；
  - 测试：0.2 天。
- 前置：设计文档 38（回灌闭环）、32（retriever hybrid/lexical）。与 37（真实评测）并行——real 模式复用其 llm_mode/cost 记账。
