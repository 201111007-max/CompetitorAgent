# 设计文档 21 — 日志完善功能（可观测性补齐）

> 对应 `implementation_plan.md` §14（P0，用户已确认，待办）

## 1. 问题现状

- `observability/logger.py` 现仅 29 行：`get_logger()` 首次调用时给根 logger 配一个 `StreamHandler(sys.stdout)` + `%(asctime)s %(levelname)s [%(name)s] %(message)s` 普通文本格式，`root.setLevel(logging.INFO)`。
- 现状缺陷（本次"0 维度"排查直接暴露）：
  1. **detached 服务器 stdout 被缓冲**，分析过程日志不落地，定位极难。
  2. **无结构化字段**：无 `request_id` / `session_id` / 阶段标签，日志只能靠 grep 文本。
  3. **无会话级日志文件**：所有会话日志混在同一个 stdout，事后无法按 session 复盘。
  4. **无 LLM 调用日志**：模型 / token / 耗时 / 成本均无记录（`BudgetController` 虽有预算，未输出链路）。
  5. **关键节点无埋点**：竞品识别 / 选源 / 采集状态 / 分析置信度 / 终止原因 / 报告维度计数没有统一事件日志。
  6. **无 Web 端点**：浏览器无法查看当前 / 历史分析的日志流。

## 2. 目标设计

补齐端到端可观测性，使任意一次分析的全过程可回溯、"0 维度"类问题一眼可定位：

1. **结构化日志**：统一 JSON（或带 `request_id` 的行日志）格式，覆盖一次分析的完整链路。
2. **每分析独立日志文件**：按 `session_id` 落盘到 `~/.competitor_agent/logs/<session_id>.log`。
3. **关键节点埋点**：任务解析结果、竞品识别、每个缺口的选源 / 采集（url + HTTP 状态 + 字节数）/ 分析（模型 + token + 耗时 + 置信度）、终止原因、报告维度计数。
4. **LLM 调用日志（脱敏）**：模型、`base_url`、输入/output token、耗时、成本；**不落 prompt 全文、不落密钥**。
5. **实时刷新 / 不缓冲**：detached / 重定向场景日志即时 flush。
6. **Web 端点暴露**：`/api/logs/{session_id}` 或前端查看当前 / 历史分析日志流。

## 3. 模块/接口设计

### 3.1 增强 `observability/logger.py`

```python
def setup_logging(
    *,
    level: str = "INFO",
    log_dir: Path | None = None,           # ~/.competitor_agent/logs 默认
    json_format: bool = True,              # False 时回退文本格式
    auto_flush: bool = True,
) -> None: ...

def get_session_logger(session_id: str) -> logging.Logger:
    """按 session 返回 logger：同时输出到根 handler + logs/<session_id>.log。"""

class SessionFileHandler(logging.Handler):
    """会话级文件 handler：路径 logs/<session_id>.log，每次 emit 后 flush()（不缓冲）。"""
```

- JSON 格式器：`{"ts","level","logger","session_id","phase","event",...,"message"}`，`extra` 字段并入。
- `config/loader.py` 的 `ObservabilityConfig.log_level` 真正注入（呼应计划 §14 依赖 / §11.2 #5）。

### 3.2 埋点接入点（关键路径）

| 阶段 | 模块 | 埋点事件 | 关键字段 |
|------|------|----------|----------|
| 解析 | `task_parser` | `task.parsed` | competitors, dimensions, is_discovery |
| 识别 | `strategic_loop` | `competitor.resolved` | name, official_links, source（registry/discovery） |
| 规划 | `strategic_loop` | `gaps.planned` | gap_fields, 初始置信度, 预算分配 |
| 选源 | `source_selector` / `gap_executor` | `source.selected` | gap_field, source_name, url, degraded |
| 采集 | `gap_executor` / `fetch_candidate` | `collect.done` / `collect.fail` | url, http_status, bytes, 耗时, fallback 链 |
| 分析 | `analyzers` / `llm/client.py` | `analyze.done` | dimension, model, tokens, 耗时, 置信度, cost |
| 终止 | `budget_controller` / `api` | `analysis.terminated` | terminal_state, 终止原因（gap_all_closed/iterations/cost/core_satisfied） |
| 汇总 | `report_builder` | `report.built` | dimension_count, overall_confidence |

