# 使用手册（usage.md）

> 竞品分析 Agent 的安装、启动与使用方式。M4 定稿，当前为契约草案。
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
python -m competitor_agent.web_app --port 8000
# 打开 http://localhost:8000
```

### 2.3 编程调用

```python
from competitor_agent import CompetitorAnalysisAPI

api = CompetitorAnalysisAPI.from_defaults()
report = api.analyze("Claude Code")
print(report.markdown_report)
```

### 2.4 MCP Client

```python
from competitor_agent.mcp_client import MCPClient

client = MCPClient(url="http://localhost:8000/mcp")
for tool in await client.list_tools():
    print(tool.name)
```

---

## 3. 常用操作

| 操作 | 命令/接口 |
|------|----------|
| 分析 | `analyze(competitor, dimensions=None)` |
| 取消 | `cancel(session_id)` |
| 恢复 | `resume(session_id)` |
| 历史 | `get_history(competitor)` |
| 凭据 | `config set-key / list / rotate` |
| 评测 | `pytest tests/evaluation` |

---

## 4. 输出说明

- Markdown 报告含：维度结论、置信度、证据 URL、未关闭缺口及原因。
- 低置信度项明确标注 `[low-confidence]`，不隐藏。
- 全部结论带采集时间戳，过期风险可见（R11 缓解）。

---

## 5. 常见问题

| 问题 | 处理 |
|------|------|
| 无 LLM Key | 自动走 fallback_analyzer，输出仍可用但质量降级 |
| 官网解析不到内容 | SPA → 检查是否安装 Playwright；或换降级源 |
| 成本超预算 | 分析被 BudgetController 终止，报告标注 reason=cost_limit_reached |
| 缺口未关闭 | 报告 `gaps_pending` 列明原因，可 `resume` 继续 |
