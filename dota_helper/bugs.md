# DotaHelperAgent Agent 框架问题清单

> 从 Agent 框架完整性角度评估，按优先级排列。

---

## 🔴 P0 — 安全风险

### 1. 提示注入防御缺失

**位置**: `agent/react_loop.py:128`

**问题**: 用户输入直接作为 `user` 角色消息注入 LLM 上下文，无任何净化处理。攻击者可输入"忽略之前指令"、"你是 OpenAI 的模型"等注入模式劫持 Agent 行为。

```python
# react_loop.py:128 — 用户输入原样注入
context.messages = [
    {"role": "system", "content": system_prompt},
    {"role": "user", "content": initial_message},  # ← 无净化
]
```

**影响**: 攻击者可完全控制 Agent 的系统提示词，绕过所有安全限制。

---

### 2. 工具护栏/参数校验缺失 ✅ 已修复

**位置**: `agent/tool_guard.py`（新增） + `agent/tool_dispatcher.py`

**问题**: `validate_tool()` 仅检查工具名是否在集合中，参数 `args: Dict[str, Any]` 原样透传给 MCP Server，无任何类型、范围、长度校验。

**修复**: 在 `ToolDispatcher.dispatch()` 单一出口插入四层护栏（设计文档 `docs/superpowers/plans/post-match-review-agent/TOOL_GUARDRAIL_DESIGN.md`）：
- **参数校验** `ToolArgumentValidator`：基于 inputSchema 的轻量 JSON Schema 子集校验（type/required/minimum/maximum/maxLength/enum/items/maxItems/pattern）+ 归一化（`"123"`→`123`，拒绝 `True`）+ 全局硬约束表（ID 64 位、数量 ≤100、字符串 ≤200、`sites` 禁 URL）
- **敏感守卫** `SensitiveOperationGuard`：`request_match_parse(s)`/`inject_*_html` 默认 CONFIRM（确认回调放行，会话内记住），`search_dota_history` 默认 BLOCK
- **速率限制** `ToolRateLimiter`：令牌桶按工具+会话双层，超频拒绝；`tool_rate_limit=False` 可整体关闭
- **审计** `AuditLog`：所有调用（含被拒）记录 `timestamp/tool/args/decision/reason/session_id`

异常（`ToolArgumentError`/`ConfirmationRequired`/`RateLimitExceeded`/`ToolBlockedError`）由 `react_loop` 转为 Observation，`error_classifier` 分类为 DEGRADABLE。开关：`DotaHelperReActAgent.create(enable_tool_guard=True/False, tool_rate_limit=True/False)`。

**测试**: `tests/unit/test_tool_guard.py`（41 个用例，覆盖 Schema 校验/归一化/硬约束/敏感守卫/限速/审计/本地工具/ReAct 端到端）；全量回归 526 passed。

---

### 3. 凭据/密钥管理分散

**位置**: 散落于 `llm/client.py`、`mcp_server/server.py`、`mcp_server/tools/search_tools.py`、`observability/langfuse_adapter.py`

**问题**: API Key 通过 `os.getenv()` 分散在 4 个文件中读取，无统一凭据池、无加密存储、无密钥轮换机制。

| 位置 | 读取方式 |
|------|---------|
| `llm/client.py:35-41` | `os.getenv("OPENAI_API_KEY")` / `os.getenv("DEEPSEEK_API_KEY")` |
| `mcp_server/server.py:34` | `os.getenv("OPENDOTA_API_KEY")` |
| `mcp_server/tools/search_tools.py:49` | `os.getenv("SERPAPI_API_KEY")` |
| `observability/langfuse_adapter.py:34-35` | `os.getenv("LANGFUSE_PUBLIC_KEY")` / `os.getenv("LANGFUSE_SECRET_KEY")` |

**影响**: 密钥泄露无防护，无最小权限限制，Agent 拿到 LLM API Key 后可任意使用。

---

## 🟡 P1 — 可靠性问题

### 4. 错误分类与自动恢复缺失 ✅ 已修复

**位置**: `agent/error_classifier.py`（新增）

