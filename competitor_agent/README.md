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

# 设计文档 46/47：默认 use_llm=True，主路径仅 LLM（需配置 LLM API Key）
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
├── config/review_config.yaml   # 预算/维度/终止阈值/新鲜度 TTL 配置
├── domain_types/               # 领域数据模型（InfoGap/Observation/CompetitorStrategy/ReportFreshness...）
├── interfaces/                 # Protocol 契约层
├── core/                       # 框架内核（双循环/预算/停止验证/报告/checkpoint）
├── agent/                      # ReAct 交互层 + 护栏 + prompts
├── collector/                  # 数据源（web/github/pricing/benchmark/review）
├── analyzers/                  # 维度分析器（仅 LLM，无规则降级）
├── skills/                     # skill 文档（规划/各维度抽取/事实边界/置信度披露，注入 LLM）
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
- 逐期设计文档：`../doc/plan/issue_designs/`（含 26_freshness_timeline_design.md：新鲜度 TTL / 过期提示 / refresh_stale / 时间线事件；27_pricing_modeling_design.md：结构化定价画像 / 成本估算；28_structured_export_design.md：结构化导出 / 定时调度轮 / 异动告警；47_llm_only_pipeline_design.md：主路径仅 LLM 解析，无规则降级；48_skill_guided_pipeline_design.md：写死代码知识型规则 → skill 化，主体流程 LLM 驱动 + 保证型逻辑代码兜底；49_domain_agent_orchestration_design.md：多 Agent 领域差异化编排——证据链回填+跨维度冲突 / 新鲜度驱动委派 / 对抗式评审 / 跨竞品同源去重 / 经验路由）

## skill 机制（设计文档 48）

`skills/*.md`（YAML frontmatter：name/description + 正文规范）承载"知识型"写死内容：
规划规范（planning）、6 个维度抽取规范、真值/事实边界（fact_verification）、置信度披露（confidence_disclosure），
经 `SkillLoader` 以独立 `<skill name="...">` system 消息注入分析/规划 prompt；保证型逻辑（安全/路由/校验/阈值/聚合）仍由代码兜底。
目录缺省 `skills/`，可用环境变量 `SKILLS_DIR` 覆盖（测试/评测注入确定性内容）；文件缺失静默跳过。

## 多 Agent 领域差异化编排（设计文档 49）

`TeamOrchestrator` 固定流水线（Collector→Analyzer→Validator→Reporter）之上追加 5 项**领域差异化编排**
（对比 deer-flow 通用骨架后确认 team 已等价其委派模型，缺的是竞品分析领域的编排智能）：

1. **证据链回填 + 跨维度冲突检测**——`DimensionResult.evidence_hashes` + `FactValidator.detect_cross_dimension_conflicts`：
   同 `content_hash` 来源在同一事实键上输出不同值 → 冲突标注/回灌（同维度 `arbitrate` 之外的**跨维度**核对）。
2. **新鲜度驱动委派**——`FreshnessGate` 把 TTL 从报告层提升到编排层：过期维度优先委派采集、新鲜维度跳过采集直入分析、
   时间线变更事件（设计文档 26）提权重采。
3. **对抗式评审 ReviewerAgent（第 5 角色）**——对草稿维度结论主动证伪（复用设计文档 44 `_verify_via_tools` 反方核对），
   `needs_revision` 回灌命中维度重分析（≤1 轮），超限报告标注 `[REVIEWED]`。
4. **跨竞品同源去重**——`SourceDedup` URL→`content_hash` 缓存，`compare` 多竞品共享官网/榜单源省抓取。
5. **经验路由委派**——按 L4 模式排序缺口执行顺序、失败反例降权委派（与设计文档 45 选源成功率/失败惩罚叠加）。

`orchestration` 配置：`reviewer`/`freshness_delegation` 默认关（零行为变化），冲突检测/去重/经验排序默认开（无副作用）；
mock 无缺陷零回灌 → LLM 调用次数不变（设计文档 47/48 不变量）。**不引入 LangGraph/独立子会话轮询**。

## 里程碑状态

- [x] M0 环境与项目骨架
- [x] M1 骨架闭环（采集→分析→报告）
- [x] M2 记忆与自进化
- [x] M3 多 Agent 协作 + 评测体系
- [x] M4 工程化（Web/MCP/CI/断点）
- [x] M5 数据新鲜度 + 竞品时间线（设计文档 26：维度 TTL / 过期提示 / `refresh_stale` 过期重爬 / 跨分析 diff → 时间线事件 / `timeline` 记忆 + CLI/Web 查询）
- [x] M6 结构化定价画像（设计文档 27：`PricingProfile` 档位 + 按量计费 + 模型档位 / light·medium·heavy 成本估算 / 企业询价标注 / 报告渲染与归档 `pricing_profiles` / 时间线价格变化 diff）
- [x] M7 结构化导出 + 定时跑 + 异动告警（设计文档 28：`report_exporter` 竞品/对比矩阵 JSON（schema v1.0.0）/ `api.run_scheduled` 按 TTL 定时重爬 / `alerting` 异动告警（Console/FileAlertSink）/ CLI `schedule`）
