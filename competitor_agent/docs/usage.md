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
```

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

# 基础分析
api = CompetitorAnalysisAPI(use_llm=False)
report = api.analyze("Claude Code")
print(report.markdown_report)

# 流式分析
async for event in api.analyze_stream("Cursor"):
    print(f"[{event.event}] {event.message}")

# 多 Agent 流水线
report = api.analyze_team("Cursor")

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
| 分析 | `analyze(competitor)` |
| 流式分析 | `analyze_stream(task)` |
| 取消 | `cancel(session_id)` |
| 恢复 | `resume(session_id)` |
| 历史 | `get_history(competitor)` |
| 凭据 | `config set-key / list / rotate` |
| 评测 | `pytest tests/evaluation` |
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
