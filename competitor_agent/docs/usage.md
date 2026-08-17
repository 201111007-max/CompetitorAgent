# 使用手册（usage.md）

> 竞品分析 Agent 的安装、启动与使用方式。
> 目标读者：使用系统的分析师 / 开发。

---

## 1. 安装

```bash
cd competitor_agent
pip install -e ".[all]"

# 可选：SPA 采集（M2+）
playwright install chromium

# 配置凭据（SecretVault 加密落盘，勿写环境变量明文）
python -m competitor_agent.cli config set-key LLM_API_KEY
python -m competitor_agent.cli config set-key GITHUB_TOKEN
```

---

## 2. 启动方式

### 2.1 CLI

```bash
# 单竞品分析
python -m competitor_agent.cli analyze "Claude Code"

# 竞品对比
python -m competitor_agent.cli analyze "对比 Cursor 和 Windsurf"

# 输出到指定目录
python -m competitor_agent.cli analyze "Cursor" --out reports/

# 查看历史
python -m competitor_agent.cli history --competitor cursor

# 单发（脚本化，一次性执行后退出）
python -m competitor_agent.cli -z "分析 Cursor"

# 恢复会话（-c 对齐 hermes --continue）
python -m competitor_agent.cli -c sess_abc123

# 运行评测基准
python -m competitor_agent.cli benchmark

# 定时调度轮：只重爬过期竞品 + 结构化 JSON 导出 + 异动告警（设计文档 28）
python -m competitor_agent.cli schedule --competitors cursor,copilot

# 交互模式（无子命令时进入 REPL，支持斜杠命令）
python -m competitor_agent.cli
```

交互模式斜杠命令：

| 命令 | 别名 | 说明 |
|------|------|------|
| `/analyze <任务>` | `/a` | 单竞品/对比分析 |
| `/compare A 和 B` | `/c` | 两个竞品对比 |
| `/history [--competitor X]` | `/h` | 查询历史 |
| `/resume [session_id]` | `/r` | 恢复会话（缺省取最近 checkpoint） |
| `/schedule [--competitors a,b]` |  | 定时调度轮（重爬过期 + 导出 + 告警） |
| `/benchmark` | `/b` | 运行评测基准 |
| `/help [命令]` | `/?` | 帮助 |

命令识别采用"前缀判定 + 注册表查表"（不写命令名 regex），`/Users/foo` 类路径不会被误判为命令。

### 2.2 Web（SSE 可视化）

```bash
pip install -e ".[web]"
python -m competitor_agent.web_app --port 8000
# 打开 http://localhost:8000
```

Web 界面提供：
- 输入竞品名称，点击"开始分析"触发 SSE 流式分析
- 实时显示分析进度（规划→采集→分析→报告）
- 取消运行中的分析
- 查询历史分析记录

API 端点：
| 端点 | 说明 |
|------|------|
| `GET /` | 简易前端页面 |
| `GET /api/analyze?task=分析%20Cursor` | SSE 流式分析 |
| `POST /api/cancel/{session_id}` | 取消分析 |
| `GET /api/history` | 全部历史 |
| `GET /api/history/{competitor}` | 指定竞品历史 |
| `GET /api/status/{session_id}` | 会话状态 |

### 2.3 MCP Server

```bash
pip install -e ".[mcp]"

# stdio 模式（默认）
python -m competitor_agent.mcp_server.server

# SSE 模式
python -m competitor_agent.mcp_server.server --transport sse --port 8001
```

MCP 工具清单：
| 工具 | 说明 |
|------|------|
| `web_extract` | 采集网页内容 |
| `web_search` | 搜索竞品信息 |
| `analyze_pricing` | 定价分析 |
| `github_stars` | GitHub Star 数 |
| `github_releases` | 版本发布 |
| `github_commits` | 近期提交 |
| `run_benchmark` | 运行评测 |
| `analyze_competitor` | 综合分析 |

### 2.4 编程调用