**修复**: 新增 `ErrorClassifier`，按 `ErrorCategory`（RECOVERABLE / DEGRADABLE / TERMINAL / UNKNOWN）分级处理异常：
- MCP 超时、LLM 限流（429/503/504）→ **RECOVERABLE**：自动重试
- MCP 连接断开、ValueError、RuntimeError → **DEGRADABLE**：跳过本轮继续
- LLM 认证错误（401/403/API Key）→ **TERMINAL**：终止推理
- 未知错误 → **UNKNOWN**：降级为 Thought 继续

**测试**: `tests/unit/test_error_classifier.py`（20 个用例）

---

### 5. Agent 层熔断器缺失 ✅ 已修复

**位置**: `agent/circuit_breaker.py`（新增）

**修复**: 新增 `CircuitBreaker` + `CircuitBreakerRegistry`：
- 连续失败 3 次 → OPEN（熔断 30s）
- 超时后 → HALF_OPEN（允许试探）
- HALF_OPEN 失败 → OPEN（超时加倍，最大 5min）
- 每个工具独立熔断，互不影响

**测试**: `tests/unit/test_circuit_breaker.py`（20 个用例）

---

### 6. 工具调用重试缺失 ✅ 已修复

**位置**: `agent/tool_dispatcher.py:150-175`

**修复**: `dispatch()` 集成熔断器检查 + 自动重试（超时/连接丢失重试 1 次，指数退避 1s→2s）。成功调用重置熔断器，重试耗尽记录失败。

**测试**: `tests/unit/test_tool_dispatcher_reliability.py`（11 个用例）

---

### 7. ReAct 循环状态无持久化 ✅ 已修复

**位置**: `agent/react_loop.py:27-44`（`ReActContext`）

**修复**: `ReActContext` 新增 `checkpoint_dir` + `save_checkpoint()` / `load_checkpoint()` / `clear_checkpoint()`。`execute()` 启动时优先从 checkpoint 恢复，每轮迭代后自动保存，推理完成后清理。

---

## 🟡 P2 — 扩展性问题

### 8. 插件系统缺失 ✅ 已修复

**位置**: `agent/plugin.py`

**修复**: 新增 `Plugin` 抽象基类（7 个生命周期钩子：`on_start`/`on_end`/`before_llm_call`/`after_llm_call`/`before_action`/`after_action`/`on_error`）+ `PluginRegistry`（注册/卸载/事件分发，管道模式，单个插件异常不中断链）。`react_loop.py` 的 `execute()` 中集成了 6 个钩子点。

---

### 9. 本地工具注册机制缺失 ✅ 已修复

**位置**: `agent/tool_registry.py`、`agent/tool_dispatcher.py`

**修复**: 新增 `ToolSchema`/`LocalTool`/`ToolRegistry`，支持 `register(name, handler, description, schema)`、同步/异步 handler 自动检测、`get_descriptions()` 格式化输出。`ToolDispatcher.dispatch()` 优先检查本地工具（本地 > MCP），`get_tool_descriptions()` 合并本地和 MCP 工具描述。

---

### 10. Agent 间协作机制缺失 ✅ 已修复

**位置**: `agent/message_bus.py`

**修复**: 新增 `MessageBus` 发布/订阅模式，`EventType` 枚举（`RESULT_READY`/`ERROR`/`STATUS_CHANGE`/`CUSTOM`），支持 `sender_filter`、消息历史查询、`max_history` 限制。子代理可通过共享 `MessageBus` 实例交换中间结果。

---

## 🟢 P3 — 效率问题

### 11. LLM 调用缓存缺失

**位置**: `llm/client.py:83-155`

**问题**: `chat()` 方法每次调用都直接请求 LLM API，无响应缓存。相同输入（messages + model + temperature）的重复调用浪费 Token。

**影响**: 重复查询浪费 Token 和成本，增加响应延迟。

---

### 12. RAG 知识库框架与内容扩充

**位置**: `mcp_server/helpers/rag_index.py`、`mcp_server/resources/heroes_txt/`

#### 12.1 现有 RAG 实现分析

当前 RAG 是纯 TF-IDF 词袋模型，不是真正的语义检索：

