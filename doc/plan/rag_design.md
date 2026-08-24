# 竞品分析 Agent — RAG 知识库设计文档

> 依据 `doc/ai_coding_agent_competitor_analysis_architecture.md` 第 5.6 节「RAG 竞品知识库」的原始设计蓝图，
> 将"向量化 + chromadb + 混合检索（向量 + 关键词）+ 重排序"的完整 RAG 能力落成可执行的设计。
> 本文档是**目标设计**，与当前 `knowledge_base/` 的"词袋降级实现"对照，明确渐进增强路径。

---

## 1. 设计目标

为竞品分析 Agent 提供**离线、可检索、带来源证据**的竞品领域知识库，让分析器/ReAct 在回答
功能 / 定价 / 版本 / 生态等问题时，能引用**预先摄入的官方文档片段**作为事实依据，从而：

1. **降低幻觉**：结论有 `source_url` 证据链支撑，而非依赖 LLM 记忆或实时抓取。
2. **加速二次分析**：同一竞品再次分析时直接命中知识库，减少重复抓取。
3. **支撑事实问答**：如"这个竞品支持哪些 IDE？"这类按竞品 × 维度的检索。

**与四层记忆的分工（不重叠）**：

| 模块 | 存什么 | 作用 |
|------|--------|------|
| `memory/` 四层记忆 | 分析过程元数据（技能/成功率/会话/笔记） | 管"**经验**" |
| `knowledge_base/` RAG | 竞品原始事实文档（官方文档/Changelog） | 管"**知识**" |

---

## 2. 总体架构

```
竞品官方文档 / Changelog / 评测报告
        │
        ▼
┌─────────────────────────────────────────────────────────┐
│  Ingester（摄取）                                        │
│  文档 → 清洗 → 分块(chunking) → embedding → 写入向量库   │
└─────────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────┐
│  CompetitorStore（存储）                                 │
│  · chromadb 向量库（按竞品 × 维度建 Collection）         │
│  · 元数据：competitor / dimension / source_url / chunk_id│
└─────────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────┐
│  Retriever（检索）                                       │
│  混合检索：向量相似度 + 关键词(BM25) → 融合 → 重排序      │
└─────────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────┐
│  注入 ReAct / 分析器（RAG 插件）                         │
│  enrich_prompt(knowledge=...) → {RAG_CONTEXT}            │
└─────────────────────────────────────────────────────────┘
```

---

## 3. 模块设计

### 3.1 Ingester（摄取器）— `knowledge_base/ingester.py`

**职责**：把竞品文档转成可检索的向量化片段。

```
ingest(competitor, dimension, text, source_url)
  → 清洗（去 HTML/噪声/重复空白）
  → chunk_text() 分块（size=1200, overlap=200，滑动窗口）
  → 每块生成 chunk_id（SHA256 摘要，去重）
  → embedding 向量化（sentence-transformers）
  → store.add_many() 写入向量库
```

**分块策略**：
- 固定窗口 `size=1200` 字符、`overlap=200` 重叠，保证跨块语义不丢失。
- 可选按标题/段落语义切分（渐进增强），优先保证确定性。

**embedding 模型**（可选依赖 `[rag]`）：
- 默认 `sentence-transformers` 本地模型（如 `BAAI/bge-small-zh-v1.5`，中英双语）。
- 未安装时降级为**词袋 TF-IDF**（见 §5 降级策略）。

### 3.2 CompetitorStore（存储）— `knowledge_base/competitor_store.py`

**职责**：按竞品 × 维度建向量索引，支撑事实问答。

- **向量库**：`chromadb`（独立数据目录 `~/.competitor_agent/vector_db/`，与记忆/凭据库隔离）。
- **Collection 划分**：按竞品建 Collection（或按 `competitor` 元数据过滤），维度作为元数据字段。
- **每条记录**：
  ```
  {
    chunk_id,          # SHA256 摘要，去重
    competitor,        # 竞品名（全局唯一键，与记忆/报告一致）
    dimension,         # feature / pricing / performance / ecosystem / roadmap / sentiment
    source_url,        # 证据来源（防幻觉透明化）
    text,              # 原始片段文本
    embedding,         # 向量（chromadb 内部存储）
  }
  ```
- **写入**：`add()` / `add_many()`；**读取**：`by_competitor()` / `by_dimension()`。
- **持久化**：chromadb 落盘；同时保留 JSON 快照便于审计与降级。

### 3.3 Retriever（检索器）— `knowledge_base/retriever.py`

**职责**：混合检索（向量 + 关键词）→ 融合 → 重排序。

```
retrieve(query, competitor, dimension, top_k)
  → 向量检索：query embedding 余弦相似度，取 top_k*3
  → 关键词检索：BM25（或 TF-IDF 词袋）命中，取 top_k*3
  → 融合：RRF（Reciprocal Rank Fusion）合并两路结果
  → 重排序：竞品过滤（同竞品优先）+ 维度加权（命中维度 +1.0）
  → 返回 top_k 个 TextChunk
```

