# 设计文档 32 — RAG 真向量检索（深度补充）

> 对应 `implementation_plan.md` §16.1 RAG 行（"纯 TF-IDF 词袋，chromadb 从未实现"）。
> 触发：2026-08-14 深度复查——设计文档 02 承诺的"向量化 + chromadb + 混合检索 + 重排序"仅完成"词袋余弦 + 维度过滤"，
> 面试高频问题（embedding 选型 / chunk 策略 / 混合融合 / 重排）无实现可答。
> 依赖：`knowledge_base/competitor_store.py`、`knowledge_base/ingester.py`、`knowledge_base/retriever.py`；可选依赖 `[rag]`（chromadb / sentence-transformers 已在 pyproject.toml）。

## 1. 问题现状

- `CompetitorStore.search`（`knowledge_base/competitor_store.py:114`）是**纯 TF-IDF 词袋余弦**：`tokenize`（:49）仅正则切词、无中文分词/词干；`chunk_text`（:54）固定窗口硬切会从句中截断；检索无语义，维度命中靠硬编码 `+0.15`（:133）。
- `Retriever`（`knowledge_base/retriever.py`）的"混合"只是"词袋得分 + 竞品/维度过滤排序"，**没有向量维度**。
- chromadb / sentence-transformers 已声明在 `[rag]` 可选依赖，但**无任何调用点**——"向量检索"停留在注释（retriever.py:5）里。
- 影响：查询词与文档用词不同（同义/口语 vs 官网文案）时召回差，直接削弱 RAG 注入质量与消融实验（设计文档 30）的叙事说服力。

## 2. 目标设计

1. **可选向量层**：安装 `[rag]` 依赖后，摄入时对片段生成 embedding 写入 chromadb collection；检索时向量 + 词袋**混合融合**（推荐 Reciprocal Rank Fusion / RRF），未安装时无缝降级纯词袋（保持 CI 无 Key 无网络可复现）。
2. **语义 chunk**：在现有固定窗口上叠加标题/段落感知切分（按 `##`/空行/句子边界对齐），减少从句中截断；保留 `chunk_text` 兼容签名。
3. **重排（可选）**：对 top-k 候选用 cross-encoder / bge-reranker 精排，默认关闭（依赖重）。
4. **可观测**：检索埋点记录命中数/来源/得分来源（lexical/vector/fused），供评测与消融复用。

## 3. 模块/接口设计

### 3.1 `knowledge_base/vector_store.py`（新增）

```python
class VectorStore:
    """chromadb 向量集合：embedding 生成 + upsert + 语义检索。
    未安装依赖时 is_available() 返回 False，调用方降级词袋。"""
    def __init__(self, collection_name: str = "competitor_chunks",
                 model_name: str = "BAAI/bge-small-zh-v1.5") -> None: ...
    def is_available(self) -> bool: ...          # 依赖与模型可用性探测
    def embed(self, texts: list[str]) -> list[list[float]]: ...
    def upsert(self, chunk_ids: list[str], vectors: list[list[float]], metadatas: list[dict]) -> None: ...
    def search(self, query_vec: list[float], top_k: int) -> list[tuple[str, float]]: ...  # (chunk_id, score)
    def clear(self) -> None: ...
```

### 3.2 `CompetitorStore` 扩展（`competitor_store.py`）

- `add`/`add_many`/`clear` 同步维护 `VectorStore`（实例化成功后；`__init__` 接收 `vector_store: VectorStore | None = None`）。
- 新增 `search_hybrid(query, top_k, alpha=0.5)`：词袋得分 + 向量得分归一化后**加权融合**（或 RRF），返回 `(chunk, score, source)`；向量不可用 → 等价 `search`。
- `search`（纯词袋）保留——评测/消融按变体开关。

### 3.3 `Retriever` 扩展（`retriever.py`）

- `retrieve()` 默认改用 `search_hybrid`，返回类型不变（`list[TextChunk]`），`retrieve(..., strategy="hybrid"|"lexical")` 供消融（设计文档 30 的 `enable_rag` 已具备变体开关，本设计补充 `strategy` 粒度）。

### 3.4 语义 chunk（`ingester.py`）

- `chunk_text_semantic(text, size, overlap)`：先按标题/空行/句子切候选块，再折叠到 `size` 上限；`Ingester.ingest` 新增 `semantic: bool = False`，开启时用之，否则保留现状。

## 4. 接入方式

```
Ingester.ingest(semantic=True)  → 建块 → CompetitorStore.add_many → VectorStore.upsert
Retriever.retrieve(strategy="hybrid") → search_hybrid → 竞品/维度过滤（沿用）
未装 chromadb / 模型加载失败 → VectorStore.is_available()=False → 纯词袋，行为与现状一致
CLI/eval 无改动；benchmark --ablate 可加 hybrid/lexical 两列
```

- 默认行为**不变**（向量层仅在依赖可用时生效），CI 与既有 618 测试保持零真实网络。

## 5. 验证方式

- **单测（VectorStore）**：mock embedding 后 upsert/search 命中正确；依赖缺失时 `is_available()=False`、`search_hybrid` 降级词袋。
- **单测（融合）**：构造词袋与向量得分矛盾（同义词命中）→ RRF/加权融合取回语义相关片段；`alpha=0` 等价纯词袋。
- **单测（语义 chunk）**：含标题文档按标题边界切块，无句中截断；与固定窗口对比。
- **集成（差分）**：预置知识库含答案、查询用同义词（页面与查询用词不同）→ hybrid 命中、lexical 缺失——沿用设计文档 30 的 RAG 差分测试模式。
- **回归**：既有 RAG 集成测试（4 个）与消融 12 条全绿；全量测试通过。

## 6. 实现优先级与工作量

- 优先级：**高**（面试最高频 + 性价比最高，代码已预留 `[rag]` 依赖与接口）。
- 工作量：约 1-1.5 天。
  - `VectorStore` + chromadb 接入：0.5 天；
  - `search_hybrid` 融合 + `Retriever`/`Ingester` 扩展：0.5 天；
  - 语义 chunk + 测试 + 消融 `strategy` 列：0.25-0.5 天。
- 前置：设计文档 02（接口已就位）、30（差分测试模式可复用）；chromadb/sentence-transformers 为可选装，主代码不强制。
