# 设计文档 57 — RAG 精排：cross-encoder rerank（bge-reranker-v2-m3，默认启用）

> 触发：2026-08-24 复核检索链路——知识库检索为「词袋+向量融合排序」（`Retriever.retrieve` retriever.py:19 +
> `search_hybrid` competitor_store.py:150），top-k 全靠两路低维信号的线性加权，**无相关性精排**；doc 32 的
> "重排（可选）"与 doc 52 §2.4 的"不做 rerank 模型（bge-reranker 等）"均为非目标，检索精度天花板被
> 融合权重锁死。用户拍板：**补 cross-encoder 精排，模型 bge-reranker-v2-m3，默认启用**
> （模型可用即默认生效；不可用/未缓存静默降级现状 hybrid，与 doc 32/52 embed 纪律一致）。
> 前置：32（VectorStore/search_hybrid 混合检索）、52（embedding 可用性治理、retrieval_compare 对照）、
> 42（RetrievalEvaluator hit_rate 门禁）。

## 1. 问题现状

### 1.1 检索排序链路的真实状态

| 环节 | 位置 | 现状 | 缺口 |
|---|---|---|---|
| 召回 | `search_hybrid`（competitor_store.py:150-190） | 词袋余弦 + 向量距离各自 min-max 归一化，`alpha` 线性加权融合 | 排序分是低维信号加权和，非"查询-片段"语义相关性 |
| 业务重排 | `Retriever.retrieve`（retriever.py:33-40） | 竞品优先 + 维度加权（`_rank_by_dimension`） | 是约束，不是相关性 |
| 精排 | 无 | — | **cross-encoder 逐对打分缺失** |

### 1.2 两个具体问题

1. **相关性排序能力缺失**：`search_hybrid` 的融合分对「语义相关但词面/向量距离不是最优」的片段排不靠前；top_k 截断后
   精度由融合权重决定，无精排兜底。检索质量天花板 = 手动调的 `alpha`。
2. **收益无量化**：doc 42 的 `retrieval_hit_hybrid` 只证明 hybrid ≥ lexical，无法回答"精排后 recall@k 还能提多少"；
   doc 52 M3 的 retrieval_compare 只有 lexical/vector/hybrid 三路，无精排对照列。

### 1.3 现有可复用资产

| 资产 | 位置 | 复用方式 |
|---|---|---|
| 向量层可用性纪律 | `vector_store._semantic_embedder_cached`（只探测缓存不下载） | reranker 可用性同一纪律 |
| 可注入调用 | `embed_fn`（callable / "hash" / None） | `scorer` 可注入（测试确定性，对应 `embed_fn="hash"`） |
| 单一读入口 | `Retriever.retrieve`（`_react_rag_context`/`kb_recall`/`RetrievalEvaluator` 全走它） | 精排插在此一处 |
| 评测 harness | `evaluation/retrieval_compare.py`（doc 52 M3） | 加精排对照列 |
| 依赖 | `sentence-transformers` 已在 `[rag]` extra | CrossEncoder 零新依赖 |

## 2. 目标设计

1. **精排阶段**：`search_hybrid` 召回池 → cross-encoder 逐对打分 → 重排 → 竞品/维度业务约束 → top_k。
2. **默认启用可降级**：facade 在 `enable_rag` 时构造 `Reranker` 注入 `Retriever`；模型未缓存/不可用 →
   `is_available()=False` → 走现状 hybrid 排序（逐字节一致）。默认安装/slim/离线零影响——"默认启用"语义
   与 doc 32/52 的"可用自动升级、不可用静默降级"一致。
3. **召回池放宽**：精排路径召回池 `top_k×6`（现状 ×3）——精排提升精度不提升召回，须先保召回率。
4. **收益量化**：`retrieval_compare` 加 `hybrid+rerank` 列，recall@5 三路对比进对照表。

## 3. 模块/接口设计

### 3.1 新 `knowledge_base/reranker.py`（~90 行）

```python
class Reranker:
    """cross-encoder 相关性精排；模型未缓存/不可用 → is_available()=False，调用方走现状排序。"""
    def __init__(self, model_name: str = "BAAI/bge-reranker-v2-m3",
                 scorer: Callable[[str, list[str]], list[float]] | None = None) -> None:
        # scorer 可注入（测试确定性）；None → CrossEncoder(model).predict([(q, text) for text in chunks])
    def is_available(self) -> bool:
        # 探测缓存不下载（同 vector_store._semantic_embedder_cached 纪律）；scorer 注入恒可用
    def rerank(self, query: str, chunks: list[TextChunk]) -> list[TextChunk]:
        # 对 (query, chunk.text) 逐对打分，按分降序返回原对象列表；失败抛 RerankerUnavailableError
```

### 3.2 `knowledge_base/retriever.py`（~20 行增量）