| 维度 | 现状 |
|------|------|
| 向量化 | 纯 NumPy 手写 TF-IDF，无 embedding 模型 |
| 检索 | 关键词匹配（0.7）+ 余弦相似度（0.3）混合评分 |
| 知识源 | 仅 127 个英雄 `.txt` 文件（技能说明书，无攻略内容） |
| 向量库 | 无（FAISS 可选，仅加速内积搜索） |
| 依赖 | 无 sentence-transformers / chromadb / faiss 声明 |

**知识源质量评估**：每个英雄 txt 仅包含官方技能数值（命石、技能、先天、魔晶、A杖），**没有出装推荐、对线技巧、团战定位、连招策略**等用户真正需要的攻略知识。用户问"幽鬼怎么玩"时 LLM 只能看到技能描述。

#### 12.2 知识缺口

| 知识类型 | 当前状态 | 用户问的频率 | 获取难度 |
|---------|---------|------------|---------|
| 英雄攻略（出装、连招、对线） | ❌ 没有 | 高 | 中 |
| 版本补丁说明 | ⚠️ 有 API 但未结构化入库 | 中 | 低 |
| 游戏机制（护甲、魔抗、中立物品） | ❌ 没有 | 中 | 低 |
| 策略知识（打盾时机、推高决策） | ⚠️ 有 YAML 提示模板但未入库 | 中 | 低 |
| 历史复盘结论 | ❌ 没有 | 低 | 高 |
| 装备信息 | ⚠️ 有 API constants 但未结构化 | 中 | 低 |

#### 12.3 RAG 选型建议

**推荐方案：Embedding + chromadb（方案二）**

| 方案 | 描述 | 复杂度 | 效果 |
|------|------|--------|------|
| ① 纯 TF-IDF 升级 | 保持现有，只扩充知识源 | ⭐ 极低 | ⭐⭐ 关键词匹配，语义理解差 |
| **② Embedding + chromadb** | **sentence-transformers + chromadb 嵌入式向量库** | **⭐⭐ 低** | **⭐⭐⭐⭐ 语义检索** |
| ③ 重排序 + LLM 生成 | 加 cross-encoder reranker + LLM 摘要 | ⭐⭐⭐⭐⭐ 极高 | ⭐⭐⭐⭐⭐ 最好但过度设计 |
| ④ 双通道混合 | TF-IDF + Embedding 并行检索合并排序 | ⭐⭐⭐ 中 | ⭐⭐⭐⭐ 兼容性好 |

**选型理由**：
- 当前 TF-IDF 无法处理语义查询（"后期怎么打"搜不到"后期决策"文档），Embedding 能解决
- 知识源已存在（127 个英雄 txt），只需新增 embedding 层
- chromadb 嵌入式无服务进程，pip install 即可，改动最小
- 未来可扩展：换 embedding 模型或加 reranker 都不需要改检索接口

**不选方案③**：DotaHelper 是单用户工具，重排序 + LLM 生成对游戏问答场景收益不大但复杂度翻倍。
**不选方案④**：纯 Embedding 语义检索已能覆盖关键词匹配场景（"幽鬼"的 embedding 和文档中"幽鬼"的 embedding 相似度自然高），无需维护两套检索。

#### 12.4 知识库目录结构设计

```
dota_helper/rag/
├── engine.py                  # RAG 引擎（embedding + chromadb 封装）
├── knowledge_base/            # 知识源目录（Markdown 文件，可 Git 管理）
│   ├── heroes/                # 英雄攻略（手动整理 + 爬取）
│   │   ├── spectre.md         # 幽鬼攻略：出装、连招、对线、团战
│   │   └── pudge.md
│   ├── mechanics/             # 游戏机制（手动整理）
│   │   ├── armor.md           # 护甲减伤公式
│   │   ├── magic_resist.md    # 魔抗叠加规则
│   │   └── neutral_items.md   # 中立物品机制
│   ├── patches/               # 版本补丁（自动爬取）
│   │   └── 7_41.md
│   └── strategies/            # 策略知识（从 YAML 提取）
│       ├── roshan_timing.md
│       └── ward_efficiency.md
└── chromadb_data/             # chromadb 持久化目录（自动生成，不 Git 管理）
```

