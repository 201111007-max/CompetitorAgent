# 设计文档 56 — 上下文压缩可逆化：kb_recall 取回闭环 + Lead 摄入补齐 + 核验事实 pinning

> 触发：2026-08-21 面试叙事深挖（"压缩有损是硬伤"追问）引出对 doc 46 历史压缩的复核。
> **核实后修正了口头分析的一个错误**：doc 46 的 `_compress_history`/`_compress_history_native`
> 并非"静默丢弃中间步"——`_fold_pair`/`_fold_native_turn` 已为每个被折叠步生成一行规则摘要
> （`调用 <tool>[URL] → 结果前 80 字`，react_agent.py:400/503），指针摘要雏形**已存在**。
> 真实缺口是四个：① 摘要块封顶 6 行（`_SUMMARY_MAX_LINES`）滚出后更旧的指针彻底消失，且
> 摘要未告知模型"去哪取回全文"——指针不可操作；② 循环内**无知识库取回工具**，模型看到
> 指针也够不到内容（假可逆）；③ Lead 的 `_react_web_extract`（api.py:797）抓取后**不摄入**
> 知识库——只有子 Agent 的 `_web_extract_for`（api.py:817）摄入，Lead 抓的内容即使将来有
> 取回工具也取不到；④ 已核验数值无 pinning，折叠后核验依据丢失（损失最严重的一类）。
> 用户拍板四决策（2026-08-21）：**Q1 范围** = 分三里程碑（M1 可逆化核心 / M2 事实 pinning /
> M3 对照实验门禁化）；**Q2 kb_recall** = Lead + 子 Agent 都加（含 Lead 摄入补齐配套）；
> **Q3 摘要** = 纯规则（M1 不引入 LLM 摘要调用，保 mock 确定性）；**Q4 阈值** =
> `_MAX_HISTORY_STEPS=8` 配置化进 config（默认 8 不变）。
> 业界依据见 §8。前置：46（压缩机制本体）、49（extra_tools 注入模式）、52（Retriever 向量化）。

## 1. 问题现状

### 1.1 现有机制（doc 46/53，核实后）

- 文本协议 `_compress_history`（react_agent.py:344）与 native 协议 `_compress_history_native`
  （react_agent.py:435）：工具步超 `max_history_steps`（默认 8）后，保留 system + 首条任务 +
  最近 `2*max_history_steps` 条，最旧步逐对折叠为一行确定性摘要并入摘要块。
- 摘要块自身封顶：`_SUMMARY_MAX_LINES=6` 行（旧行滚出）+ `_SUMMARY_MAX_CHARS=1200`。
- `ReactAgent.run` 已有 `max_history_steps` 参数，但 `ReactLoop.run_with_result`
  （react_loop.py:102）**不透传**——facade 无法注入，实际恒为默认值 8。

### 1.2 四个真实缺口

1. **指针不可操作**：摘要行含工具名/URL/结果前 80 字，但没有任何一句告诉模型"全文在哪、
   怎么取回"；6 行滚出后连指针也消失。
2. **无取回能力**：ReAct 工具面（8 工具 + make_plan/delegate/复核工具）无知识库检索工具——
   RAG 检索只在循环启动时经 `rag_fn` 注入系统提示（react_loop.py:186），循环内模型够不到
   Retriever。指针 + 无取回 = 假可逆，模型只剩两条坏路：幻觉填空 / web_extract 重抓 URL
   （花钱且知识库内非 URL 内容够不到）。
3. **Lead 摄入缺口**：`_react_web_extract` 抓完直接返回不摄入；子 Agent `_web_extract_for`
   才摄入（`_ingest_fetched`，幂等由内容哈希保证）。Lead 路径的观察不落知识库。
4. **核验事实无 pinning**：`validate_facts` 等复核工具的核验结论随普通步一起折叠，
   已交叉核验的关键数值（价格/星数/性能分）丢失核验依据。

## 2. 目标设计

### 2.1 M1 可逆化核心（Q1/Q2/Q3/Q4）

**① kb_recall 工具（走 `extra_tools`，不进 TOOLS/TOOL_SPECS）**

