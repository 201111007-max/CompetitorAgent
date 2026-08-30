# 设计文档 70 —— 第二十轮：报告子系统统一设计（主 Agent 驱动格式 + 历史知识库复用 + 目录运行时配置）

> 第二十轮。**合并**三个相关设计问题为一份"报告子系统"文档：
>
> - **问题 2（报告格式）**：报告格式不固定，由主 Agent（Lead）根据用户提问生成，未指定则 Lead 自选 —— **M1 呈现层自由化**（原 doc 69 §2 方案 B 迁入）。
> - **知识库增强**：历史分析过的报告作为知识库，可被复用 —— **M2 规划层意图/格式决策** + **M3 维度级增量复用**。
> - **问题 3（报告目录）**：落盘/下载目录默认进项目目录，Web 运行时可改 —— **Part B 目录运行时配置**。
>
> **原则**（全篇）：分析结构化、呈现自由化；确定性留在中间层（分析/检索/目录解析），自由度只放一头一尾（问题理解与报告撰写）。
> **范围**：本文档为设计（不实现）；实现方向以 §7 已确认决策为准。

## 0. 设计依据：本项目 vs 目标设计的差距

对照目标（基于维度映射的动态报告生成）与本项目现状：

| 目标设计 | 本项目现状 | 差距 |
|---|---|---|
| 规划层：选维度 + 决定查历史 + output_intent | `make_plan` + `parse_task`（REGISTRY/COMPARE/DISCOVERY/CHAT）已选维度/竞品/resolution | 缺 `output_intent`/`format_hint`/`need_history` 显式建模（M2） |
| 维度注册表 | `DIMENSIONS` + `SubagentRegistry`（6 维 + competitor，工具白名单/skill）+ `dimensions.enabled` | 已具备，硬编码在代码；可渐进外置 |
| 分析层：每维结构化输出 | ✅ `DimensionResult` + `SUBAGENT_RESULT_SCHEMA` + evidence + freshness TTL | 达标，无需改 |
| 检索层：历史上下文注入 | ✅ RAG（向量 + rerank + `kb_recall`）+ 四层记忆 + timeline | 达标；缺"注入带 as_of + 冲突以新为准"规则（M3 附带） |
| 呈现层：格式自由 | ❌ `MarkdownRenderer` 代码模板写死 | **M1 主战场** |
| 两层知识库 | 第 2 层（全文语义检索）= 现有 RAG ✅；第 1 层（维度级精确复用）= JSON 导出 + freshness，但**缺"未过期即复用不重跑"决策** | **M3** |

技术栈：LangGraph（可选引擎已有）/chromadb（已有向量库）/`complete_with_tools`（已有 function calling）——**均不需新引入**。

## Part A — 报告格式自由化与历史知识库

### A.1 M1 呈现层自由化（问题 2 方案 B）

**现状链路**：

```
Lead Final Answer (REPORT_SCHEMA JSON / 散文+【市场格局核心结论】)
   → react_report.assemble(_parse_report 提取 JSON) → dimension_results
   → CompetitorReport.markdown_report = MarkdownRenderer.render(report)   # 代码模板
对比/普查 → assemble_comparison: render_comparison() 矩阵 + 提取 Lead 结论段拼入
```

**目标**：正文 = Lead 生成（格式贴用户提问；未指定则 Lead 自选：要点/表格/分节/公告稿）；结构化 = 代码保留；模板保底。

**（1）Prompt（`agent/prompts/react_system.py`）**：`build_lead_system_prompt` Final Answer 两段式——

```
Final Answer 输出两段：
① 报告正文（Markdown，给人读）：格式贴合用户提问——用户指定了格式（表格对比/要点式/公告稿/一页纸）就按其指定；
   未指定则由你自行选择并保证结构清晰（结论先行，可含要点/表格/分节/证据链接）。
② 结构化数据（JSON，给机器用）：仍是 REPORT_SCHEMA 原样：{"competitor": ..., "dimensions": [...]}，
   放正文之后，用独立 JSON 代码块或明显边界；只输出一份 JSON。
```