**设计原则**：
- 知识源和检索分离：知识源是 Markdown 文件（人类可读、可 Git 管理），检索用 chromadb（向量索引自动构建）
- Metadata 过滤：每个文档带 tag（hero/mechanic/patch/strategy），检索时按类型过滤
- 增量更新：chromadb 支持 upsert，新增文档不需要重建整个索引
- 回退机制：chromadb 查询无结果时回退到现有 TF-IDF 搜索

#### 12.5 知识获取方案（按投入产出比排序）

**Phase 1 — 结构化现有数据（半天）**

| 数据 | 位置 | 做法 |
|------|------|------|
| 复盘技能 YAML | `prompts/skills/*.yaml` | 解析为 Markdown 文档入库 |
| 战术分析 YAML | `prompts/tactical_*.yaml` | 同上 |
| OpenDota constants | `api_samples/constants_*.json` | 定时拉取，结构化后入库 |
| 历史复盘报告 | SQLite session_archive | 提取结论，去重后入库 |

**Phase 2 — 爬取公开攻略站点（1 天）**

| 站点 | 内容 | 爬取方式 | 更新频率 |
|------|------|---------|---------|
| Dotabuff | 英雄胜率、出装统计、对位数据 | 页面解析（已有 httpx） | 每周 |
| Liquipedia | 英雄攻略、版本 Meta、赛事数据 | 页面解析（已有站点过滤） | 每月 |
| Dota 2 Wiki | 游戏机制、技能机制、物品机制 | API 或页面解析 | 每版本 |

**爬虫策略**：不实时爬，用定时任务（GitHub Actions / 系统 cron）每周更新一次。用户查询时只查本地知识库。

**Phase 3 — 复盘结论自动沉淀（2 天）**

```
复盘完成 → 提取结论（conclusions） → 向量化 → 存入 chromadb
下次类似比赛 → 检索历史结论 → 作为 context 注入 LLM
```

**过滤条件**：只存置信度 > 0.7 的结论，避免垃圾数据污染知识库。

**Phase 4 — 手动整理热门英雄攻略（2 天）**

挑选 10 个热门英雄（幽鬼、帕吉、影魔、卡尔等），人工整理出装推荐、对线技巧、团战定位，写入 Markdown 文件。

#### 12.6 知识库扩充管道

```
┌─────────────────────────────────────────────────┐
│                 知识库扩充管道                      │
├─────────────────────────────────────────────────┤
│                                                   │
│  定时任务（每周）                                   │
│  ├── 爬取 Dotabuff 英雄出装统计 → heroes/          │
│  ├── 爬取 Liquipedia 版本更新 → patches/           │
│  └── 爬取 Dota 2 Wiki 机制变更 → mechanics/        │
│                                                   │
│  触发式（每次复盘后）                               │
│  ├── 提取复盘结论（confidence > 0.7）              │
│  ├── 去重（检查 chromadb 中是否已有相似文档）       │
│  └── 存入 chromadb（带 metadata: match_id, patch） │
│                                                   │
│  手动（开发者操作）                                 │
│  ├── 新增英雄攻略 Markdown                         │
│  ├── 更新游戏机制文档                              │
│  └── 运行索引重建脚本                              │
│                                                   │
└─────────────────────────────────────────────────┘
```

#### 12.7 集成到 Agent 循环的设计

##### 12.7.1 当前架构的问题

现有 RAG 使用方式是**被动调用**——LLM 自己决定是否调 `rag_hero_intro` 工具：

```
用户输入 → LLM（无知识注入）→ LLM 决定是否调 rag_hero_intro → 拿到知识 → 回答
```

问题：
1. LLM 不知道什么时候该查知识库，系统提示词说"英雄攻略直接 Final Answer"，但 LLM 自身知识可能过时
2. RAG 结果只给 LLM 看一次，没有自动注入机制
3. 知识检索和 LLM 推理是串行的，LLM 必须先调工具才能拿到知识

##### 12.7.2 三层 RAG 集成架构

