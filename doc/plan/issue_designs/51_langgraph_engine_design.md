# 设计文档 51 — 可切换 LangGraph 引擎（mini 复刻）+ benchmark 对照实验

> 触发：2026-08-20 岗位差距分析（BOSS/猎聘等 Agent 应用开发岗 JD 提炼）发现项目主流框架关键词缺失；
> 用户拍板采用「可切换真实引擎 + benchmark 对照」方案：mini 版不是 examples 玩具，
> 而是接入 `CompetitorAnalysisAPI` 的第二编排引擎，真实可跑、可用同一评测 harness 做双引擎对照。
> 已确认范围：主链路（plan → delegate 并发子 Agent → report）+ SSE 事件 + 记忆/RAG 召回；
> **不含**取消/预算/checkpoint 恢复（自研引擎的差异化能力，作为对比结论呈现）。
> 前置：47/49（Lead ReAct 编排、REPORT_SCHEMA、transcript）、30（消融开关）、36（benchmark harness）。

## 1. 问题现状

- 编排层全自研（`agent/react_loop.py` + `agent/delegate_tool.py` + `SubagentRegistry`），
  零 LangChain/LangGraph 依赖——架构能力实际达标，但简历/面试缺框架关键词，
  且「为什么自研」目前只有定性论证，无实证数据。
- 需要一个**同任务、同 LLM、同工具、同出口**的第二引擎，把编排层变成唯一变量，
  用 benchmark 数据回答「自研 vs 框架」。

### 1.1 现有可复用资产（接入成本低的依据）

| 资产 | 位置 | 复用方式 |
|---|---|---|
| LLM 调用（重试/fallback/成本核算/埋点） | `llm/client.py::LLMClient` | 节点内直接调，成本/日志口径不变 |
| 工具面（8 工具 + 白名单 + 反递归） | `agent/tool_registry.py::build_react_dispatcher` | 子 Agent 节点共用同一 dispatcher |
| 报告出口（REPORT_SCHEMA 解析/组装） | `facade/react_report.py::assemble` | 两引擎同一出口，产物格式一致 |
| 记忆/RAG 召回 | `facade/api.py::_memory_ctx_for` / `_react_rag_context` | plan 节点前注入同样文本 |
| 事件桥 | `event_sink` 回调（ProgressEvent） | LangGraph 节点内 emit，SSE 前端零改动 |
| 评测 harness（确定性 mock + 门禁） | `evaluation/benchmark.py::BenchmarkMockLLM`（ReAct-scripted） | LLMClient 接口不变 → mock 脚本原样复用 |

### 1.2 明确不做（范围边界）

- 取消 / 预算 / checkpoint 恢复不对齐：LangGraph 自带 interrupt/checkpointer，
  硬对齐等于用框架重写自研横切能力，失去对比意义；文档与对比报告中作为
  「框架省了编排代码，横切控制要自己补」的实证结论。
- 不引入 langchain 全家桶：只依赖 `langgraph` + `langchain-core`（StateGraph 类型需要），
  节点内仍直接调 `LLMClient.complete`，不用 `create_react_agent`/LangChain 模型封装——
  保证 mock、成本核算、埋点三个口径与自研引擎逐位一致（对照实验的控变量要求）。

## 2. 目标设计

### 2.1 引擎拓扑（StateGraph）

```
state = {task, competitor, memory_ctx, rag_ctx, plan, subagent_results: list, final_answer, transcript}

plan_node        → LLM 调 make_plan 同 schema（PLAN_SCHEMA），产出 plan dict
                   （memory_ctx/rag_ctx 注入系统提示，与自研路径同文本）
delegate_node    → 按 plan.dimensions 用 Send API fan-out，每维度一条边
subagent_node    → 单维度 mini ReAct 子图：thought/action 循环调共用 dispatcher
                   （工具白名单同 _SUBAGENT_TOOLS；事件 emit phase_start/complete）
aggregate_node   → 收拢 subagent_results（错乱序按 dimension 归位）
report_node      → LLM 产出 REPORT_SCHEMA JSON → final_answer
```

- 并发：`Send` fan-out（LangGraph 原生 map-reduce），对齐自研 `DelegateRunner` 的批量并发语义。
- transcript：每个节点追加 `{tool/node, args, result_brief, url}` 同构记录，
  使 `_record_memory_success` / `_first_url_for` 不加分支直接可用。

### 2.2 引擎切换

```python
CompetitorAnalysisAPI(..., engine: str = "react")   # "react" | "langgraph"
```

- `analyze()` 内部路由：`react` → 现有 `_run_react_loop`（不动）；
  `langgraph` → `_run_langgraph_engine(task, sid)`，返回与 `(loop, result)` 同形的
  `(plan, answer, transcript)` 三元组，之后 assemble/记忆写侧/归档/导出/时间线全部复用。
- langgraph 未安装时：`engine="langgraph"` 在构造期抛 `ImportError`
  （提示 `pip install -e ".[langgraph]"`），默认路径零依赖零影响。

### 2.3 双引擎对照（benchmark）

- `benchmark` 子命令加 `--engine {react,langgraph,both}`（默认 react，门禁行为不变）；
  `--engine both` 时同一批 fixture 顺序跑两套，产出对比表落盘
  `<data_dir>/reports/engine_compare_<date>.md`：

