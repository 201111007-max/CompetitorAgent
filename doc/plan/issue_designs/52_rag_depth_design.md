# 设计文档 52 — RAG 深化：L1 记忆召回向量化 + embedding 可用性治理 + 检索质量对照

> 触发：2026-08-20 岗位差距分析（BOSS/猎聘 Agent 应用开发岗 JD 提炼）标出「词袋 TF 余弦，
> 无真 Embedding/向量库」。经代码核实该判断**只说对一半**：知识库 RAG（设计文档 32）已是真 RAG
> （chromadb + bge-small-zh + 词袋/向量 hybrid 融合），真正缺口是 L1 记忆召回
> `SessionArchive._rank_entries` 仍为纯词袋。
> 用户拍板：**不引入 FAISS**（chromadb 自带 HNSW 索引，几千 chunk 规模性能富余，避免重复依赖），
> 记忆召回复用现有 VectorStore/chromadb 接入点，词袋保留为降级路径。
> 前置：32（VectorStore/search_hybrid 混合检索）、35（SessionArchive 压缩与 recent_context 召回）。

## 1. 问题现状

### 1.1 两条检索链路的真实状态（核实结论）

| 链路 | 位置 | 现状 | 是否真 RAG |
|---|---|---|---|
| 知识库 RAG | `knowledge_base/vector_store.py::VectorStore` + `competitor_store.py::search_hybrid` | chromadb PersistentClient + bge-small-zh-v1.5（本地缓存才启用）+ hash_embed 确定性兜底 + 词袋/向量 alpha 融合；消费方 `_react_rag_context`（api.py:631） | ✅ 已是 |
| L1 记忆召回 | `memory/session_archive.py::_rank_entries`（:132） | 纯 TF 余弦词袋，对历史会话摘要排序 | ❌ 缺口 |

### 1.2 三个具体问题

1. **记忆召回语义盲**：`_rank_entries` 只做词面匹配——「定价」与「收费模式」、「护城河」与
   「竞争优势」这类语义相关但词面不重叠的条目召不回来，top_k 被词面噪声挤占。
2. **embedding 静默降级无感知**：装了 `rag` extra 但模型未预缓存 →
   `_semantic_embedder_cached` 只探测缓存不下载（vector_store.py:61）→ `is_available()=False`
   → 永远走词袋，用户无任何提示，「真 RAG」形同虚设。
3. **检索质量无数据**：词袋 vs 向量 vs hybrid 的召回差异没有对照实验支撑，
   「升级值得」目前只有定性判断。

### 1.3 现有可复用资产

| 资产 | 位置 | 复用方式 |
|---|---|---|
| 向量层（嵌入解析/降级/chromadb 封装） | `knowledge_base/vector_store.py::VectorStore` | 记忆侧建新实例，`collection_name` 隔离 |
| 增量同步 | `VectorStore.get_existing` | 老摘要惰性 upsert，不强制回填 |
| 可注入嵌入 | `embed_fn`（callable / `"hash"` / None 三级解析） | 测试用 `"hash"` 或注入 mock，确定性不触网 |
| 融合检索范式 | `CompetitorStore.search_hybrid` | 记忆召回照搬「向量优先、词袋降级」语义 |
| 评测 harness | `evaluation/benchmark.py` 确定性 mock 哲学 | 检索对照实验同口径 |

## 2. 目标设计

### 2.1 L1 记忆召回向量化

```
SessionArchive(..., vector_store: VectorStore | None = None)   # 新增可选注入

archive() / _rebuild_context() 后：
    若 vector_store 可用 → 摘要条目文本（_entry_text 同口径）embed + upsert
    到独立 collection "session_summaries"（与知识库 competitor_chunks 隔离）

recent_context(competitor, top_k, query)：
    query 非空且向量可用 → embed(query) → chromadb search → 按距离排序召回
    向量不可用 / 集合为空 / 任何异常 → 回退现有 _rank_entries 词袋路径（行为逐位不变）
```

- 条目 id：`{competitor}:{session_id 或 summary 索引}`，去重/覆盖随 `archive()` 幂等。
- 竞品过滤：chromadb `where={"competitor": competitor}` metadata 过滤，
  与 JSON 存储的按竞品分键语义对齐。
- 老化/删除：`_age_out` 剔除的条目在下次 `_rebuild_context` 时同步从集合删除
  （按 id delete），防止向量库返回已过期条目。

### 2.2 embedding 可用性治理

- **CLI 预缓存命令**：`python -m competitor_agent.cli rag-warmup`
  显式下载/校验 bge-small-zh-v1.5 缓存，打印向量层状态（模型路径/可用性/chromadb 版本）。
  这是唯一会触网的路径，且必须用户显式执行。
- **启动状态日志**：`CompetitorAnalysisAPI.__init__` 在 enable_rag 时打一行
  `向量层状态: available(bge-small-zh-v1.5) / degraded(模型未缓存，降级词袋)`，
  消除静默降级。

### 2.3 检索质量对照实验（可选 M3）

- `evaluation/retrieval_compare.py`：固定查询集（从 benchmark fixtures 提炼 ~20 条
  「查询 → 标注相关条目」对），分别跑 lexical / vector / hybrid 三模式，
  输出 recall@5 对比表落盘 `<data_dir>/reports/retrieval_compare_<date>.md`。