```
┌─────────────────────────────────────────────────────────────┐
│                    三层 RAG 集成架构                          │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  第一层：系统提示词注入（初始化时）                             │
│  ┌─────────────────────────────────────────────────────┐    │
│  │  ReactSystemPrompt.build()                          │    │
│  │  ├── 角色定义 + 工具描述                             │    │
│  │  └── + RAG 知识摘要（可选，注入高频知识片段）          │    │
│  └─────────────────────────────────────────────────────┘    │
│                                                              │
│  第二层：before_llm_call 插件（每轮迭代）                      │
│  ┌─────────────────────────────────────────────────────┐    │
│  │  RagPlugin.before_llm_call(messages)                │    │
│  │  ├── 提取最后一条 user message 作为 query            │    │
│  │  ├── 检索 chromadb → top_k 结果                     │    │
│  │  ├── 如果相似度 > threshold → 注入为 system 消息      │    │
│  │  └── 返回修改后的 messages                           │    │
│  └─────────────────────────────────────────────────────┘    │
│                                                              │
│  第三层：MCP 工具（LLM 主动调用）                              │
│  ┌─────────────────────────────────────────────────────┐    │
│  │  rag_hero_intro(query, top_k) — 已有，保留不变       │    │
│  │  rag_search(query, type_filter) — 新增通用检索工具    │    │
│  └─────────────────────────────────────────────────────┘    │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

##### 12.7.3 新增文件

```
dota_helper/rag/
├── __init__.py              # 包入口
├── engine.py                # RAG 引擎：embedding + chromadb 封装
├── plugin.py                # RagPlugin：before_llm_call 自动注入
└── knowledge_base/          # 知识源目录（Markdown，可 Git 管理）
    ├── heroes/              # 英雄攻略
    ├── mechanics/           # 游戏机制
    ├── patches/             # 版本补丁
    └── strategies/          # 策略知识
```

##### 12.7.4 RagEngine 设计

```python
class RagEngine:
    """RAG 引擎 — Embedding + chromadb 封装

    职责：
    1. 从 knowledge_base/ 加载 Markdown 文档
    2. 用 sentence-transformers 生成 embedding
    3. 存入 chromadb（带 metadata 过滤）
    4. 提供 search() 接口供插件和工具调用
    """

    def __init__(self, kb_dir="knowledge_base", persist_dir="chromadb_data"):
        self._kb_dir = Path(kb_dir)
        self._persist_dir = Path(persist_dir)
        self._embedding_model = None   # 懒加载
        self._collection = None        # 懒加载

    def _load_embedding_model(self):
        """懒加载 sentence-transformers 模型（首次 ~2s，之后常驻内存）"""
        from sentence_transformers import SentenceTransformer
        self._embedding_model = SentenceTransformer("all-MiniLM-L6-v2")

    def _get_collection(self):
        """懒加载 chromadb collection"""
        import chromadb
        client = chromadb.PersistentClient(str(self._persist_dir))
        self._collection = client.get_or_create_collection(
            name="dota_knowledge", metadata={"hnsw:space": "cosine"},
        )
        return self._collection

    def index_all(self):
        """扫描 knowledge_base/ 下所有 .md 文件，重建索引
        - 遍历 knowledge_base/{category}/*.md
        - 每个文件按 ## 标题切分为段落
        - 每段独立 embedding → upsert to chromadb
        - metadata: {category, filename, title, source}
        """

    def search(self, query, top_k=3, category=None, min_score=0.3):
        """语义检索
        - query → embedding
        - chromadb query(where={"category": category} if category)
        - 过滤 score < min_score
        - 返回 [{"content": "...", "metadata": {...}, "score": 0.95}]
        """

    def search_hero(self, hero_name):
        """快捷方法：按英雄名精确检索（metadata 过滤 category=hero + filename 匹配）"""
```

**关键设计点**：
- **懒加载模型**：`SentenceTransformer` 首次调用时加载，之后常驻内存
- **段落切分**：Markdown 按 `##` 标题切分，每段独立 embedding，检索粒度更细
- **相似度阈值**：低于 0.3 的结果丢弃，避免注入无关知识污染 LLM context
- **回退机制**：chromadb 查询无结果时调用现有 `rag_index.rank_hero_documents()` 回退

##### 12.7.5 RagPlugin 设计

