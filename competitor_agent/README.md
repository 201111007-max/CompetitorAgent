# competitor_agent — AI coding agent 竞品分析 Agent

自动采集并分析 AI coding agent 竞品（Claude Code、Cursor、Windsurf、Copilot 等），
输出含功能 / 定价 / 性能 / 生态 / 口碑 / 路线图的 Markdown 报告，
并附**数据新鲜度注记**（维度 TTL / 过期提示）、跨分析**竞品时间线**（价格/版本/功能变化事件），
以及**结构化定价画像**（档位 / 按量计费 / 典型用量成本估算 / 企业询价标注）。

复用 `dota_helper` 的框架思想（信息缺口驱动、证据链防幻觉、四层记忆），
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

# 设计文档 47/49：主路径仅 LLM（需配置 LLM API Key），Lead ReAct 编排
api = CompetitorAnalysisAPI(llm=LLMClient(...), use_llm=True)
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
├── config/review_config.yaml   # 预算/维度/新鲜度 TTL/编排开关配置
├── domain_types/               # 领域数据模型（InfoGap/Observation/CompetitorStrategy/ReportFreshness...）
├── interfaces/                 # Protocol 契约层（context/exceptions/memory/reporter）
├── core/                       # 框架内核（预算/取消/checkpoint/报告构建与渲染/输入清洗/URL 守卫/竞品注册与发现）
├── agent/                      # ReAct 引擎 + Lead 编排（make_plan/delegate/subagent_registry/react_schemas）+ prompts + 护栏
├── collector/                  # 数据源（web/github/pricing/benchmark/review 工具实现）
├── skills/                     # skill 文档（规划/各维度抽取/事实边界/置信度披露，注入 LLM）
├── knowledge_base/             # 竞品知识库（RAG）
├── memory/                     # 四层记忆 + 竞品时间线（timeline_memory）
├── evaluation/                 # 评测体系（benchmark/ablation/behavior/failure）
├── mcp_server/                 # MCP Server（对外暴露采集/分析工具）
├── web_app.py                  # FastAPI + SSE 可视化
├── facade/api.py               # 外部唯一入口 CompetitorAnalysisAPI
│   └── react_report.py         # Lead Final Answer（REPORT_SCHEMA JSON）→ CompetitorReport 组装
├── secret_vault.py             # 凭据池（数据目录 ~/.competitor_agent/）
└── tests/                      # unit / integration / evaluation
```

## 设计文档

- 架构总纲：`../doc/ai_coding_agent_competitor_analysis_architecture.md`
- 分步实现计划：`../doc/plan/implementation_plan.md`
- 各模块契约/规范：`docs/`（interfaces/domain_models/prompts/data_sources/configuration/evaluation_guide/testing/usage/api）
- 逐期设计文档：`../doc/plan/issue_designs/`（含 26_freshness_timeline_design.md：新鲜度 TTL / 过期提示 / refresh_stale / 时间线事件；27_pricing_modeling_design.md：结构化定价画像 / 成本估算；28_structured_export_design.md：结构化导出 / 定时调度轮 / 异动告警；47_llm_only_pipeline_design.md：主路径仅 LLM 解析，无规则降级；48_skill_guided_pipeline_design.md：写死代码知识型规则 → skill 化，主体流程 LLM 驱动 + 保证型逻辑代码兜底；49_domain_agent_orchestration_design.md：多 Agent **LLM 主导编排**——deer-flow 式 Lead Agent 动态委派 + 独立 LLM 子 Agent 后台并发 + 结果回填，独有流程/校验脚本 skill/工具化，废弃固定流水线）

## skill 机制（设计文档 48）

`skills/*.md`（YAML frontmatter：name/description + 正文规范）承载"知识型"写死内容：
规划规范（planning）、6 个维度抽取规范、真值/事实边界（fact_verification）、置信度披露（confidence_disclosure），
经 `SkillLoader` 以独立 `<skill name="...">` system 消息注入分析/规划 prompt；保证型逻辑（安全/路由/校验/阈值/聚合）仍由代码兜底。
目录缺省 `skills/`，可用环境变量 `SKILLS_DIR` 覆盖（测试/评测注入确定性内容）；文件缺失静默跳过。

## 多 Agent LLM 主导编排（设计文档 49，deer-flow 式）

主路径是一条 **Lead Agent 编排的 LLM 主导多 Agent 流程**（`analyze()` 即 Lead ReAct 循环，无代码阶段序列）：

```
analyze(task)
  → Lead ReactLoop（共享 cancel/budget/memory/RAG/events，max_steps≈12）
  → Lead LLM 自主编排：首步必须 make_plan（PLAN_SCHEMA）→ 自由调用工具
    → delegate 批量后台并发委派维度子 Agent（结果合并回填 Observation）
    → 低置信/冲突关键数值可 validate_facts / 重新抓取核验
    → Final Answer 输出 REPORT_SCHEMA JSON
  → react_report.assemble → CompetitorReport（复用 ReportBuilder 渲染/freshness/证据链）
```

- **Lead = `ReactAgent` + `make_plan`/`delegate` 工具**（`agent/react_loop.py` plan-first 强制）：
  委派哪些维度、分几批、是否补证、何时收尾全部由 LLM 自主决定。
- **子 Agent = 独立 LLM Agent**（`agent/subagent_registry.py` 预注册 pricing/feature/performance/ecosystem/sentiment/roadmap）：
  每个 = `ReactAgent` + 对应维度 skill + fact_verification/confidence_disclosure + 工具子集（排除 `analyze_competitor` 防递归）。
- **保留逻辑 → skill / 工具 / 代码兜底**：规划与抽取规范、事实边界、置信度披露走 skill 注入；
  选源/复核/冲突/新鲜度/定价归一化走工具（`select_source`/`validate_facts`/`detect_conflict`/`check_freshness`/`analyze_pricing`）；
  url_guard/注入防护/预算/取消/checkpoint/聚合渲染/评测保持代码强制兜底，不进 LLM 决策。
- 无 LLM（无 API Key）显式抛 `LLMUnavailableError`，无静默规则降级；`analyze_team`/`analyze_stream` 为同一路径的薄包装。

## 里程碑状态

- [x] M0 环境与项目骨架
- [x] M1 骨架闭环（采集→分析→报告）
- [x] M2 记忆与自进化
- [x] M3 多 Agent 协作 + 评测体系
- [x] M4 工程化（Web/MCP/CI/断点）
- [x] M5 数据新鲜度 + 竞品时间线（设计文档 26：维度 TTL / 过期提示 / `refresh_stale` 过期重爬 / 跨分析 diff → 时间线事件 / `timeline` 记忆 + CLI/Web 查询）
- [x] M6 结构化定价画像（设计文档 27：`PricingProfile` 档位 + 按量计费 + 模型档位 / light·medium·heavy 成本估算 / 企业询价标注 / 报告渲染与归档 `pricing_profiles` / 时间线价格变化 diff）
- [x] M7 结构化导出 + 定时跑 + 异动告警（设计文档 28：`report_exporter` 竞品/对比矩阵 JSON（schema v1.0.0）/ `api.run_scheduled` 按 TTL 定时重爬 / `alerting` 异动告警（Console/FileAlertSink）/ CLI `schedule`）
- [x] M8 评测盲区覆盖（设计文档 29：ecosystem/sentiment/roadmap 维度入 benchmark，harness 0.4.0）
- [x] M9 消融/对比实验（设计文档 30：`enable_rag`/`enable_memory` 开关 + `AblationRunner` 变体对比）
- [x] M10 失败类型统计（设计文档 31：`FailureType` 五类归因聚合入 benchmark 报告）
- [x] M11 多 Agent LLM 主导编排（设计文档 49 重写：Lead ReAct `make_plan`/`delegate` 动态委派 + `SubagentRegistry` 预注册 6 维度独立 LLM 子 Agent 后台并发回填 + `react_report.assemble` 组 REPORT_SCHEMA；删除固定流水线/规则管线（team/analyzers/strategic_loop 等）；benchmark ReAct-scripted + HARNESS 0.7.0）