候选竞品子 Agent（`_build_competitor_prompt`）保持结构化 JSON 输出不变（结果归矩阵，不产正文）。

**（2）装配（`facade/react_report.py`）**：新增 `_split_body_and_payload(lead_answer) -> (body, payload)`——
JSON 块前文本为 body（复用 doc 65 `_extract_json_block`/`_strip_json_blocks` 防残留）；`assemble` 的
`markdown_report = body or MarkdownRenderer.render(report)`；`dimension_results` 仍从 payload 解析（现状不变）。

**（3）对比/普查（`facade/comparison_report.py`）**：`lead_body`（【市场格局核心结论】之前的正文，含结论段）+ 代码矩阵附录
→ `markdown_report = lead_body + "\n\n" + matrix`（信息不丢；前端 dossier 已按 markdown 渲染）。

**（4）模板（`core/markdown_renderer.py`）**：结构不改，仅作保底。

**（5）开关**：`report.lead_formatted_body: true`（默认开）；`false` 全回退模板。

**（6）前端（`static/app.js`）**：无改动（report payload 的 markdown_report 已是正文；chips 用结构化字段）。

**（7）测试迁移（关键）**：mock LLM 无正文 → body 空 → 模板保底 → **既有 44 处模板断言零改动**；
新增 `_split_body_and_payload`（纯 JSON/正文+JSON/括号配平）、assemble 分支、对比矩阵附录、开关用例；
真实 LLM 端到端验证"正文出、JSON 不进正文"。

### A.2 M2 规划层意图/格式决策（`output_intent` + `format_hint`）

**目标**：给呈现层"定调"——知道给谁看、什么目的，才能决定组织方式。

- `make_plan`（`agent/prompts/react_system.py` + `react_loop._on_plan` 校验）schema 增三个可选字段：
  - `output_intent`：给谁看/目的（CTO 选型 / 投资人 / 自己备忘…）
  - `format_hint`：问题类型定调（对比型 / 深度单体型 / 变化追踪型 / 开放型）——**只定调不强制**
  - `need_history`：是否需要检索历史（"和上次比变化"类问题）
- 呈现层 prompt 结构（M1 之上叠加）：用户原问题 + `output_intent` + `format_hint` + 本次结构化结果 + 检索到的历史（标 `as_of`）+ 约束规则（基于素材禁编造 / 事实附来源 / 对比优先表格 / 结尾有结论）。

### A.3 M3 维度级增量复用（历史报告当知识库）

**目标**：历史报告作为知识库，核心是"**精确复用不重跑**" + "**语义注入**"两层。

- **精确层（复用决策）**：规划后、委派前，按 `target × dimension` 查历史导出 JSON（`<output>/<竞品>.json` 已含每维度 summary/confidence + created_at + freshness TTL）——
  命中且**未过期** → 该维度结果直接注入、**跳过重跑**；只跑缺的/过期的维度（成本控制关键）。
- **语义层（上下文注入）**：现有 RAG 已做（全文切块 + 向量 + rerank + `kb_recall` 注入）。补一条**呈现规则**：
  历史结论注入带 `as_of` 日期；与本次新数据冲突时以新为准并显式指出变化（= 变化追踪卖点，timeline diff 已给数据）。
- **实现形态**：做成**工具**（如 `reuse_dimension_results(target, dims)`，LLM 回合内自调，守 doc 62"代码守骨架、LLM 自调工具"哲学），
  而非写死代码流程；未命中/过期 → 工具返回空 → 子 Agent 照常采集。

## Part B — 报告目录运行时配置（问题 3）

### B.1 用户决策（2026-08-29）

| 决策 | 结论 |
|---|---|
| 决策 1 落盘 | 报告自动保存到**项目目录 `output/`**（不再默认 C 盘） |
| 决策 2 入口 | A2 运行时入口——Web UI 可改，改动即生效 |
| 决策 3 下载 | 下载默认到**项目目录 `download/`** |
| 决策 4 浏览器下载自选 | 未选——浏览器保存位置保持浏览器默认，不做 showSaveFilePicker |
| 决策 5 持久化 | `<data_dir>/settings.json` |

