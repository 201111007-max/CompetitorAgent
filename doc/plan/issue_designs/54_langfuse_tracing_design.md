# 设计文档 54 — Langfuse 式链路追踪：自研 trace 总线 + 可选 Langfuse exporter

> 触发：2026-08-20 复核可观测性：自研结构化日志 +
> 成本核算已有，但无 OpenTelemetry/Langfuse 式链路追踪。经代码核实属实：`observability/logger.py`
> 有会话级 JSON 结构化日志 + `_log_call` LLM 埋点（tokens/成本/耗时，脱敏），但事件是扁平的
> 按 session 日志——无 trace→span 树、工具调用无结构化埋点、无 trace 级聚合视图。
> 用户拍板（2026-08-20）「使用 langfuse 跟踪」+ 三决策：**Q1 自研轻量 trace 为底座 +
> Langfuse 作可选 exporter**（数据模型对齐 Langfuse 概念，三环境变量齐全才启用上报）；
> **Q2 span 三档全要**（llm.call generation / tool.call / 子 Agent 嵌套 span）；
> **Q3 查看方式 = CLI `trace show <sid>` 文本瀑布图 + JSONL 落盘**（不做 Web trace 页面）。
> 历史包袱：问题 19 修复时曾把 `ObservabilityConfig` 无消费方的 `tracing`/`metrics`/`langfuse_*`
> 字段作为「假亮点」删除——本次每个配置字段必须有真消费方（见 §7 风险 1）。
> 参考模式：dota_helper 子项目曾有 `langfuse_adapter.py`（Tracer 接口 + NoOp 降级 +
> `LANGFUSE_AVAILABLE` 惰性探测），该子项目不在本仓库磁盘上，仅借鉴模式不复用代码。
> 前置：36（LLM 可靠性/成本埋点）、43（ReactLoop 共享上下文/event_sink）、49（子 Agent 编排）、
> 06/41（脱敏与注入防护纪律）。

## 1. 问题现状

### 1.1 现有可观测性资产与缺口

| 层 | 现状 | 缺口 |
|---|---|---|
| 会话日志 | `get_session_logger`/`log_event`/`emit_session_event` → JSON 落盘 `logs/<sid>.log` | 扁平事件流，无 parent 层级，还原不了「谁触发谁」 |
| LLM 埋点 | `_log_call`（client.py:234）emit `llm.call`：model/tokens/elapsed_ms/cost_usd/attempts/retried | 数据现成但不是 span——无 trace 挂载点，无法按会话聚合 |
| 工具调用 | `ToolDispatcher.dispatch` 仅一行 `logger.info` | 无结构化 span（参数摘要/耗时/结果大小/错误状态） |
| 进度事件 | `ProgressEvent` + `event_sink` → SSE | 面向 UI 进度，非链路追踪 |
| 上报通道 | 无 | Langfuse 式平台不可达 |

### 1.2 三个具体问题

1. **无 span 树**：一次 analyze 里「哪次 LLM 调用属于哪个子 Agent、哪个工具结果触发了
   哪次重试」只能靠人工 grep 时间戳拼凑，排查与复盘成本高。
2. **trace 级聚合缺失**：单会话总成本/总耗时/调用次数没有现成视图（`_log_call` 数据散在
   日志行里），评测报告的成本数字与运行日志对不上口径。
3. **无平台化上报**：Langfuse 式 UI（trace 瀑布/generation 详情/成本看板）完全缺失，
   缺「LLMOps 链路追踪」实证，无法支撑跨会话的成本/耗时/调用聚合视图。

### 1.3 现有可复用资产

| 资产 | 位置 | 复用方式 |
|---|---|---|
| 会话上下文注入 | `_current_session_id()` 线程上下文 + `set_current_session` | trace_id 即 session_id，零新 ID 体系 |
| LLM 调用数据 | `_log_call`（tokens/cost/elapsed/attempts/retried，已脱敏） | generation span 字段直搬，埋点只加 hook |
| 工具单入口 | `ToolDispatcher.dispatch`（tool_dispatcher.py:66） | tool.call span 埋点只需一处，Lead/子 Agent 全经过 |
| transcript 记录 | `ReactAgent._step_record`（tool/args/result_brief/url） | tool span 字段口径对齐 |
| 落盘纪律 | `SessionRouterHandler`（logs/<sid>.log）+ `JsonStore` 原子写 | traces JSONL 同目录同纪律 |
| 降级模式参考 | dota_helper `langfuse_adapter`（ITracer/NoOpTracer/惰性探测） | exporter 未配置 → NoOp，底座不受影响 |

## 2. 目标设计

### 2.1 数据模型（对齐 Langfuse 概念）

