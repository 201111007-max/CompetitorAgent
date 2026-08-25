# AI coding agent 竞品分析 Agent

自动采集并分析 **AI coding agent** 竞品（Claude Code、Cursor、Windsurf、Copilot 等），
输出含功能 / 定价 / 性能 / 生态 / 口碑 / 路线图的 Markdown 报告，
并附**数据新鲜度注记**（维度 TTL / 过期提示）、跨分析**竞品时间线**（价格/版本/功能变化事件），
以及**结构化定价画像**（档位 / 按量计费 / 典型用量成本估算 / 企业询价标注）。

## 仓库结构

```
.
├── README.md                  # 本文件
├── .gitignore
├── .github/workflows/ci.yml   # CI：ruff / mypy / pytest / benchmark
└── competitor_agent/          # 竞品分析 Agent（唯一源码包）
    ├── README.md              # 项目详述：快速开始 / CLI / Web / MCP / 编程调用 / 架构
    ├── docs/                  # 契约文档（interfaces / domain_models / prompts / data_sources / ...）
    ├── config/review_config.yaml  # 预算 / 维度 / 新鲜度 TTL / 编排开关
    ├── domain_types/          # 领域数据模型（InfoGap / Observation / CompetitorStrategy / ReportFreshness / ...）
    ├── interfaces/            # Protocol 契约层（context / exceptions / memory / reporter）
    ├── core/                  # 框架内核（预算 / 取消 / checkpoint / 报告构建与渲染 / 输入清洗 / URL 守卫 / 竞品注册与发现）
    ├── agent/                 # ReAct 引擎 + Lead 编排（make_plan / delegate / subagent_registry）+ prompts + 护栏
    ├── collector/             # 数据源工具（web / github / pricing / benchmark / review）
    ├── skills/                # skill 文档（规划 / 维度抽取 / 事实边界 / 置信度披露，注入 LLM）
    ├── knowledge_base/        # 竞品知识库（RAG）
    ├── memory/                # 四层记忆 + 竞品时间线（timeline_memory）
    ├── evaluation/            # 评测体系（benchmark / ablation / behavior / failure）
    ├── mcp_server/            # MCP Server（对外暴露采集 / 分析工具）
    ├── facade/api.py          # 外部唯一入口 CompetitorAnalysisAPI
    ├── web_app.py             # FastAPI + SSE 可视化
    ├── secret_vault.py        # 凭据池
    ├── cli.py                 # 命令行入口（analyze / history / refresh / timeline / schedule）
    └── tests/                 # unit / integration / evaluation
```

> 工具缓存与报告生成物均写在仓库外（`~/.cache/competitor_agent`、`~/.competitor_agent/reports`）。

## 快速开始

```bash
cd competitor_agent
pip install -e ".[dev]"

# 运行测试
pytest
```

## 启动方式

```bash
# CLI
python -m competitor_agent.cli analyze "Cursor"
python -m competitor_agent.cli history --competitor cursor

# Web（SSE 可视化）
pip install -e ".[web]"
python -m competitor_agent.web_app --port 8000

# MCP Server
pip install -e ".[mcp]"
python -m competitor_agent.mcp_server.server --transport stdio
```

## 架构要点

- **主路径仅 LLM**：`run()` 统一入口——registry/compare/discovery 全 resolution 同走一条 Lead Agent 单 loop，LLM 回合内自调通用工具编排（`make_plan` 规划 → `delegate` 批量并发委派维度/候选子 Agent → 可选 `web_search_candidates` 枚举候选 / `aggregate_report` 聚合 → Final Answer 组 REPORT_SCHEMA/dimensions[]），组装按 `plan.resolution` 统一分型（CompetitorReport / ComparisonReport 矩阵 + 结论段）。
- **保证型逻辑代码兜底**：url_guard / 注入防护 / 预算 / 取消 / checkpoint / 聚合渲染 / 并发与候选数硬上限 / 评测不进 LLM 决策。
- **新鲜度与时间线**：维度 TTL / 过期重爬 / 跨分析 diff → 时间线事件。
- **结构化导出 + 定时跑 + 异动告警**：竞品/对比矩阵 JSON + `api.run_scheduled` + 告警 sink。
- **评测体系**：benchmark / ablation / failure 类型统计（HARNESS 0.11.0）。

## 文档

- 项目详述（CLI / Web / MCP / 编程调用 / 里程碑状态）：[competitor_agent/README.md](competitor_agent/README.md)
- 契约文档：`competitor_agent/docs/`
- CI：`.github/workflows/ci.yml`（ruff / mypy / pytest / benchmark）