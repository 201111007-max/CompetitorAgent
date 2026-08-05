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

# 基础分析
api = CompetitorAnalysisAPI(use_llm=False)
report = api.analyze("Claude Code")
print(report.markdown_report)

# 流式分析
async for event in api.analyze_stream("Cursor"):
    print(f"[{event.event}] {event.message}")

# 多 Agent 流水线
report = api.analyze_team("Cursor")

# 对比分析
from competitor_agent import CompetitorAnalysisAPI

api = CompetitorAnalysisAPI(use_llm=False)

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
| MCP | `mcp_server.server --transport sse` |

---

## 4. 输出说明

- Markdown 报告含：维度结论、置信度、证据 URL、未关闭缺口及原因。
- 低置信度项明确标注 `[low-confidence]`，不隐藏。
- 全部结论带采集时间戳，过期风险可见。

---

## 5. 常见问题

| 问题 | 处理 |
|------|------|
| 无 LLM Key | 自动走 fallback_analyzer，输出仍可用但质量降级 |
| 官网解析不到内容 | SPA → 检查是否安装 Playwright；或换降级源 |
| 成本超预算 | 分析被 BudgetController 终止，报告标注 reason=cost_limit_reached |
| 缺口未关闭 | 报告 `gaps_pending` 列明原因，可 `resume` 继续 |
| 分析中断 | 每缺口完成后自动保存 checkpoint，调用 `resume(session_id)` 恢复 |