```
Trace      {trace_id(=session_id), name="analyze", input_brief(task 截断),
            start/end, status, total_cost_usd, total_tokens, metadata}
Span       {span_id, trace_id, parent_span_id, name, kind: phase|tool|subagent,
            start/end, status: ok|error|cancelled, input_brief, output_brief, error}
Generation (Span 特化 kind=llm)：+ model, prompt_tokens, completion_tokens,
            cost_usd, attempts, retried, latency_ms   ← 字段与 _log_call 一一对应
```

- **落盘**：`<data_dir>/traces/<YYYY-MM-DD>.jsonl`，每行一条 span 完成记录
  （含 trace_id/parent_span_id），按 session 过滤重建树；原子追加写，同 JsonStore 纪律。
- **脱敏**：沿用 `_log_call` 纪律——不落 prompt 全文、不落密钥；input/output_brief
  截断 200 字符。

### 2.2 trace 总线（自研底座，零依赖）

- 新增 `observability/tracer.py`：`Tracer`（`start_trace`/`start_span`/`end_span`/
  `generation(...)` 快捷方法 + `Span` 上下文管理器）；线程局部 trace 栈
  （同线程嵌套自动挂 parent）；**跨线程显式传 parent_span_id**（子 Agent 场景）。
- sink 列表：`JsonlSink` 默认启用（纯本地）；`LangfuseExporter` 可选追加。
- **三档埋点**（Q2 全要）：
  ① `llm.call` generation span：`_log_call` 末尾挂 tracer hook（数据现成，
     LLMClient 构造接受可选 tracer，None 则跳过——默认路径由 facade 注入）；
  ② `tool.call` span：`ToolDispatcher.dispatch` 埋点（name/args 摘要/elapsed/
     结果大小/异常状态），dispatcher 构造接受可选 tracer；
  ③ 子 Agent span：`delegate` fan-out 时把当前 span_id 显式传给子线程，
     子 Agent 的 ReactLoop 运行包在 `kind=subagent` span 里（挂在 delegate span 下）。
- 取消/预算中断 → 未闭合 span 落 `status=cancelled|error`，树不留悬半节点。

### 2.3 Langfuse exporter（可选上报）

- 新增 `observability/langfuse_exporter.py`：惰性 import langfuse SDK；
  `LANGFUSE_HOST` + `LANGFUSE_PUBLIC_KEY` + `LANGFUSE_SECRET_KEY` **三者齐全且 SDK 已装**
  才启用，否则 NoOp（JSONL 底座不受影响，启动不炸）。
- 映射：Trace→trace、Span→span、Generation→generation（tokens/cost/model 直搬）；
  span 完成时异步上报（后台线程 + 有界队列，不阻塞分析主链路）；上报失败静默降级
  只记本地 + 一行 warning。
- 配置：`ObservabilityConfig` 加**派生属性** `langfuse_enabled`（读三环境变量计算，
  yaml 不落明文密钥）——字段有真消费方，不蹈问题 19「假亮点」覆辙。

### 2.4 CLI 查看器（Q3）

- `python -m competitor_agent.cli trace list`：最近 trace 列表（sid/任务摘要/状态/
  总成本/总耗时/span 数）。
- `python -m competitor_agent.cli trace show <sid>`：读 JSONL 重建 span 树，
  文本瀑布图——缩进树 + 相对耗时条 + 每行 model/tokens/cost 列，例如：

```
analyze "分析 Cursor"  [ok]  42.3s  $0.0123
├─ llm.call make_plan        deepseek-chat   1.2k tok  $0.0008   3.1s  ███
├─ delegate [pricing,feature]                                 28.4s  ████████████████
│  ├─ subagent pricing                                        22.1s  ████████████
│  │  ├─ llm.call            deepseek-chat   2.1k tok  $0.0015   4.2s  ██
│  │  └─ tool.call web_extract                                6.8s  ████
│  └─ subagent feature                                        19.5s  ███████████
└─ llm.call report           deepseek-chat   3.4k tok  $0.0024   5.6s  ███
```

### 2.5 明确不做

- **不接 OpenTelemetry SDK**：span 模型对齐 OTel/Langfuse 概念但零依赖自研；
  平台上报走 Langfuse exporter 一条路（用户拍板），不引入 OTel collector 体系。
- **不做 Web 端 trace 页面**（Q3 拍板 CLI 瀑布图）。
- **不落 prompt 全文/密钥**：脱敏纪律不破（doc 06/41 同级）。
- **不动 ProgressEvent/SSE 桥**：UI 进度语义不变，trace 与进度事件双轨不合并。
- **测试零触网**：tracer 底座纯本地；exporter 测试 mock SDK（与 `_isolate_llm_env`
  同级隔离纪律）。

## 3. 模块/接口设计

### 3.1 新增/修改点（均为增量）

