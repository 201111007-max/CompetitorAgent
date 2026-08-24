# 设计文档 30 — 消融 / 对比实验（有无 RAG / rerank / memory）

> 对应 `implementation_plan.md` §12.3 #10（P2）「无对比/消融实验」。
> 触发：2026-08-13 评测体系复核——8 条评测能力标准中"有无 RAG / 有无 rerank / 有无 memory 对比实验"缺失，各组件收益无法量化。
> 依赖：`evaluation/benchmark.py`（真实执行版，26 条用例）、`facade/api.py`（RAG/记忆注入点）。

## 1. 问题现状

- `CompetitorAnalysisAPI.__init__`（`facade/api.py:114-121`）**无条件**组装 `CompetitorStore`/`Ingester`/`Retriever`，经 `api.py:251-252`（single）、`319-320`（team）注入 `GapExecutor`——RAG 无开关，无法回答"有 RAG 到底降了多少幻觉率"。
- `memory`（L1-L4）为可注入参数，但无 `enable_memory` 语义开关；`use_llm`（`api.py:85`）是唯一现成开关。
- **没有一份"同一用例集 × 有无组件"的对比实验**。`Benchmark.run()` 已对 26 条用例（17 accuracy + 9 strategy）真实执行并产出字段准确率/幻觉率/F1/工具选择准确率/成本效率（`benchmark.py:385-435`），恰好可作对照基线，但从未按变体并排跑过。
- 无数据支撑回答"加 RAG 到底有没有用？加记忆呢？规则降级 vs LLM 差多少？"——组件收益没有量化口径。

## 2. 目标设计

1. **组件开关**：`CompetitorAnalysisAPI` 新增 `enable_rag` / `enable_memory` 构造开关（默认开启，保持现状行为不变），使"有/无 RAG、有/无 memory"可独立组合。
2. **消融运行器** `evaluation/ablation.py`：定义变体矩阵（full / no-rag / no-memory / no-rag+no-memory / no-llm-rule 共 5 组），对同一批 26 条确定性用例逐变体跑 `Benchmark`，产出「变体 × 指标」对比表。
3. **对比报告落盘**：`reports/ablation/ablation_<date>.md` + `.json`（或 CSV），含每组变体的字段准确率 / 幻觉率 / F1 / 工具选择准确率 / 成本效率 / 平均命中排名，及逐 case 差异明细。
4. **门禁化可选**：断言 `full` 幻觉率 ≤ `no-rag`（证明 RAG 有效）——若未来某变体反超，说明回归，评测直接暴露。

## 3. 模块/接口设计

### 3.1 `facade/api.py` 组件开关

```python
def __init__(
    self,
    llm=None, use_llm: bool = True,
    max_iterations=None, cost_limit=None,
    event_sink=None, extractor=None,
    memory: IFourLayerMemory | None = None,
    config: AppConfig | None = None,
    web_tool=None,
    enable_rag: bool = True,      # ← 新增
    enable_memory: bool = True,   # ← 新增
) -> None:
    ...
    if enable_rag:
        self._store = CompetitorStore()
        self._ingester = Ingester(store=self._store)
        self._retriever = Retriever(store=self._store)
    else:
        self._store = self._ingester = self._retriever = None
    self._enable_memory = enable_memory   # 门控 _apply_memory_boost / set_success_rates / 记忆沉淀
```

- 注入点（`api.py:251-252` / `319-320`）在 `enable_rag=False` 时传 `ingester=None, retriever=None`；`GapExecutor` 对 None 走"跳过摄入/跳过检索注入"（对齐"知识库不存在"路径，`gap_executor.py:175/200` 已有 try/except 兜底）。
- `memory` 门控：`enable_memory=False` 时跳过 `selector.set_success_rates`（`api.py:106-107`）、`_apply_memory_boost`、`record_skill/record_outcome`、`archive_session` 等全部记忆副作用。

### 3.2 `evaluation/ablation.py`（新增）

```python
@dataclass(frozen=True)
class AblationVariant:
    name: str                  # "full" / "no-rag" / "no-memory" / "no-rag+no-memory" / "no-llm-rule"
    enable_rag: bool = True
    enable_memory: bool = True
    use_llm: bool = True

@dataclass
class AblationResult:
    variant: AblationVariant
    report: BenchmarkReport        # 该变体下 26 条用例的完整评测
    # 派生指标：field_accuracy / hallucination_rate / f1 / tool_selection_accuracy / cost_efficiency

class AblationRunner:
    def __init__(self, fixture_dir: Path): ...      # 复用 Benchmark 的 fixture 加载与确定性采集
    def run(self, variants: list[AblationVariant] | None = None) -> list[AblationResult]:
        """逐变体构造 api（enable_rag/enable_memory/use_llm 按变体），跑同一批用例，汇总结果。"""
```

- 变体构造复用 `benchmark.py` 的 `_build_api`（`BenchmarkMockLLM` + `BenchmarkExtractor` 确定性采集，CI 无 Key 可复现），仅把开关参数透传。

### 3.3 渲染与 CLI

- `render_ablation_table(results: list[AblationResult]) -> str`：Markdown 对比表（行=指标，列=变体，标出最优；幻觉率一列标绿/标红差异）。
- `write_ablation_json(results, out)`：稳定 schema（variants / metrics / per_case 差异明细 / harness_version）。
- CLI：`python -m competitor_agent.cli benchmark --ablate`（追加 5 组变体全跑，默认仅跑 full 保持现状）。

## 4. 接入方式

```
AblationRunner.run()
  └─ 对每个 variant：CompetitorAnalysisAPI(enable_rag=..., enable_memory=..., use_llm=..., extractor=BenchmarkExtractor, llm=BenchmarkMockLLM)
  └─ api.analyze(case.task, mode=case.mode)  × 26 用例（同 Benchmark.run）
  └─ extract_prediction / extract_strategy / real_trace → AccuracyEvaluator + StrategyEvaluator
  └─ 汇总 AblationResult → render_ablation_table + 落盘 reports/ablation/
```

- 默认路径零改动：`enable_rag/enable_memory` 默认 True，`benchmark` 不带 `--ablate` 时行为与现状一致。

## 5. 验证方式

- **单测（开关门控）**：`enable_rag=False` 构造 api 后 `_ingester is None`，分析过程无摄入/检索调用；`enable_memory=False` 时分析前后 `memory` 无任何写副作用（skill/outcome/archive 均为空）。
- **单测（AblationRunner 汇总）**：mock 2 个变体 × 小用例集 → 每组 `AblationResult` 指标正确、`render_ablation_table` 表头/数值对齐。
- **集成**：mock LLM + 固定页面，跑 full 与 no-rag 两组 → 对比表有数据；构造一个"答案只在知识库片段中"的用例，断言 full 命中而 no-rag 缺失（证明 RAG 差分可测）。
- **回归**：默认参数下既有 471 测试全绿；`benchmark` 不带 `--ablate` 输出与现状一致。

## 6. 实现优先级与工作量

- 优先级：**中低**（P2；功能不影响交付，但影响评测体系的组件归因能力，建议在 23-29 功能落地后或穿插实现）。
- 工作量：约 1-1.5 天。
  - `enable_rag`/`enable_memory` 开关 + 门控注入：0.5 天；
  - `AblationRunner` + 渲染 + CLI `--ablate`：0.5 天；
  - 测试 + 首份消融报告落盘：0.5 天。
- 前置：`evaluation/benchmark.py`（真实执行版，已就绪）；与设计文档 31（失败类型统计）共享 `BenchmarkReport`，可同批落地。