### 3.3 LLM 调用日志（`llm/client.py`）

- 在 `LLMClient.chat()` 完成回调中记录：`model` / `base_url` / `prompt_tokens` / `completion_tokens` / `total_tokens` / `elapsed_ms` / `cost_usd`（对接 `BudgetController` 计费）。
- 脱敏规则：prompt / completion **只记长度不记全文**；`api_key`、`Authorization` 头一律不记。
- `cost_usd` 来源：从 `BudgetController.record_iteration` 复用的计价逻辑。

### 3.4 Web 日志端点（`web_app.py`）

```python
@app.get("/api/logs/{session_id}")
async def logs(session_id: str, _: None = Depends(require_auth)) -> JSONResponse:
    """返回该次分析的日志（从 logs/<session_id>.log 读，尾随式增量由前端轮询/SSE）。"""

@app.get("/api/logs/stream/{session_id}")
async def logs_stream(...) -> StreamingResponse:
    """SSE 推送日志尾部追加（配合前端实时查看）。"""
```

- 前端 `index()` 增加"日志"面板：分析中实时滚动显示 `logs/stream/{session_id}`，分析后可从 `/api/history` 选择历史会话查看对应日志。
- 历史日志与 `archive_session` 生命周期对齐：`logs/<session_id>.log` 与分析会话同步保留 / 清理。

## 4. 接入方式

```
setup_logging(level=config.observability.log_level, log_dir=get_data_dir()/"logs")
    ↑ 在 web_app.main() / cli.main() / mcp 入口调用一次

CompetitorAnalysisAPI.analyze(task, session_id=...)
    ├─ 会话开始：get_session_logger(sid) → 写 session_started
    ├─ 各阶段埋点：task_parser / strategic_loop / source_selector / gap_executor / analyzers 打结构化日志
    ├─ LLM 调用：llm/client.py 完成回调写脱敏调用日志
    └─ 结束：analysis.terminated + report.built；SessionFileHandler 自动 flush
```

- `session_id` 贯穿：`get_session_logger(sid)` 内部用 `logging.LoggerAdapter` 注入 `extra={"session_id": sid}`，JSON 格式器自动落字段。
- detached / 重定向场景：`SessionFileHandler` 直接写文件（不受 stdout 缓冲影响），`StreamHandler` 可选加 `flush` 到控制台。

## 5. 验证方式

- **单测**：`setup_logging` 后 JSON 格式器产出含 `session_id` / `phase` 字段的行；`get_session_logger(sid)` 写出 `logs/<sid>.log`；`auto_flush` 下重定向 stdout 后日志仍实时落盘（模拟 detached）。
- **埋点单测**：构造一次 `analyze`（`FakeExtractor` + `mock_llm`），断言日志含 `competitor.resolved` / `source.selected` / `collect.done` / `analyze.done`（含 model/tokens/cost）/ `analysis.terminated`（含原因）。
- **脱敏单测**：`LLMClient` 调用日志不含 prompt 全文、不含 `api_key`；无 Key 时不触发真实网络（复用问题 15 的 autouse 清 key fixture）。
- **Web 集成**：`/api/logs/{session_id}` 返回历史分析日志；`/api/logs/stream/{sid}` 在分析中返回增量行；受 `require_auth` 保护（401 用例）。
- **回归**：现有日志输出格式变化不影响测试（断言不依赖旧文本格式）；全量测试通过。

## 6. 实现优先级与工作量

- 优先级：**高**（P0，本次排障已证明无日志无法定位 0 维度类问题）。
- 工作量：约 2-3 天。
  - logger 增强 + JSON 格式器 + 会话文件 handler + flush：0.5-1 天；
  - 埋点接入 7 类关键路径：0.5-1 天；
  - LLM 脱敏调用日志：0.5 天；
  - Web `/api/logs` + `/api/logs/stream` + 前端日志面板：0.5 天；
  - 测试（单测 + 埋点断言 + Web 集成）：0.5 天。
- 前置依赖：`ObservabilityConfig.log_level` 注入依赖问题 5 已修复（`config/loader.py` 已就位）；与 §15（Web 端报告展示）共用"分析完成"钩子，可一并接。