- 签名 `kb_recall(query: str) -> str`；背后是 facade 闭包复用现有 `Retriever`
  （`retrieve(query, competitor, dimension, top_k=5, strategy="hybrid")`，retriever.py:19），
  片段拼接后截断到 `collector.max_content_chars`；零新存储、零新依赖。
- **注入模式与 make_plan/delegate 相同**（`build_react_dispatcher(extra_tools=...)`，
  api.py:603/692）：原因——kb_recall 有状态（依赖 Retriever 实例与竞品上下文），
  TOOLS 是无状态函数面且会被 MCP 同源自动曝光（doc 40），有状态工具进 TOOLS 会
  迫使 MCP server 装配知识库。走 extra_tools 则 **MCP 工具面零变化、TOOL_SPECS 零变化**。
- Lead 侧：闭包内 competitor 懒绑定——`make_plan` 落地后经 `loop.plan["competitor"]`
  回填，落地前以 `competitor=""` 全局检索（Retriever 的同竞品优先过滤对空串自然失效为
  全局排序，行为合理）。
- 子 Agent 侧：`build_subagent` 已有 `extra_tools` 参数（subagent_registry.py:107），
  按 `(competitor, dimension)` 绑定（与 `_web_extract_for` 同模式，api.py:817）。
- 知识库为空 / Retriever 未装配：工具仍注册，返回可读信息"知识库暂无可检索内容"——
  工具面稳定，不随状态缺 tool（避免模型因工具消失而困惑）。

**② Lead 摄入补齐**

- `_react_web_extract` 抓取成功后调 `_ingest_fetched`（幂等，内容哈希 chunk_id）；
  competitor 同样懒绑定，plan 落地前摄入到 `dimension="web"` 通用域；
  守卫拦截/抓取失败/空文本的占位文本不摄入（沿用 api.py:835 既有纪律）。

**③ 指针摘要增强（纯规则）**

- 摘要块指引语句改为可操作：前缀从"仅回顾已完成的动作，不可当作最新状态"增补为
  "……；折叠步的完整内容已摄入知识库，可用 kb_recall(query) 取回"。两协议共用。
- `_SUMMARY_MAX_LINES=6` 滚出策略**不变**（防摘要反向膨胀）——指针可滚出、内容不丢，
  取回由 kb_recall 兜底，这才是"可逆"的完整闭环。

**④ 阈值配置化（Q4）**

- `config/loader.py` 新增 `AgentConfig`（`max_history_steps: int = 8`），
  `review_config.yaml` 新增 `agent` section（默认 8，行为不变）；
  `ReactLoop.__init__` 增 `max_history_steps` 透传参数，`run_with_result` 传给
  `agent.run`；facade `_react_loop` 与 `build_subagent` 从 config 注入。

### 2.2 M2 核验事实 pinning

- 新增 pinned 段：transcript 捕获（`on_step`）中 `validate_facts`/`detect_conflict`
  工具返回的核验通过结论，按 `fact_verification` 键空间（价格/星数/性能分等
  `_VERIFY_NUMERIC_KEYS`）抽取为一行一条的「已核验事实」清单。
- pinned 段作为独立 user 消息固定在摘要块之后，**永不折叠、永不滚出**；
  自身封顶（行数 + 单行字符），超限只保最近核验（旧核验的结论已沉淀进报告details）。
- 双协议共用同一 pinned 段插入逻辑（消息形状两协议兼容：普通 user 消息）。

### 2.3 M3 对照实验（门禁化）

- 新增 behavior_eval 场景（或独立 evaluation 模块）：ScriptedLLM 构造 >8 步脚本，
  第 9 步让模型"需要"早期已抓取 URL 的内容——断言修复后模型调 `kb_recall`
  而非重发 `web_extract`（重复抓取次数 = 0）；断言 pinned 段在压缩后仍在消息列表。
- 指标进 `BenchmarkReport.behavior`（doc 42 既有五字段旁新增）：`refetch_after_fold`
  （折叠后重复抓取次数，门禁 = 0）；HARNESS_VERSION 不变（新增字段非重定既有门禁）。

### 2.4 明确不做