### B.2 设计

**默认目录（代码计算，不硬编码绝对路径）**：`project_dir()` = 本包 `__file__` 的 `parents[2]`（仓库根）；
`default_output_dir() = <项目根>/output`；`default_download_dir() = <项目根>/download`；`settings_path() = get_data_dir()/settings.json`。

**settings.json 形状**（空字符串 = 未设置 → 默认）：

```json
{ "report_output_dir": "", "report_download_dir": "" }
```

**目录解析优先级**（`resolve_output_dir`，向后兼容）：显式 output_dir 参数 > settings > config.report.output_dir（YAML 置空则跳过）> 项目默认 output/。
新增 `resolve_download_dir()`：settings.report_download_dir 非空用之，否则项目 download/。

**下载写入 + 读侧回退**：新增 `save_report_download(report)`（分析完成时把 .md 原子写进下载目录）；
`download_file_path(competitor)` 回退链：download/ → output/ → 旧归档 `~/.competitor_agent/reports/competitor/`（历史报告不迁移不丢）；
`report_file_path`（报告库读）同样旧归档回退。

**Web 端点**：`GET /api/settings` → 当前生效值 + data_dir + 默认值；`PUT /api/settings`（传 `""` 重置）→ 原子写 settings.json → 返回更新结果。鉴权同现有端点。

**前端设置面板**：rail 头部「设置」→ 面板含「报告保存目录/下载目录」两行：选择目录按钮（优先 `window.showDirectoryPicker()`，Chromium；不支持回退文本输入）+ 当前值 + 重置为默认 + 保存。

**配置与 .gitignore**：`review_config.yaml` `report.output_dir: ""`（空 = 项目 output）；`.gitignore` 加 `output/`、`download/`。

## 改动清单

| 文件 | 改动 |
|---|---|
| `agent/prompts/react_system.py` | 两段式 Final Answer + make_plan schema（output_intent/format_hint/need_history） |
| `facade/react_report.py` | `_split_body_and_payload`；assemble 正文优先/模板保底 |
| `facade/comparison_report.py` | Lead 正文 + 矩阵附录 |
| `core/markdown_renderer.py` | 不改（保底模板） |
| `core/report_settings.py`（新） | project_dir / 默认目录 / settings 读写 |
| `core/report_archiver.py` | resolve_output_dir 优先级 + resolve_download_dir + save_report_download + 旧归档回退 |
| `web_app.py` | GET/PUT /api/settings；下载端点读 download 目录；分析完成写下载副本 |
| `config/review_config.yaml` | `report.output_dir: ""`；`report.lead_formatted_body: true` |
| `config/loader.py` | `ReportConfig.lead_formatted_body` |
| `.gitignore` | `output/`、`download/` |
| `static/app.js` + `style.css` | 设置面板 |
| 环境（不入 git） | `TAVILY_API_KEY`（问题 1，doc 69） |

## 验证方式

- 单测：`_split_body_and_payload`/assemble 分支/对比附录/开关；settings 读写/解析优先级/下载落盘/旧归档回退；`GET/PUT /api/settings`。
- 回归：既有 44 处模板断言零改动；全量 `pytest`；`ruff`。
- 起服冒烟：settings 默认显示项目 output/download；PUT 改路径生效；旧报告仍可开/下载；真实 LLM 端到端验证"正文出、JSON 不进正文"。

## 7. 已确认决策（2026-08-29，交互确认，全部按推荐）

| # | 决策点 | 结论 |
|---|---|---|
| 1 | 默认开关 `lead_formatted_body` | **默认开**（正文默认由主 Agent 生成，配置可关回退模板） |
| 2 | 对比/普查矩阵呈现 | **Lead 正文 + 代码矩阵附录**（信息不丢、前端零改动） |
| 3 | M2 规划层建模深度 | **全加** `output_intent` / `format_hint` / `need_history`（可选字段，只定调不强制） |
| 4 | M3 复用形态 | **做成工具** `reuse_dimension_results`（LLM 回合内自调，守 doc 62 哲学） |
| 5 | 旧报告处理 | **读侧回退不迁移**（`~/.competitor_agent/reports/competitor` 仍可开/下载，零风险） |
| 6 | 决策 4：浏览器下载自选 | **不做**（保持浏览器默认保存位置，服务端下载目录已满足需求） |
| 7 | 设置面板位置 | **rail 头部齿轮按钮**（doc 68 布局自然入口） |

