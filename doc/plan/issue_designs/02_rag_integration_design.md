# 设计文档 02 — RAG 完全未接线

> 对应 `implementation_plan.md` 第 11 节问题 2（P0）
> 详细 RAG 目标设计见 `doc/plan/rag_design.md`，本文档聚焦"接入主流程"。

## 1. 问题现状

- `knowledge_base/`（`Ingester` / `CompetitorStore` / `Retriever`）只在自身和测试中被引用，主流程 `CompetitorAnalysisAPI` **完全没有知识库**。
- 实际实现是**词袋余弦检索**（`competitor_store.py:102-124`），向量检索从未实现（`retriever.py:6` 注释"可选"）。
- 无任何代码往知识库**灌数据**（`Ingester` 只在测试被调用）。

## 2. 目标设计

1. 将 RAG 接入主流程，作为分析器的**外部事实依据**，降低幻觉。
2. 实现**数据灌入链路**：采集到的竞品文档自动摄入知识库。
3. 按 `rag_design.md` 实现向量化 + chromadb + 混合检索 + 重排序（渐进增强）。

## 3. 模块/接口设计

### 3.1 知识库实例化（`facade/api.py`）

`CompetitorAnalysisAPI.__init__` 增加知识库组装：

```python
self._store = CompetitorStore(data_dir=...)
self._ingester = Ingester(store=self._store)
self._retriever = Retriever(store=self._store)
```

### 3.2 灌库链路（采集后自动摄入）

在 `TacticalLoop` 采集到 `Observation` 后，将 `observation.raw_text` 摄入知识库：

```python
self._ingester.ingest(
    competitor=obs.competitor,
    dimension=obs.dimension,
    text=obs.raw_text,
    source_url=obs.source_url,
)
```

### 3.3 检索注入（分析前）

分析器分析前检索相关片段作为背景证据：

```python
chunks = self._retriever.retrieve(
    query=gap.description,
    competitor=gap.competitor,
    dimension=gap.dimension,
    top_k=5,
)
# 片段注入 analyzer 的 prompt（{RAG_CONTEXT}）
```

### 3.4 向量化渐进增强（`knowledge_base/`）

按 `rag_design.md` §5 降级策略：装 `[rag]` 依赖后切换 chromadb + sentence-transformers + 混合检索 + RRF 重排序。

## 4. 接入方式

```
CompetitorAnalysisAPI.analyze(task)
  → StrategicPlanner.plan() 解析 competitor + gaps
  → 对每个 gap（竞品 × 维度）:
      → TacticalLoop 采集 → Ingester 摄入知识库
      → Retriever.retrieve() 检索片段
      → 片段注入分析器 prompt（{RAG_CONTEXT}）
      → 分析器产出 DimensionResult（引用 source_url 证据）
  → ReportBuilder 汇总
```

## 5. 验证方式

- **单元测试**：Ingester 摄入 → Retriever 检索命中正确片段。
- **集成测试**：分析 Cursor 定价时，知识库命中 pricing 维度片段。
- **端到端**：二次分析同一竞品命中知识库，报告更快、证据带 source_url。

## 6. 实现优先级与工作量

- 优先级：**高**（P0，核心卖点）。
- 工作量：约 2-3 天（先接词袋版，再渐进增强向量版）。
- 建议先解决"数据从哪来"（灌库链路），再接检索注入。