| 指标 | react | langgraph |
|---|---|---|
| field_accuracy / hallucination_rate（现有门禁指标） | … | … |
| LLM 调用次数 / total_cost_usd / wall time | … | … |
| 编排代码行数 / 三方依赖体积 | …（静态统计，文档记录一次） | … |

- mock 下只比「编排开销/步数/成本」；产出质量对比需 `--llm real` 手动跑一遍
  （真实 LLM 不进 CI，成本护栏沿用 `--cost-limit`）。

## 3. 模块/接口设计

### 3.1 新增 `competitor_agent/agent/langgraph_engine/`

```
langgraph_engine/
├── __init__.py        # 惰性导出；ImportGuard
├── state.py           # EngineState TypedDict（含 transcript: list[dict]）
├── graph.py           # build_graph(dispatcher, llm, event_sink, memory_ctx, rag_ctx) -> CompiledGraph
├── nodes.py           # plan_node / delegate_node / subagent_node / aggregate_node / report_node
└── engine.py          # run_langgraph(task, *, llm, dispatcher, event_sink, session_id,
                       #              memory_ctx_fn, rag_fn) -> (plan, answer, transcript)
```

- 全部 langgraph 导入局限在本包内，惰性 import；包外只接触 `run_langgraph` 签名。
- 子 Agent 循环复用 `ReactAgent.run`（同一 parser/dispatcher），仅编排由 StateGraph 接管——
  保证「唯一变量是编排层」。

### 3.2 修改点（均为增量，不改现有行为）

- `facade/api.py`：`__init__` 加 `engine` 参数 + `_run_langgraph_engine` 路由（~40 行）。
- `cli.py`：`analyze` / `benchmark` 子命令各加 `--engine`。
- `pyproject.toml`：`[project.optional-dependencies]` 加
  `langgraph = ["langgraph>=0.2", "langchain-core>=0.3"]`。
- `evaluation/benchmark.py`：`--engine both` 双跑 + 对比表落盘（不动 HARNESS_VERSION，
  门禁仍只对默认 react 引擎生效）。

### 3.3 测试

- `tests/unit/agent/test_langgraph_engine.py`：图拓扑编译、plan→delegate→report 走通
  （mock LLM 复用 conftest 的 react_mock_llm）、transcript 同构断言、事件序列断言。
- `tests/unit/facade/test_engine_switch.py`：engine 路由、未装 langgraph 的 ImportError 信息
  （`importlib` 屏蔽模拟）、默认 react 行为不回归。
- benchmark 双引擎 smoke：mock 模式 `--engine both` 产出对比表文件。

## 4. 接入方式

- 配置：`review_config.yaml` 无新字段；引擎选择只走构造参数/CLI 参数（不做全局配置，
  避免 Web 端会话间串引擎）。
- 兼容：默认 `engine="react"`，全部现有测试/门禁/Web/CLI 行为不变；langgraph 为 optional extra。
- 回退：整个特性隔离在新包 + 路由分支，删除 `langgraph_engine/` 与路由即完全回退。

## 5. 验证方式

- `pytest tests/unit/agent/test_langgraph_engine.py tests/unit/facade/test_engine_switch.py -q` 全绿；
  全量 `pytest -q`（competitor_agent/）不回归。
- `pip install -e ".[langgraph]"` 后 CLI 实测：
  `python -m competitor_agent.cli analyze --engine langgraph "分析 Cursor"`（真实 LLM，手动）。
- `python -m competitor_agent.evaluation.benchmark --engine both`（mock）产出对比表；
  `--llm real --engine both --cost-limit 1.0` 手动跑一遍取质量对比数据。
- 未装 langgraph 环境：`--engine langgraph` 报可读 ImportError；默认路径不受影响。

## 6. 实现优先级与工作量

| # | 里程碑 | 产出 | 工作量 |
|---|--------|------|--------|
| 0 | 设计文档 + 索引登记 | 本文档 + README/implementation_plan 登记 | 0.2d ✅ 2026-08-20 |
| 1 | 引擎核心 | langgraph_engine 五文件 + 单测 | 1d |
| 2 | 接线 | api/cli 路由 + 事件/记忆注入 + extra | 0.5d |
| 3 | 对照实验 | benchmark --engine both + 对比表 + 实测报告 | 0.5d |

## 7. 风险与缓解

1. **langgraph API 漂移**：Send/StateGraph 接口版本间有变动——锁 `langgraph>=0.2,<1.0`，
   编译期单测覆盖图拓扑，升级时先跑该文件。
2. **对照公平性被质疑**（子 Agent 复用 ReactAgent 是否"LangGraph 含量不足"）：
   文档明示对比目标是**编排层**（状态机/并发委派/聚合），LLM/工具/出口控变量是实验设计有意为之；
   叙事重点放在结论数据而非框架使用面积。
3. **mock 脚本兼容性**：BenchmarkMockLLM 按消息内容特征脚本化，若 LangGraph 路径消息序列不同
   可能失配——M1 先用 conftest mock 调通消息形状，失配时按 phase 标签分流而非改全局脚本。
4. **依赖体积**：langgraph+langchain-core 约 15MB——optional extra 隔离，CI 默认不装，
   单独 extras 测试任务覆盖。