> 本文档实现方向以本表为准。

## 8. 运行期健壮性补强（第二十一轮，2026-08-29 grilling 逐项确认，全部按推荐）

> 背景：doc 70 首轮落地后真实市场普查（国内外 coding agent）暴露 5 个运行期问题：
> 搜索 key 未进服务器进程致搜索禁用、delegate 60s 超时致零候选、零候选对比报告触发
> 归档崩溃 + 置信度 0%、对比 JSON 仍写 C 盘 comparison_dir、无 payload 的 report 事件
> 产生「report/已批准（无正文）」幽灵报告。本节为收口设计（决策树经 grilling 确认）。

### 8.1 零候选对比报告健壮性（#1 归档崩溃 + #2 置信度 0% 同根）

**根因**：候选子 Agent 全部超时/失败 → `report.competitors`/`report.reports` 为空 →
① `web_app.py` 对比归档 `competitor_name=" / ".join([])` = `""` → `SessionArchive.archive_session`
抛 `ValueError("会话归档需要 competitor_name")` → SSE 异常（「系统分析异常」）；
② 载荷置信度 `max((r.overall_confidence ...), default=0.0)` = 0.0（「置信度 0%」）。

**决策**：
- **D1a 归档兜底**：`web_app.py` 对比归档 `names = " / ".join(...) or "compare"`（空名占位）；
  归档调用整体包 `try/except`（失败仅告警，**永不阻塞 SSE 主流程**）。
- **D1b 零候选呈现**：report 载荷新增 `has_candidates: bool`（候选为 0 → `false`）；
  前端 dossier 在 `has_candidates === false` 时显示提示「未收集到候选数据（候选委派超时/失败），
  置信度 0% 为事实」，不再只显示干巴巴 0%。
- **D1c 不加代码级重试**：守 doc 62「代码守骨架、LLM 回合内自调」哲学——超时后 Lead 本就可在
  回合内再 delegate；本次只优雅降级 + 提示（靠 §8.4 超时调大缓解）。
- **D1d 空报告留痕**：零候选空报告仍落盘 `.md` + 导出 JSON + 入库（报告库可见可点开看原因），
  不额外制造垃圾（对比 .md 内容为「矩阵空 + Lead 结论段 + 提示」）。

### 8.2 comparison_dir 收口（#3 对比 JSON 写 C 盘）

**根因**：`api.py::_export_comparison_json` 用 `config.report.comparison_dir`
（yaml 仍为 `~/.competitor_agent/reports/comparison`）；doc 70 Part B 只迁移了竞品 output_dir，
漏了对比矩阵 JSON。

**决策**：
- **D2a 新落点**：`<output_dir>/comparison/`（默认 = `<项目>/output/comparison/`）。
  新增 `report_archiver.resolve_comparison_dir()`：**恒派生自** `resolve_output_dir()`（`/comparison`），
  不读 config.comparison_dir、不读 settings（无新配置键）。
- **D2b 不纳入 settings.json**：对比 JSON 是次级产物，跟随主输出目录即可，界面不添乱。
- **D2c 旧目录读侧回退**：`~/.competitor_agent/reports/comparison/*.json` 读侧回退不迁移
  （历史对比数据不丢；当前无读消费方，作兜底声明，未来有读方再补回退逻辑）。
- **D2d 审批不覆盖 comparison**：`/api/reports/{name}/status` + review 只查竞品 JSON，
  对比报告无审批语义、status 保持默认 approved。
- 实现：`report_exporter.export_comparison_json` 默认（`output_dir=None`）→ `resolve_comparison_dir()`；
  `api.py:659` 改 `export_comparison_json(report)`；`report_visuals` 的 comparison 输出路径同步；
  yaml `comparison_dir: ""`（置空，注释说明已并入 output/comparison）。

