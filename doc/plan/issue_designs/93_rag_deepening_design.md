# 设计文档 93 —— 第四十三轮：RAG 做实（时效衰减 + bge-reranker 精排 + 循环依赖拆解 + 真实命中样本）

> 第四十三轮。来源：`doc/tech_review_2026-09-12.md` P1-6（2026-09-12 更正版）——
> hybrid 检索已按设计文档 32 落地（词袋+向量 alpha 融合、语义切块），评审"无 hybrid"
> 系误判；残余缺口为：无时效策略、无 rerank（设计 32 当时推迟）、无真实命中样本、
> knowledge_base↔memory 循环依赖。用户经 grill-me 三轮确认选择**做实**，决策如下：
>
> **用户决策（2026-09-12，grill-me 问答记录）**：
> 1. 时效策略 = **时间衰减降权**（不删除数据，只影响检索打分）；
> 2. 半衰期 = **30 天**（比推荐的 90 天更激进，竞品事实"近况优先"）；
> 3. 时间元数据 = **ingest 时间戳**（页面真实发布日期拿不到）；
> 4. 重复摄取同一内容 = **刷新为最近确认**（语义=最近一次验证该事实仍存在；
>    长期不抓的页面时间戳自然变老——正是期望行为）；
> 5. rerank = **引入 bge-reranker-v2-m3**（中英混合语料，~2.2GB）——
>    **推翻设计文档 32 的"依赖重、默认关闭"决定**，本文件即再决策记录；
> 6. 权重获取 = **本地权重探测 + 自动降级**（只探测 HF 本地缓存，无权重降级为
>    不精排、hybrid 结果直出；不触发网络，沿袭设计 32 `is_available` 教训：
>    代理 407 曾挂起 13 分钟）；权重由用户自行下载；
> 7. 精排幅度 = **hybrid top 15 候选精排取 top 5**（现状 top_k*3 召回不变）；
> 8. 循环依赖拆解 = **共享类型下沉 domain_types**；
> 9. 命中样本 = **真实任务沉淀**（本机现有配置跑 2-3 个真实竞品分析，
>    命中片段+来源 URL+时间戳 3-5 条进 `docs/rag_samples.md`）。

---

## 1. 现状核验（事实基线）

- hybrid 检索已在：`retriever.py::retrieve` 默认 `strategy="hybrid"` →
  `competitor_store.search_hybrid`（词袋/向量 min-max 归一化 + alpha=0.5 加权），
  `vector_store.py`（chromadb + 可插拔嵌入 + `is_available` 本地权重探测），
  `ingester.chunk_text_semantic`（标题/空行/句末边界，size=1200）。
- `TextChunk` 无时间字段；`Ingester.ingest` 不写时间戳。
- **bug（顺带修）**：`chunk_text_semantic(text, size, overlap)` 的 `overlap`
  是死参数——函数体从未使用（折叠逻辑只看 size）。本次实现 overlap
  （跨块保留尾部 N 字符重叠，保持签名不变）。
- 循环依赖：`facade/api.py:220-261` 函数内局部导入 + 注释自承认绕依赖。
  实施时先读码确认 knowledge_base 与 memory 互相引用的具体符号，
  共享类型下沉 `domain_types/`，目标：包间无循环 import、facade 无局部导入。

## 2. 方案（四条工作线）

### 2.1 时效衰减（A）
- `TextChunk` 增 `ingested_at: float`（epoch 秒）；`Ingester.ingest` 写入当前时间；
  **同 chunk_id 重复摄取刷新时间戳**（决策 4）。`CompetitorStore.add_many` 对已有
  id 更新时间戳字段；JSON 落盘含该字段。
- 衰减在检索打分侧：`retrieve`/`search_hybrid` 融合分乘 `0.5 ** (age_days / 30)`；
  `retrieve_by_dimension` 同样衰减排序。时钟可注入（`now_fn`），测试不依赖墙钟。
- **迁移语义**：历史 `knowledge_base.json` 片段无时间戳 → 载入时置为迁移时刻
  （= 首次以新版本加载的时间）。记录在此：旧知识一次性"变新"，随后按自然老化，
  可接受（不引入迁移版本号）。
- 向量层同步：`_load_chunks`/增量 upsert 路径带上时间戳，vector_store metadata
  存 ingested_at（chromadb metadata 字段）。

### 2.2 bge-reranker 精排（B）
- 新增 `knowledge_base/reranker.py`：`CrossEncoderReranker`——
  `is_available()` 只探测本地 HF 缓存权重文件（不触网，沿袭设计 32 实现）；
  `rerank(query, chunks, top_k)` 用 sentence-transformers `CrossEncoder`
  （模型 `BAAI/bge-reranker-v2-m3`）对候选打分；不可用/加载失败 → `None`，
  调用方降级现状行为。
- 接线：`Retriever.retrieve` hybrid 取 top 15 候选后，reranker 可用则精排，
  再经既有"竞品优先 + 维度加权"取 top 5；不可用则完全走现状路径
  （**测试环境无权重 → 全部既有测试行为不变**，这是本设计的回归安全阀）。
- API 注入：`CompetitorAnalysisAPI(reranker=...)` 可选参数，`enable_rag` 时默认
  尝试构造（探测失败→None），与 `vector_store` 注入同风格。

### 2.3 循环依赖拆解（C）
- 读码确认 knowledge_base↔memory 互相引用的符号清单，共享类型下沉
  `domain_types/`；facade `api.py:220-261` 局部导入改回顶层导入，
  去掉绕弯注释与 `Any` 标注（能恢复类型契约处恢复）。
- 若读码发现实际无 import 环（仅 facade 历史遗留局部导入），则收敛为
  "恢复正常导入 + 记录实证"，不强行下沉（设计修正记录在本文件附录）。

