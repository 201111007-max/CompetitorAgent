# competitor_agent — AI coding agent 竞品分析 Agent

自动采集并分析 AI coding agent 竞品（Claude Code、Cursor、Windsurf、Copilot 等），
输出含功能 / 定价 / 性能 / 生态 / 口碑 / 路线图的 Markdown 报告。

复用 `dota_helper` 的框架思想（双循环编排、信息缺口驱动、证据链防幻觉、四层记忆），
但独立目录、独立包、**零 import 耦合**。

## 快速开始

```bash
cd competitor_agent
pip install -e ".[dev]"

# 配置凭据（可选，缺失时自动降级规则分析）
python -m competitor_agent.cli config set-key LLM_API_KEY

# 运行测试
pytest
```

## 目录结构

```
competitor_agent/
├── config/review_config.yaml   # 预算/维度/终止阈值配置
├── domain_types/               # 领域数据模型（InfoGap/Observation/CompetitorStrategy...）
├── interfaces/                 # Protocol 契约层
├── core/                       # 框架内核（双循环/预算/停止验证/报告）
├── agent/                      # ReAct 交互层 + 护栏 + prompts
├── collector/                  # 数据源（web/github/pricing/benchmark/review）
├── analyzers/                  # 维度分析器（LLM 驱动，规则降级）
├── knowledge_base/             # 竞品知识库（RAG）
├── memory/                     # 四层记忆
├── team/                       # 多 Agent 协作
├── evaluation/                 # 评测体系
├── mcp_server/                 # MCP Server 对外开放采集工具
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
- [ ] M1 骨架闭环（采集→分析→报告）
- [ ] M2 记忆与自进化
- [ ] M3 多 Agent 协作 + 评测体系
- [ ] M4 工程化（Web/MCP/CI/断点）