```python
from competitor_agent import CompetitorAnalysisAPI
from competitor_agent.interfaces.context import ChatMessage

# 基础分析（设计文档 46/47：默认 use_llm=True，主路径仅 LLM；需配置 API Key）
api = CompetitorAnalysisAPI(llm=LLMClient(...), use_llm=True)
report = api.analyze("Claude Code")
print(report.markdown_report)

# 流式分析
async for event in api.analyze_stream("Cursor"):
    print(f"[{event.event}] {event.message}")

# 多 Agent 流水线
report = api.analyze_team("Cursor")

# 对比分析
from competitor_agent import CompetitorAnalysisAPI

api = CompetitorAnalysisAPI(llm=LLMClient(...), use_llm=True)

# 对比（可传两个竞品，或一个"对比 A 和 B"任务）
result = api.compare("Cursor", "Windsurf")
print(result.markdown_report)

# 多轮追问（conversation_history 支持，第二轮相对指代可从历史承接竞品）
report1 = api.analyze("Cursor")
report2 = api.analyze("那定价呢", conversation_history=[
    ChatMessage(role="user", content="Cursor"),
    ChatMessage(role="assistant", content=report1.markdown_report),
])

# 历史查询
history = api.get_history("cursor")

# 断点续跑
api.cancel("sess_abc123")
report = api.resume("sess_abc123")
```

> **无 Key 语义（设计文档 47）**：主路径（任务解析 / 规划 / 竞品识别 / 维度分析）只走 LLM。
> 未配置 API Key 时调用会抛 `LLMUnavailableError`（CLI 打印"需要配置 LLM API Key"退出码 2，
> Web 返回 SSE `error` 事件），**不再静默降级规则**。

---

## 3. 常用操作

| 操作 | 命令/接口 |
|------|----------|
| 分析 | `analyze(task)` / CLI `analyze` |
| 对比 | `compare(a, b)` / CLI `analyze "对比 A 和 B"` / `/compare` |
| 多轮追问 | `analyze(task, conversation_history=[...])` |
| 流式分析 | `analyze_stream(task)` |
| 取消 | `cancel(session_id)` |
| 恢复 | `resume(session_id)` / `continue_analysis(session_id)` / CLI `-c` |
| 历史 | `get_history(competitor)` / CLI `history` / `/history` |
| 评测 | `pytest tests/evaluation` / CLI `benchmark` |
| 定时调度轮 | `run_scheduled(competitors=None, alert_sink=None)` / CLI `schedule` |
| MCP | `mcp_server.server --transport sse` |

---

## 4. 输出说明

- Markdown 报告含：维度结论、置信度、证据 URL、未关闭缺口及原因。
- 低置信度项明确标注 `[low-confidence]`，不隐藏。
- 全部结论带采集时间戳，过期风险可见。
- **定价维度（设计文档 27）**：渲染「定价档位 / 按量计费 / 成本场景估算」三张表——档位含月付/年付/限额与 `需询价` 标注（企业档不猜数字），成本场景按 light(30)/medium(100)/heavy(1000) 次/天×30 天估算月成本（无按量单价且超限 → 需询价/无法估算，不编造）。`PricingProfile` 随报告归档为 `pricing_profiles`，时间线 `price_change` 事件摘要直接给出价格变化（如 `$20/mo → $40/mo`）。
- **结构化导出（设计文档 28）**：分析完成后自动导出 `reports/competitor/<竞品>.json`（`config.report.export_json` 开启时，与 .md 同目录同名），`compare` 另出 `reports/comparison/<names>.json`（维度×竞品矩阵 + 每维度最佳 + 汇总排名）；报告末尾追加「已导出 JSON 路径」提示。定时轮 `schedule`/`run_scheduled` 只重爬过期（超过维度 TTL）竞品，把与上次快照的 diff 映射为异动告警（`price_change`/`feature_added`/`version_release`/`score_change`），`ConsoleAlertSink` 打印、`FileAlertSink` 追加 `reports/alerts/<date>.md`。

---

## 5. 常见问题

| 问题 | 处理 |
|------|------|
| 无 LLM Key | 主路径仅 LLM（设计文档 47）：CLI 报"需要配置 LLM API Key"退出码 2，Web 返回 SSE `error` 事件，库调用抛 `LLMUnavailableError`——请先 `cli config set-key LLM_API_KEY` |
| 官网解析不到内容 | SPA → 检查是否安装 Playwright；或换降级源 |
| 成本超预算 | 分析被 BudgetController 终止，报告标注 reason=cost_limit_reached |
| 缺口未关闭 | 报告 `gaps_pending` 列明原因，可 `resume` 继续 |
| 分析中断 | 每缺口完成后自动保存 checkpoint，调用 `resume(session_id)` 恢复 |