```python
class RagPlugin(Plugin):
    """RAG 插件 — 在 LLM 调用前自动注入相关知识

    通过 PluginRegistry 注册到 ReActLoop，
    在 before_llm_call 钩子中检索并注入知识。
    """

    def __init__(self, engine: RagEngine, threshold=0.4):
        self._engine = engine
        self._threshold = threshold
        self._last_query = ""        # 避免重复检索
        self._last_injected = ""     # 避免重复注入

    async def before_llm_call(self, messages):
        """在 LLM 调用前注入 RAG 检索结果

        流程：
        1. 取最后一条 user 消息作为 query
        2. 如果 query 和上次一样 → 跳过（避免重复检索）
        3. 检索 chromadb
        4. 如果最高分 > threshold → 注入为 system 消息
        5. 如果最高分 < threshold → 跳过（不污染 context）
        """
        last_user = self._get_last_user_message(messages)
        if not last_user or last_user == self._last_query:
            return messages
        self._last_query = last_user

        results = self._engine.search(last_user, top_k=2)
        if not results or results[0]["score"] < self._threshold:
            return messages

        content = self._format_context(results)
        if content == self._last_injected:
            return messages
        self._last_injected = content

        messages = self._inject_context(messages, content)
        return messages

    def _format_context(self, results):
        """格式化检索结果为 LLM 可读的上下文"""
        lines = ["\n## 相关知识", ""]
        for r in results:
            cat = r["metadata"].get("category", "general")
            title = r["metadata"].get("title", "")
            lines.append(f"[{cat}] {title}:")
            lines.append(r["content"][:500])
            lines.append("")
        return "\n".join(lines)
```

**关键设计点**：
- **去重机制**：`_last_query` 和 `_last_injected` 避免同一轮迭代重复检索和重复注入
- **阈值过滤**：相似度低于 0.4 的不注入，避免无关知识干扰 LLM
- **注入位置**：追加到已有 system 消息末尾，不破坏 system/user/assistant 消息顺序
- **不阻塞**：检索失败或超时不影响主流程，静默跳过

##### 12.7.6 集成到现有代码

**修改 `react_agent.py`**（约 10 行）：

```python
# 在 create() 工厂方法中注册 RagPlugin
from dota_helper.rag.engine import RagEngine
from dota_helper.rag.plugin import RagPlugin

rag_engine = RagEngine()
rag_plugin = RagPlugin(engine=rag_engine)

plugin_registry = PluginRegistry()
plugin_registry.register(rag_plugin)

self._loop = ReActLoop(
    llm_client=self._llm_client,
    tool_dispatcher=self._tool_dispatcher,
    parser=self._parser,
    prompt_builder=self._prompt_builder,
    plugin_registry=plugin_registry,  # ← 新增
    ...
)
```

**修改 `react_system.py`**（约 5 行）：

```python
# 在系统提示词中告知 LLM 有自动 RAG 能力
_SYSTEM_ROLE_TEMPLATE = """...
## 自动知识检索

系统会自动检索相关知识库并注入到你的上下文中。
你无需主动调用 rag_hero_intro 工具来获取英雄知识，
直接使用注入的知识即可。

如果你需要更详细的特定知识，仍然可以调用 rag_hero_intro 工具。
..."""
```

##### 12.7.7 数据流完整链路

```
用户输入："幽鬼怎么玩"
  │
  ├─→ ReActLoop.execute()
  │     │
  │     ├─→ before_llm_call 插件
  │     │     └─→ RagPlugin.before_llm_call(messages)
  │     │           ├─ 提取 "幽鬼怎么玩" 作为 query
  │     │           ├─ engine.search("幽鬼怎么玩", top_k=2)
  │     │           │     └─ chromadb query → [{content: "幽鬼攻略...", score: 0.87}]
  │     │           ├─ score 0.87 > threshold 0.4 → 注入
  │     │           └─ messages 追加 system 消息：
  │     │              "相关知识：[hero] 幽鬼攻略：出装推荐..."
  │     │
  │     ├─→ LLM 调用（messages 已包含 RAG 知识）
  │     │     └─ LLM 看到 RAG 知识 + 系统提示词 → 直接 Final Answer
  │     │
  │     └─→ yield final 事件
  │
  └─→ 用户看到："幽鬼推荐出装：辉耀→分身斧→蝴蝶..."
```

