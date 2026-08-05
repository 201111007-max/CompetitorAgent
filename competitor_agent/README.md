# competitor_agent — AI coding agent 竞品分析 Agent

自动采集并分析 AI coding agent 竞品（Claude Code、Cursor、Windsurf、Copilot 等），
输出含功能 / 定价 / 性能 / 生态 / 口碑 / 路线图的 Markdown 报告。

复用 `dota_helper` 的框架思想（双循环编排、信息缺口驱动、证据链防幻觉、四层记忆），
但独立目录、独立包、**零 import 耦合**。

## 快速开始

```bash
cd competitor_agent
pip install -e ".[dev]"

# 运行测试
pytest
```

## 启动方式

### CLI
```bash
python -m competitor_agent.cli analyze "Cursor"
python -m competitor_agent.cli history --competitor cursor
```

### Web（SSE 可视化）
```bash
pip install -e ".[web]"
python -m competitor_agent.web_app --port 8000
# 打开 http://localhost:8000
```

### MCP Server
```bash
pip install -e ".[mcp]"
python -m competitor_agent.mcp_server.server --transport stdio
# 或 SSE 模式
python -m competitor_agent.mcp_server.server --transport sse --port 8001
```

### 编程调用
```python
from competitor_agent import CompetitorAnalysisAPI

api = CompetitorAnalysisAPI(use_llm=False)
report = api.analyze("Cursor")
print(report.markdown_report)

# 流式分析（Web SSE）
async for event in api.analyze_stream("Cursor"):
    print(event.message)

# 历史查询
history = api.get_history("cursor")

# 断点续跑
api.cancel("sess_abc123")
report = api.resume("sess_abc123")
```

## 目录结构

```
competitor_agent/
├── config/review_config.yaml   # 预算/维度/终止阈值配置
├── domain_types/               # 领域数据模型（InfoGap/Observation/CompetitorStrategy...）
├── interfaces/                 # Protocol 契约层
├── core/                       # 框架内核（双循环/预算/停止验证/报告/checkpoint）
├── agent/                      # ReAct 交互层 + 护栏 + prompts
├── collector/                  # 数据源（web/github/pricing/benchmark/review）
├── analyzers/                  # 维度分析器（LLM 驱动，规则降级）
├── knowledge_base/             # 竞品知识库（RAG）
├── memory/                     # 四层记忆
├── team/                       # 多 Agent 协作
├── evaluation/                 # 评测体系
├── mcp_server/                 # MCP Server（对外暴露采集/分析工具）
├── web_app.py                  # FastAPI + SSE 可视化
├── facade/api.py               # 外部唯一入口 CompetitorAnalysisAPI
├── secret_vault.py             # 凭据池（数据目录 ~/.competitor_agent/）
└── tests/                      # unit / integration / evaluation
```

## 设计文档

- 架构总纲：`../doc/ai_coding_agent_competitor_analysis_architecture.md`
- 分步实现计划：`../doc/plan/implementation_plan.md`
- 各模块契约/规范：`docs/`（interfaces/domain_models/prompts/data_sources/configuration/evaluation_guide/testing/usage/api）

## 里程碑状态

- [x] M0 环境与项目骨架
- [x] M1 骨架闭环（采集→分析→报告）
- [x] M2 记忆与自进化
- [x] M3 多 Agent 协作 + 评测体系
- [x] M4 工程化（Web/MCP/CI/断点）