- embed_fn 注入确定性 mock（或 `"hash"`），CI 可复现；真实 bge 模型手动跑一遍取真实数据。

### 2.4 明确不做

- **不引入 FAISS**：chromadb 自带 HNSW，单机几千 chunk 规模无性能瓶颈；FAISS 无持久化/
  元数据管理，引入即重复依赖（2026-08-20 用户确认）。
- 不动知识库 `search_hybrid` 融合逻辑（doc 32 已定）。
- 不做 rerank 模型（bge-reranker 等）——量级不需要，后续按需再议。
- 不改 L2/L3/L4 记忆层（读侧无消费者是 doc 49 后的已知状态，不在本文档范围）。

## 3. 模块/接口设计

### 3.1 修改点（均为增量）

- `memory/session_archive.py`（~60 行增量）：
  - `__init__` 加 `vector_store: VectorStore | None = None`；
  - `_sync_vectors(competitor)`：`_rebuild_context` 末尾调用，增量 upsert + 过期删除；
  - `recent_context` 向量优先分支（异常/不可用回退词袋）。
- `memory/four_layer_memory.py`：`__init__` 加同名可选参数透传 SessionArchive。
- `facade/api.py`（~10 行）：enable_rag 时构造
  `VectorStore(collection_name="session_summaries", data_dir=<记忆 data_dir>)`
  注入 FourLayerMemory；加启动状态日志。
- `knowledge_base/vector_store.py`：零改动（`collection_name`/`data_dir`/`embed_fn`
  参数已齐备）。
- `cli.py`：`rag-warmup` 子命令（~30 行）。
- `evaluation/retrieval_compare.py`：新增（M3）。

### 3.2 测试

- `tests/unit/memory/test_session_archive_vectors.py`：
  - 注入 `embed_fn="hash"` 的 VectorStore（tmp_path），验证 recent_context 走向量召回；
  - 向量不可用（embed_fn=None 且无模型缓存）时回退词袋、结果与现状逐位一致；
  - 重复 archive 幂等（同 session_id 覆盖不增向量条数）；
  - TTL 老化后向量集合同步剔除。
- `tests/unit/cli/test_rag_warmup.py`：mock 下载路径，状态输出断言。
- 全量 `pytest -q` 不回归（默认无注入 = 词袋路径，现有测试零影响）。

## 4. 接入方式

- 配置：`review_config.yaml` 无新字段；向量注入走构造参数，与 doc 32 同哲学
  （可用自动升级、不可用静默降级词袋）。
- 依赖：无新依赖——chromadb/sentence-transformers 已在 `rag` extra；
  默认安装（无 extra）走词袋，行为与现状逐位一致。
- 兼容：不注入 vector_store = 完全现状；web_app/CLI/benchmark 默认路径不变。
- 回退：删注入参数与 `_sync_vectors` 调用即完全回退。
- 老数据：已有 session_summaries JSON 无向量 → 首次 archive/compress 时经
  `get_existing` 增量惰性 upsert，不做一次性强制回填（避免启动卡顿）。

## 5. 验证方式

- `pytest tests/unit/memory/test_session_archive_vectors.py -q` 全绿；全量不回归。
- 手动：`pip install -e ".[rag]"` + `rag-warmup` 后跑两次同竞品不同表述的分析任务，
  观察第二次任务的记忆注入是否召回语义相关历史（对比降级模式的词面召回）。
- M3：`python -m competitor_agent.evaluation.retrieval_compare`（mock）产出对比表；
  真实模型手动跑取 recall@5 真实差距。
- 启动日志确认：无模型缓存环境打 degraded，warmup 后打 available。

## 6. 实现优先级与工作量

| # | 里程碑 | 产出 | 工作量 |
|---|--------|------|--------|
| 0 | 设计文档 + 索引登记 | 本文档 + README/implementation_plan 登记 | 0.2d ✅ 2026-08-20 |
| 1 | 记忆召回向量化 | SessionArchive/FourLayerMemory/api 注入 + 单测 | 0.5d |
| 2 | 可用性治理 | rag-warmup CLI + 启动状态日志 + 单测 | 0.3d |
| 3 | 检索质量对照 | retrieval_compare + 对比表 + 实测记录 | 0.5d |

## 7. 风险与缓解

1. **降级路径行为漂移**：向量分支任何异常必须回退到与现状逐位一致的词袋结果——
   单测对「不注入 vector_store」做全量断言，现有 memory 测试即回归网。
2. **chromadb 双 collection 一致性**：知识库与记忆共用 `data_dir/chroma` 客户端路径，
   collection_name 隔离；删除/老化同步遗漏会导致向量库返回过期条目——
   `_sync_vectors` 与 `_rebuild_context` 同事务调用，单测覆盖老化场景。
3. **测试触网**：`_semantic_embedder_cached` 只探测缓存不下载的约束必须保持——
   所有新测试用 `embed_fn="hash"` 或注入 callable，禁止走 None 解析路径
   （与 conftest `_isolate_llm_env` 同级的隔离纪律）。
4. **向量召回质量不及预期**（hash_embed 语义弱、bge 未缓存时对照实验数据失真）：
   对比表标注所用 embed_fn；真实结论以 bge 手动跑为准，mock 数据只验证链路。