- **不做 LLM 摘要**（Q3）：压缩点零额外 LLM 调用；留为可选后续里程碑（配置切换）。
- **kb_recall 不进 TOOLS/TOOL_SPECS**：MCP 工具面不动（见 2.1①）。
- **不动 LangGraph 引擎**：其循环体在 `run_langgraph` 内部（节点仅复用
  `ReactAgent.build_system_prompt`），压缩/取回本次只覆盖 ReactLoop 路径；
  与 doc 51「双引擎差异化结论」纪律一致。
- **不改 `_SUMMARY_MAX_LINES`/滚出策略**（防膨胀优先，取回由 kb_recall 兜底）。
- **不做 MemGPT 式内存分页 / logit mask**（API 层摸不到 logit；12 步垂直任务不需要
  完整分页机制，依据见 §8）。

## 3. 模块/接口设计

### 3.1 修改点

- `agent/react_agent.py`（~10 行）：摘要块指引语句增补 kb_recall 取回提示（两协议共用
  `_SUMMARY_MSG_PREFIX` 拼接处）；`_fold_pair`/`_fold_native_turn` 行为不变。
- `agent/react_loop.py`（~10 行）：`__init__` 增 `max_history_steps`，
  `run_with_result` 透传 `agent.run`。
- `facade/api.py`（~60 行）：
  - `_build_kb_recall(competitor_fn, dimension)` 闭包工厂（Lead 懒绑定 / 子 Agent 按维度绑定）；
  - `_react_loop` 与 `build_subagent` 调用点的 `extra_tools` 增 `kb_recall`；
  - `_react_web_extract` 增补 `_ingest_fetched`（competitor 懒绑定 cell）；
  - config 注入 `max_history_steps`。
- `agent/subagent_registry.py`（~5 行）：`build_subagent` 透传 `max_history_steps`。
- `config/loader.py` + `config/review_config.yaml`：`AgentConfig` + `agent` section。
- M2：`facade/api.py` pinned 段收集（on_step 包装）+ `react_agent.py` pinned 消息插入点。
- M3：`evaluation/behavior_eval.py` 折叠取回场景 + `evaluation/benchmark.py` behavior 字段。

### 3.2 测试

- `tests/unit/agent/test_kb_recall.py`：闭包检索返回片段拼接 / 空库可读信息 /
  competitor 懒绑定（plan 前全局、plan 后同竞品优先）/ 子 Agent (competitor,dimension)
  绑定 / 结果截断到 max_content_chars / 回灌路径 wrap_untrusted 包裹（复用现有机制）。
- `tests/unit/agent/test_compress_pointer.py`：摘要块含 kb_recall 指引（双协议）/
  滚出策略不变 / fold 行格式回归 / `max_history_steps` 经 ReactLoop 注入生效。
- Lead 摄入：`_react_web_extract` 成功后 `_ingest_fetched` 被调（plan 前通用域 /
  plan 后竞品绑定）/ 占位文本不摄入。
- M2：pinned 段压缩后存活 / 键空间封顶 / 无核验时不插入空段。
- M3：折叠后重抓次数 = 0（mock 确定性）/ pinning 保留断言进门禁。
- 回归：`test_react_context_cap.py` 9 条 pin 的摘要前缀形状需同步更新（指引语句变化）；
  全量 `pytest -q` 不回归（mock 脚本不主动调 kb_recall，既有门禁零突变）。

## 4. 接入方式

- 配置：`agent.max_history_steps`（默认 8，不设 = 现状逐位不变）。
- 依赖：零新 Python 依赖（复用 Retriever/chromadb 既有渐进增强）。
- 兼容：知识库为空时 kb_recall 返回可读信息、摘要指引语句变化为纯文本增强——
  无 Key 无网络路径行为不变；MCP server 工具面不变。
- 回退：删 kb_recall 闭包 + 摄入增补 + 指引语句 + AgentConfig 即完全回退。

## 5. 验证方式

- 上述单测全绿；全量 `pytest -q` 不回归；ruff/mypy 改动文件通过。
- M3 对照报告：修复前后跑同一 >8 步场景，`refetch_after_fold` 从 >0 降为 0；
  benchmark `--gate`（doc 55 M1）持续绿。