##### 12.7.8 三种使用方式对比

| 方式 | 触发时机 | 优点 | 缺点 | 适用场景 |
|------|---------|------|------|---------|
| **插件自动注入** | 每轮 LLM 调用前 | 无感，LLM 不需要主动调工具 | 多一次 embedding 查询（~10ms） | 通用知识问答 |
| **MCP 工具调用** | LLM 主动选择 | LLM 可控，可指定参数 | LLM 可能忘记调 | 需要详细知识的场景 |
| **系统提示词注入** | 初始化时一次 | 零开销 | 提示词变长，不能动态适配 | 高频知识片段 |

**推荐组合**：插件自动注入（兜底）+ MCP 工具（补充），系统提示词注入暂不做。

##### 12.7.9 实施步骤

| 步骤 | 内容 | 文件 | 行数 |
|------|------|------|------|
| 1 | 创建 `rag/engine.py` — RAG 引擎 | 新增 | ~120 |
| 2 | 创建 `rag/plugin.py` — RagPlugin | 新增 | ~80 |
| 3 | 创建 `rag/__init__.py` | 新增 | ~5 |
| 4 | 修改 `react_agent.py` — 注册 RagPlugin | 修改 | ~10 |
| 5 | 修改 `react_system.py` — 告知 LLM 自动 RAG | 修改 | ~5 |
| 6 | 创建 `knowledge_base/` 目录 + 示例文档 | 新增 | ~50 |
| 7 | 安装依赖 `sentence-transformers` + `chromadb` | pyproject.toml | ~2 |

**总计**：新增 ~200 行，修改 ~15 行，安装 2 个依赖。

#### 12.8 实施优先级

| 阶段 | 内容 | 工作量 | 收益 |
|------|------|--------|------|
| Phase 1 | 把现有 YAML 技能/战术模板结构化入库 | 半天 | 中 |
| Phase 2 | 爬取 Dotabuff 英雄出装统计 | 1 天 | 高 |
| Phase 3 | 爬取 Dota 2 Wiki 游戏机制 | 1 天 | 高 |
| Phase 4 | 复盘结论自动沉淀 | 2 天 | 中（需积累） |
| Phase 5 | 手动整理 10 个热门英雄攻略 | 2 天 | 高 |

**建议**：先做 Phase 1 + Phase 2，两天内让 RAG 知识库从"只有技能说明书"变成"有出装统计 + 策略知识"。Phase 3-5 看用户反馈再决定是否投入。

---

### 13. 输出验证/合规检查缺失

**位置**: `agent/response_parser.py:93-135`

**问题**: LLM 输出解析失败时直接返回 `THOUGHT` 类型，无格式校验。无事实性校验、无内容安全过滤、无隐私信息泄露检查。

**影响**: LLM 输出可能包含幻觉信息、有害内容或敏感数据泄露。

---

## 优先级建议

| 优先级 | 模块 | 建议行动 |
|--------|------|---------|
| **P0** | 提示注入防御 | 添加输入净化层，检测注入模式，隔离用户输入与系统提示词 |
| **P0** | 工具护栏 | 添加参数类型/范围校验，敏感操作二次确认，速率限制 |
| **P0** | 凭据管理 | 实现统一凭据池，加密存储，支持密钥轮换 |
| **P1** | 错误分类与恢复 | 实现错误分类器，分级恢复策略（重试→降级→跳过→终止） |
| **P1** | 熔断器 | 实现工具级熔断器，连续失败后自动暂停 |
| **P1** | 状态持久化 | 为 ReActContext 添加 checkpoint 机制 |
| **P2** | 插件系统 | 定义生命周期钩子，实现插件注册 API |
| **P2** | 工具注册 | 实现本地 register_tool API |
| **P2** | Agent 协作 | 实现 Agent 间消息总线 |
| **P3** | LLM 缓存 | 添加语义缓存，配置 TTL |
| **P3** | RAG 集成 | 将向量检索集成到 ReAct 循环 |
| **P3** | 输出验证 | 添加格式校验和内容安全过滤 |