- `observability/tracer.py`（新增 ~150 行）：`Tracer`/`Span`/线程局部栈/`JsonlSink`/
  `get_tracer()` 模块级单例（可注入替换）。
- `observability/langfuse_exporter.py`（新增 ~80 行）：`LangfuseExporter(sink 接口)`，
  惰性 import + NoOp 降级 + 异步有界队列。
- `llm/client.py`（~15 行）：构造加可选 `tracer`；`_log_call` 末尾发 generation span。
- `agent/tool_dispatcher.py`（~10 行）：构造加可选 `tracer`；`dispatch` 包 tool span。
- `facade/api.py`（~20 行）：`analyze` 包 trace 生命周期（start/end/status/聚合）；
  delegate 处显式传 parent_span_id 给子 Agent 线程；子 Agent ReactLoop 包 subagent span。
- `config/loader.py`（~10 行）：`ObservabilityConfig.langfuse_enabled` 派生属性
  （三环境变量齐全 + import 探测）。
- `cli.py`（~60 行）：`trace show`/`trace list` 子命令 + 瀑布渲染。
- `pyproject.toml`：optional extra `langfuse = ["langfuse>=2,<3"]`。

### 3.2 测试

- `tests/unit/observability/test_tracer.py`：span 树嵌套/parent 显式传递（跨线程模拟）/
  JSONL 落盘往返重建/取消与异常的 span status/脱敏（不落 prompt 全文、brief 截断）/
  聚合字段（total_cost/total_tokens）。
- `tests/unit/observability/test_langfuse_exporter.py`：SDK 缺失 NoOp/三变量不齐 NoOp/
  mock SDK 上报字段映射/上报失败静默降级本地不受影响。
- `tests/unit/cli/test_trace_cli.py`：瀑布渲染含三档 span/list 输出。
- 全量 `pytest -q` 不回归（tracer 默认纯本地零网络；未配 Langfuse 环境行为与现状一致）。

## 4. 接入方式

- 配置：`review_config.yaml` 不加明文密钥字段；Langfuse 启用全走环境变量 +
  `langfuse_enabled` 派生属性（真消费方 = exporter 初始化判断）。
- 依赖：自研底座零新依赖；`langfuse` SDK 为 optional extra，未装则 exporter NoOp。
- 兼容：现有日志/事件/成本核算口径不变（generation span 数据同源 `_log_call`）；
  未配置环境 = 只多一个 traces JSONL 落盘目录。
- 回退：删三处埋点 hook（client/dispatcher/api）即完全回退；traces 目录残留无害。
- 测试隔离：默认 sink 纯本地；exporter 测试 mock SDK，CI 零触网。

## 5. 验证方式

- `pytest tests/unit/observability/ tests/unit/cli/test_trace_cli.py -q` 全绿；全量不回归。
- 手动：CLI `analyze "分析 Cursor"`（mock 或真实）后 `trace show <sid>`，
  瀑布图含 llm/tool/subagent 三档且耗时/成本与日志口径一致。
- 手动（可选）：本地 docker 起 Langfuse server + 配三环境变量 + `pip install -e ".[langfuse]"`，
  跑一次 analyze 后在 Langfuse UI 看到同构 trace/span/generation。

## 6. 实现优先级与工作量

| # | 里程碑 | 产出 | 工作量 |
|---|--------|------|--------|
| 0 | 设计文档 + 索引登记 | 本文档 + README/implementation_plan 登记 | 0.2d ✅ 2026-08-20 |
| 1 | trace 底座 | tracer.py + JsonlSink + llm/tool 两档埋点 + 单测 | 1d |
| 2 | 子 Agent span + CLI | delegate parent 传递 + subagent span + trace show/list 瀑布图 | 0.5d |
| 3 | Langfuse exporter | exporter + extra + 环境变量启用判断 + 单测 + 手动实测记录 | 0.5d |

## 7. 风险与缓解

1. **问题 19「假亮点」覆辙**：配置字段只在真启用路径存在——`langfuse_enabled` 为派生
   属性（三环境变量齐全 + SDK 可 import 才为真），yaml 无死字段；单测覆盖各组合。
2. **跨线程 parent 传递遗漏导致 span 树断裂**：delegate 是唯一 fan-out 点，显式传参
   单点控制；单测断言子 Agent span 的 parent 链完整、trace show 树无孤儿节点。
3. **埋点 overhead**：JSONL 追加写 + 内存栈，单 span 微秒级；会话 span 数百级量级，
   无性能风险（若未来高开销可采样，本期不做）。
4. **Langfuse SDK 版本漂移**：锁 `langfuse>=2,<3`；惰性 import + 失败 NoOp，
   升级先跑 exporter 单测。
5. **脱敏边界**：span 不落 prompt 全文与密钥，input/output_brief 截断 200 字符；
   单测断言 traces JSONL 不含 mock prompt 全文特征串。