```python
class Retriever:
    def __init__(self, store: CompetitorStore, reranker: Reranker | None = None) -> None: ...
    def retrieve(self, query, competitor, dimension="", top_k=5, strategy="hybrid", rerank=True):
        recall_pool = top_k * (6 if (rerank and self._reranker and self._reranker.is_available()) else 3)
        scored = self._store.search_hybrid(query, top_k=recall_pool)      # 现状
        if rerank and self._reranker is not None and self._reranker.is_available():
            try:
                chunks = self._reranker.rerank(query, [c for c, _s, _src in scored])
                scored = [(c, 1.0) for c in chunks]
            except RerankerUnavailableError:
                pass                                                       # 静默降级现状
        # 以下竞品优先 / 维度加权 / 取 top_k 逐字节不变
```

### 3.3 接线（`facade/api.py` + `evaluation/`）

- `CompetitorAnalysisAPI.__init__`：`enable_rag` 时构造 `Reranker()` 注入 `Retriever`（与 doc 52 注入 VectorStore 同路径）。
- `cli.py rag-warmup`（doc 52 M2）扩展：打印 reranker 模型缓存状态（`is_available`）。
- 启动状态日志（doc 52 §2.2）扩展一行：`rerank: available(v2-m3) / degraded(模型未缓存，跳过精排)`。
- `evaluation/retrieval_compare.py`：加 `hybrid+rerank` 模式列，recall@5 三路对比；mock 模式注入 fake `scorer`
  （确定性），真实 bge-reranker-v2-m3 手动跑取真实数据。

### 3.4 依赖与配置

- 零新 Python 依赖：`sentence_transformers.CrossEncoder` 已在 `[rag]` extra。bge-reranker-v2-m3 ~1.1GB（运行时按需缓存，不进镜像）。
- `review_config.yaml` 无新字段；reranker 走构造参数（与 doc 32/51 同哲学）。

## 4. 接入方式

```
enable_rag=True ──► Reranker(v2-m3) 注入 Retriever
                      │ 模型已缓存 → 精排生效（默认启用）
                      │ 模型未缓存 / 注入失败 → is_available()=False → 现状 hybrid（逐字节一致）
不注入 reranker（默认无 rag / slim）→ 现状，零影响
```

- 调用方零改动（`Retriever.retrieve` 签名新增默认参数，`kb_recall`/`_react_rag_context`/`RetrievalEvaluator` 透传默认）。
- 回退：删 `Reranker` 注入与 `retrieve` 精排分支即完全回退。

## 5. 验证方式

- **单测**：注入 fake `scorer`（确定性）断言精排改变 top_k 顺序且可复现；不注入/不可用 → 与现状逐字节一致
  （回归网）；`rerank=False` 参数显式关闭。
- **评测**：`retrieval_compare`（mock + fake scorer）产出三路 recall@5 对照表，断言 `hybrid+rerank ≥ hybrid`；
  真实 bge-reranker-v2-m3 手动跑一遍记录真实差距（doc 52 §7.4 纪律：真实结论以手动跑为准）。
- **回归**：benchmark 门禁用降级路径（模型未缓存）零突变；全量 `pytest -q` + ruff/mypy 通过。
- **实测**：`rag-warmup` 后启动日志显示 `rerank: available`；分析任务触发精排（trace 可见 tool/kb_recall 延迟）。

## 6. 实现优先级与工作量

| # | 里程碑 | 产出 | 工作量 |
|---|--------|------|--------|
| 0 | 设计文档 + 索引登记 | 本文档 + README 登记 | 0.2d ✅ 2026-08-24 |
| 1 | 精排核心 | reranker.py + Retriever 精排分支 + 单测 | 0.5d |
| 2 | 接线 + 可用性治理 | facade 注入 + rag-warmup/启动日志扩展 | 0.3d |
| 3 | 评测对照 | retrieval_compare 精排列 + 对照表 + 实测记录 | 0.5d |

- 前置：32/52（检索与可用性基建已就绪）；与 58/59/60 并行（独立文件，互不依赖）。
- 文档同步：doc 52 §2.4 删「不做 rerank 模型（bge-reranker 等）」一句（本设计推翻该非目标）。

## 7. 风险与缓解

1. **模型体积/内存**（v2-m3 ~1.1GB）：仅 `[rag]` + 手动 warmup 才加载；不缓存则降级，slim 镜像零影响。
2. **精排延迟**（top×6×~30 对，v2-m3 多语言较重，约秒级）：一次 retrieve 内做一次，量级可接受；若卡顿可降
   `_RERANK_RECALL_FACTOR` 或对候选池先按融合分截断再精排（后续按需）。
3. **降级路径漂移**：任何异常回退现状 hybrid（单测断言不注入 = 现状逐字节一致，回归网兜底）。
4. **测试触网**：`scorer` 注入隔离（同 doc 52 §7.3 纪律），禁止测试走 None 解析路径下载模型。
5. **精排与业务约束冲突**：精排只决定候选顺序，竞品优先/维度加权仍在其后强制执行——不破坏既有约束语义。