**检索策略**：
1. **向量检索**（语义）：`sentence-transformers` 编码 query → chromadb 余弦相似度。
2. **关键词检索**（词面）：BM25 倒排索引，兜底语义检索的词汇覆盖不足。
3. **融合**：RRF 公式 `score = Σ 1/(k + rank)`，`k=60`，稳定合并两路排序。
4. **重排序**：同竞品片段前置；命中目标维度的片段额外加权。

**专用入口**：
- `retrieve_by_dimension(competitor, dimension)`：按竞品 × 维度直接取（无需查询词），
  用于"分析某竞品定价"时直接拉取该维度全部片段。

---

## 4. 与 Agent 主流程的接入（RAG 插件）

### 4.1 接入点

RAG 作为 **ReAct Agent 的插件**注入（对标架构文档的 RagPlugin），同时在**战术循环**提供背景知识。

| 接入点 | 位置 | 注入内容 |
|--------|------|---------|
| **ReAct 提示词** | `agent/prompts/react_system.py` 的 `enrich_prompt()` | `{RAG_CONTEXT}` = `Retriever.top_k(competitor, dimension)` |
| **战术循环** | `core/tactical_loop.py` 分析前 | 检索片段作为分析器背景证据 |

### 4.2 调用链

```
CompetitorAnalysisAPI.analyze(task)
  → StrategicPlanner.plan() 解析出 competitor + gaps
  → 对每个 gap（竞品 × 维度）:
      → Retriever.retrieve(query, competitor, dimension)
      → 片段注入分析器 / ReAct 提示词（{RAG_CONTEXT}）
      → 分析器产出 DimensionResult（引用 source_url 证据）
  → ReportBuilder 汇总（证据链透明化）
```

### 4.3 数据来源（灌库）

| 来源 | 采集方式 | 覆盖维度 |
|------|---------|---------|
| 官方文档站 | 文档站抓取 + RAG ingester | 功能 / 路线图 |
| Changelog | 抓取 + RAG ingester | 版本 / 功能演进 |
| 评测报告 | 抓取 + RAG ingester | 性能 |
| 官网 | 静态 HTML 或 Playwright | 功能 / 定价 / 生态 |

---

## 5. 降级策略（渐进增强）

**核心原则：零外部依赖也能跑，装上 `[rag]` 依赖自动升级。**

| 能力 | 降级实现（当前） | 增强实现（目标） |
|------|-----------------|-----------------|
| 存储 | 内存 + JSON（`JsonStore`） | chromadb 向量库 |
| 索引 | TF-IDF 词袋倒排 | embedding 向量索引 |
| 检索 | 词袋余弦 + 竞品/维度过滤 | 混合检索（向量 + BM25）+ RRF 融合 + 重排序 |
| embedding | 无（词袋） | sentence-transformers |

**切换逻辑**：
```python
if RAG_DEPS_AVAILABLE:   # chromadb + sentence-transformers 已安装
    store = ChromaCompetitorStore(...)   # 向量库
    retriever = HybridRetriever(...)     # 向量 + BM25 + RRF
else:
    store = CompetitorStore(...)         # 词袋降级
    retriever = BagOfWordsRetriever(...) # 余弦 + 过滤
```

---

## 6. 依赖清单（`pyproject.toml`）

```
optional [rag]:
  chromadb>=0.4
  sentence-transformers>=2.2
```

安装方式：`pip install -e ".[rag]"`

---

## 7. 验证方式

| 层级 | 验证 | 通过标准 |
|------|------|---------|
| 单元测试 | Ingester 分块 / Store 写入读取 / Retriever 检索 | 给定文档返回相关 chunk |
| 集成测试 | 灌入 Cursor 官方文档 → 检索"定价" | 命中 pricing 维度片段 |
| 端到端 | 二次分析同一竞品命中知识库 | 报告更快、证据带 source_url |
| 评测 | 检索命中率 / 幻觉率 | 命中率 ≥ 阈值、幻觉率 ≤ 5% |

---

## 8. 与当前实现的对照

| 架构文档原始设计 | 当前 `knowledge_base/` 实现 | 状态 |
|-----------------|---------------------------|------|
| 向量化（embedding） | 词袋 TF-IDF | ⚠️ 降级（预留增强） |
| chromadb 向量库 | JSON 存储 | ⚠️ 降级（预留增强） |
| 混合检索（向量+关键词） | 词袋余弦 + 竞品/维度过滤 | ⚠️ 降级（预留增强） |
| 重排序（RRF） | 维度加权排序 | ⚠️ 降级（预留增强） |
| 按竞品 × 维度索引 | 已实现（TextChunk 元数据） | ✅ 符合 |
| 分块摄入（chunking） | 已实现（1200/200 窗口） | ✅ 符合 |
| ReAct 插件注入 | `enrich_prompt(knowledge=...)` 已实现，未接线 | ⚠️ 待接入 |

> 当前实现是**零依赖可运行的词袋降级版**，本文档定义的是**完整向量化目标版**。
> 渐进增强路径：装 `[rag]` 依赖 → 切换 chromadb + sentence-transformers → 启用混合检索 + RRF 重排序。