### 2.4 真实命中样本（D）
- 本机现有配置跑 2-3 个真实竞品分析（如 analyze Cursor 定价维度），
  从 trace/日志截取 3-5 条真实检索命中：query、命中片段摘要、来源 URL、
  ingested_at、融合分/精排分，写入 `competitor_agent/docs/rag_samples.md`。
- 唯一需要真模型/key 的工作线；key 不可用则留可执行命令 + 文件骨架，
  在设计文档附录标注"样本待补"。

## 3. 测试验收

- 衰减：`now_fn` 注入——同龄同分、30 天前半权、60 天 1/4 权、重复摄取刷新时间戳、
  无时间戳旧数据迁移默认；`retrieve_by_dimension` 衰减一致。
- rerank：`is_available` 无权重不触网（mock 文件系统探测）、可用时精排改变顺序
  （stub CrossEncoder）、不可用时与现状逐位一致（既有测试零改动通过即证）。
- overlap：跨块重叠字符存在且边界仍在句末/块界。
- 循环依赖：`python -c "import competitor_agent.knowledge_base; import competitor_agent.memory"`
  任意顺序无环；facade 无局部导入（grep 验证）。
- `tests/unit` 全量绿；ruff/mypy 改动文件清。

## 4. 风险权衡

- **衰减改变检索排序** → 所有带时间戳的路径默认行为随墙钟漂移：测试一律
  `now_fn` 注入；benchmark/golden 门禁若消费 RAG 需核查确定性（mock 路径
  不经真实时间戳或注入固定钟）。
- **reranker 2.2GB CPU 秒级延迟**：只在检索路径付一次；不可用时零成本降级。
  用户自承权重下载。
- **决策 5 推翻设计 32**：已在本文件记录再决策理由（中英混合语料 + 面试叙事
  收益 + 自动降级兜底使"依赖重"风险可控）。
- **样本工作线依赖本机 key**：失败不阻塞 A/B/C 交付，降级为"命令+骨架"。

---

## 实施修正（2026-09-12 实施记录）

1. **C 循环依赖实证**：`knowledge_base.competitor_store` 顶层导入
   `memory.json_store.JsonStore`，`memory.session_archive` 顶层导入
   `knowledge_base.competitor_store.tokenize`——**存在真实的包间互相引用**
   （双向顶层 import），但实测两种导入顺序均不炸：`competitor_agent/__init__`
   → facade 的导入顺序恰好把环掩盖（latent cycle）。按决策 8 将共享符号
   `tokenize` 下沉到新建的 `domain_types/text_utils.py`，
   `session_archive` 改从 domain_types 导入；`competitor_store` 保留
   `tokenize` 再导出（`evaluation/golden.py`、`agent/stagnation.py` 等既有
   导入点零改动）。此后 memory 对 knowledge_base 仅剩 TYPE_CHECKING 引用，
   包间依赖单向化（knowledge_base → memory.json_store）。facade
   `api.py:220-261` 局部导入全部改回顶层导入，`Any` 标注恢复为
   `CompetitorStore | None` 等真实类型契约；`CompetitorStore` 实例化经模块
   属性（`_competitor_store_mod.CompetitorStore`）以保持既有测试可
   monkeypatch 宿主模块。
2. **无时间戳片段不衰减**：`TextChunk.ingested_at` 默认 0.0，检索侧
   `decay_factor` 对 <=0 返回 1.0。这是既有测试零改动的关键——所有直接
   构造未打戳的片段行为与旧版逐位一致；衰减只作用于 Ingester 打戳或
   迁移后的片段。旧 JSON 迁移按"缺字段"判定（非 0 值），迁移时刻落盘
   保证只迁移一次。
3. **add_many 去重语义**：决策 4 落地为"同 chunk_id 已存在 → 只刷新
   时间戳，不重复追加"（顺带消除历史重复 id 导致的 chromadb
   DuplicateIDError 隐患）；传入片段 ingested_at<=0 时保留原时间戳不回退。
4. **overlap 启用护栏**：`overlap >= size` 或 `overlap <= 0` 时禁用重叠
   （重叠不小于窗口会整段重复，无意义）。该护栏使既有
   `chunk_text_semantic(size=60, overlap=200 默认)` 用例行为不变、零改动
   通过；生产默认（size=1200, overlap=200）重叠生效。重叠种子与下一句
   合计超 size 时舍弃重叠，块长上限优先于重叠。
5. **rerank 降级等价**：`Retriever.retrieve` 仅在 reranker 非 None 且
   `is_available()` 时走 top 15 召回 + 精排；否则路径与旧版逐位一致
   （既有测试零改动通过即证）。`strategy="lexical"` 消融路径不经精排。
6. **facade 向量层/知识库参数类型收紧**：`rag_store`/`vector_store` 参数
   标注由 `object | None` 收紧为真实类型（`CompetitorStore | None` /
   `VectorStore | None`），运行时对 duck-typed 注入无影响。
7. **D 样本已真实沉淀**（非骨架）：本机 `.env`（deepseek-v4-flash @ Ark）
   跑 3 个真实分析，46 个真实抓取片段入库，5 条命中样本（query/片段/URL/
   ingested_at/分数）落 `competitor_agent/docs/rag_samples.md`。采集环境
   两处如实记录在该文件：沙箱代理出网需 `SSL_CERT_FILE` 指系统 CA 包
   （httpx 默认 certifi 不含代理 CA）、URL 守卫 DNS 预检在代理环境不适用
   置 `block_private_urls: false`（同测试 `_OFFLINE_CFG` 模式）；
   本机无 bge 权重，向量/精排层按设计自动降级，样本分数为词袋×衰减。