- 手动：真实 Key 跑一次长链路分析，观察压缩日志行后模型是否以 kb_recall 取回
  （trace 瀑布图 doc 54 M2 可直接观察 tool.kb_recall span）。

## 6. 实现优先级与工作量

| # | 里程碑 | 产出 | 工作量 |
|---|--------|------|--------|
| 0 | 设计文档 + 索引登记 | 本文档 + README/implementation_plan 登记 | 0.2d ✅ 2026-08-21 |
| 1 | 可逆化核心 | kb_recall（Lead+子Agent）+ Lead 摄入补齐 + 摘要指引 + 阈值配置化 + 单测 | 1d |
| 2 | 事实 pinning | pinned 段收集/插入/封顶 + 单测 | 0.5d |
| 3 | 对照实验 | behavior 场景 + `refetch_after_fold` 门禁 | 0.5d |

## 7. 风险与缓解

1. **工具面扩大改变真实 LLM 行为**：kb_recall 增加一个决策分支，真实模型可能滥用/误用。
   缓解：工具描述明确"仅当需要回溯被折叠步骤的完整内容时使用"；mock 不主动调用，
   既有门禁零突变；M3 对照实验量化真实收益。
2. **Lead 摄入污染知识库**：plan 前摄入无 competitor 归属的通用域片段可能稀释检索。
   缓解：`dimension="web"` 标记 + 摄入幂等；检索同竞品优先过滤天然降权无关片段。
3. **摘要指引语句变化破坏 pin 住的形状断言**：`test_react_context_cap` 9 条逐位断言需
   同步更新——这是设计内的回归网维护，不是行为回归。
4. **pinned 段膨胀**（M2）：键空间有界 + 行数/字符双封顶 + 只保最近核验。
5. **kb_recall 返回内容注入风险**：知识库内容源自抓取的外部页面。
   缓解：回灌路径既有 `wrap_untrusted` 自动包裹（react_agent.py:161/283），零新增暴露面。

## 8. 业界依据（本设计每层对应的来源）

| 设计点 | 来源 | 借鉴内容 |
|---|---|---|
| 可逆压缩原则（丢内容留指针） | [Manus: Context Engineering for AI Agents](https://manus.im/blog/Context-Engineering-for-AI-Agents-Lessons-from-Building-Manus)（2025-07） | 原则 3「file system as context」：compression 必须 restorable——丢页面内容但留 URL/路径 |
| 取回工具与指针不可分割 | 同上 + [MemGPT (arXiv:2310.08560)](https://arxiv.org/abs/2310.08560) | Manus 的文件系统上下文以 agent 持有 read 工具为前提；MemGPT 的 archival memory 必配 `archival_memory_search` function call |
| tool result clearing 是最安全的压缩 | [Anthropic: Effective context engineering for AI agents](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)（2025-09） | 清掉深层历史原始 tool 结果；compaction 保留关键决策、丢弃冗余输出 |
| pinned 选择性保留 | 同上 + [OpenHands Condensation](https://www.openhands.dev/blog/openhands-context-condensensation-for-more-efficient-ai-agents) / [SDK 论文 §4.6 (arXiv:2511.03690)](https://arxiv.org/html/2511.03690v1) | Claude Code 保架构决策/未解决 bug；OpenHands 摘要保 goals/progress/关键文件 + `keep_first` 永不折叠 |
| 四策略分类框架 | [LangChain: Context Engineering for Agents](https://blog.langchain.com/context-engineering-for-agents/) / [repo](https://github.com/langchain-ai/context_engineering) | Write/Select/Compress/Isolate——本项目已有 Isolate（子 Agent）+ 半个 Write（RAG 摄入），本设计补齐取回闭环 |
| **明确不借鉴** | Manus 原则 2（logit mask）/ MemGPT 完整分页 | API 层摸不到 logit；≤12 步垂直任务不需要 OS 式分页 |

本项目特化（非业界现成）：kb_recall 复用既有 Retriever 零新存储（MemGPT 建独立
archival memory）；pinning 键空间复用自有 fact_verification 体系（Claude Code 保的是
编码场景决策）；双协议（native/react）折叠单位适配；摘要纯规则化以保 benchmark mock
确定性（业界方案均无 CI 确定性约束）。