### 8.3 无 payload report 事件净化（#5 幽灵空报告）

**根因**：单/对比收尾 `_emit(ProgressEvent(event="report", ...))` 发**无 payload** 的 report 事件
（api.py:426-433 / 461-468）；`report` ∉ `_NARRATIVE_EVENTS` → web `_event_generator` 原样透传 →
前端 `handleEvent 'report'` 当真实报告渲染成空 dossier（title="report"、无正文、
`fetchStatus` 缺 JSON → 默认「已批准」）。

**决策**：
- **D3a 丢弃而非删除**：api 层事件保留（CLI/MCP 的「报告完成」信号不变）；web 侧在事件分层
  丢弃「无 payload 的 report 事件」（`_narrative_sse` 前加判定：`event.event == "report" and not event.payload` → 丢弃）。
- **D3b 单/对比统一处理**：同一丢弃逻辑覆盖两条路径（一处判定，天然统一）。

### 8.4 工具启停 + 超时配置（#4 榜单/舆情未启用、delegate 超时）

**根因**：`build_benchmark_provider` 需 `benchmark_provider ∈ {swebench|terminalbench|aider}`
（yaml `""` → 未启用）；`sentiment_sampling` 需 `sentiment_provider ∈ {hackernews|reddit}`
（yaml `""` → 未启用）；搜索 key 未进服务器进程（已修）；`subagents.timeout_seconds: 60`
（`delegate_tool._DEFAULT_TIMEOUT_SECONDS=60`）在无搜索/榜单下靠多次 web_extract 采集不够。

**决策**：
- **D4a** `collector.benchmark_provider: "swebench"`（官方 SWE-bench 榜单表最稳、与 coding agent 最相关）。
- **D4b** `collector.sentiment_provider: "hackernews"`（公开免 Key，即启即用）。
- **D4c** `subagents.timeout_seconds: 120`（给子 Agent 足够 web 采集时间，不过度拖延）。
- **D4d 未启用提示带原因**：`web_search`/`benchmark_scores`/`sentiment_sampling` 未启用分支的
  回灌文案从「未启用」改为带原因（缺 `TAVILY_API_KEY` / 未配 `benchmark_provider` /
  未配 `sentiment_provider`），Lead 不再困惑、可自行改策略（自恢复）。

### 8.5 测试

- 零候选对比归档兜底：零候选走完 SSE 不崩、归档 competitor_name 为 "compare"。
- 零候选载荷 `has_candidates == false`；前端提示分支。
- 无 payload 的 report 事件被 web 丢弃（SSE 流无幽灵 report 事件；带 payload 的正常放行）。
- `resolve_comparison_dir()` 派生 `<output>/comparison`；`export_comparison_json` 默认写入新目录；
  旧 comparison 目录读侧回退；`api._export_comparison_json` 不再用 comparison_dir。
- 配置新值：`benchmark_provider="swebench"`/`sentiment_provider="hackernews"` 时
  `build_benchmark_provider`/`build_sentiment_provider` 返回非 None；`subagents.timeout_seconds=120` 透传 delegate。
- 既有 987 unit / 61 integration+e2e / benchmark 门禁回归不破。
- 起服冒烟：`/api/settings` 仍 200；真实普查不再崩「会话归档需要 competitor_name」。
- **跨平台路径坑（CI=Linux）**：doc70/§8 测试曾硬编码盘符绝对路径（`D:/...`），在 Linux 上
  `Path("D:/x")` 非绝对路径会被拼到 CWD → CI「test (3.11)」pytest 挂 4 项（3.11 只是先到先取消，
  实为平台问题）。已修：`test_report_settings_70`/`test_web_settings_70` 改 tmp_path 派生绝对路径，
  `web_app._normalize_dir_setting` 加 `_is_abs_like` 盘符绝对判定（不依赖宿主 OS 的 `Path.is_absolute`）；
  Docker python:3.11 复现 4 挂 → 1148 passed / 43 skipped 全绿。
