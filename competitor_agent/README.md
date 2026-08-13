# competitor_agent — AI coding agent 竞品分析 Agent

自动采集并分析 AI coding agent 竞品（Claude Code、Cursor、Windsurf、Copilot 等），
输出含功能 / 定价 / 性能 / 生态 / 口碑 / 路线图的 Markdown 报告，
并附**数据新鲜度注记**（维度 TTL / 过期提示）、跨分析**竞品时间线**（价格/版本/功能变化事件），
以及**结构化定价画像**（档位 / 按量计费 / 典型用量成本估算 / 企业询价标注）。

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
python -m competitor_agent.cli refresh                 # 过期竞品按 TTL 重爬（--all 全量）
python -m competitor_agent.cli timeline cursor         # 查看竞品时间线事件（价格/版本/功能变化）
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

# 新鲜度与时间线（设计文档 26）
stale = api.refresh_stale()          # 按维度 TTL 重爬过期竞品（可 ttl_override / recompute_all）
events = api.timeline.events("cursor")  # 跨分析 diff 产生的 price_change/version_release 等事件
```

## 目录结构

```
competitor_agent/
├── config/review_config.yaml   # 预算/维度/终止阈值/新鲜度 TTL 配置
├── domain_types/               # 领域数据模型（InfoGap/Observation/CompetitorStrategy/ReportFreshness...）
├── interfaces/                 # Protocol 契约层
├── core/                       # 框架内核（双循环/预算/停止验证/报告/checkpoint）
├── agent/                      # ReAct 交互层 + 护栏 + prompts
├── collector/                  # 数据源（web/github/pricing/benchmark/review）
├── analyzers/                  # 维度分析器（LLM 驱动，规则降级）
├── knowledge_base/             # 竞品知识库（RAG）
├── memory/                     # 四层记忆 + 竞品时间线（timeline_memory）
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
- 逐期设计文档：`../doc/plan/issue_designs/`（含 26_freshness_timeline_design.md：新鲜度 TTL / 过期提示 / refresh_stale / 时间线事件；27_pricing_modeling_design.md：结构化定价画像 / 成本估算；28_structured_export_design.md：结构化导出 / 定时调度轮 / 异动告警）

## 里程碑状态

- [x] M0 环境与项目骨架
- [x] M1 骨架闭环（采集→分析→报告）
- [x] M2 记忆与自进化
- [x] M3 多 Agent 协作 + 评测体系
- [x] M4 工程化（Web/MCP/CI/断点）
- [x] M5 数据新鲜度 + 竞品时间线（设计文档 26：维度 TTL / 过期提示 / `refresh_stale` 过期重爬 / 跨分析 diff → 时间线事件 / `timeline` 记忆 + CLI/Web 查询）
- [x] M6 结构化定价画像（设计文档 27：`PricingProfile` 档位 + 按量计费 + 模型档位 / light·medium·heavy 成本估算 / 企业询价标注 / 报告渲染与归档 `pricing_profiles` / 时间线价格变化 diff）
- [x] M7 结构化导出 + 定时跑 + 异动告警（设计文档 28：`report_exporter` 竞品/对比矩阵 JSON（schema v1.0.0）/ `api.run_scheduled` 按 TTL 定时重爬 / `alerting` 异动告警（Console/FileAlertSink）/ CLI `schedule`）
