# 设计文档 66 — 真实 Tavily 搜索接入 + 报告路径决策对齐 + 前端隐藏未关闭缺口 + 前端阶段事件 todo 化

> 第十六轮。用户真实运行（2026-08-29，`sess_1787984174985`「帮我分析下市面上常见的coding agent，选出效果好，价钱相对适中的，跟其他家对比」）复现五类问题：
> ① 报告正文仍有 `{...}`/`[...]`（大括号中括号）；② 报告内容缺失、不反映真实需求；③ web_search 用不了（Tavily key 已配置却无效）；④ 前端展示「未关闭缺口」；⑤ 前端 Lead 气泡把"Lead 编排: {task}"与"开始 ReAct 推理"两段引擎文案挤在一行，且"开始 ReAct 推理"这类引擎内部阶段标记无信息价值。
> 本文档合并解决：**真实 Tavily 接入（doc 61 声称"已实现"但实际从未落地）** + **报告路径由主 Agent 决策对齐（Q3 根因）** + **前端隐藏未关闭缺口** + **畸形 JSON 兜底补强（doc 65 遗留）** + **前端阶段事件 todo 化（叙述流与引擎内部标记分层）**。

## 1. 问题现状

### 1.1 现象与证据（真实运行日志 `C:\Users\d\.competitor_agent\logs\sess_1787984174985.log`）

1. **web_search 不可用**：任务被 LLM 判为多竞品普查，Lead 回合内调 `web_search_candidates(scope='mainstream coding agents...')`，但 `_web_search_candidates` → `self._discoverer.candidates()` → `self._web_tool is None` → 返回 `[]` → 回灌"候选竞品枚举失败（联网搜索不可用）"。**配置了 TAVILY_API_KEY 但代码零读取**。
2. **报告路径错位**：`make_plan` 只写了 `competitor="coding-agent-market"`（无 `resolution`/`competitors`），`delegate_collector` 空（Lead 从未成功 delegate）→ `_plan_resolution(plan, parsed, candidate_count=0)` 返回 `registry` → 走单竞品 `CompetitorReport`，把市场普查当单竞品分析。
3. **Lead 自编兜底**：因搜索失效，Lead 用 `aggregate_report` 把自己**凭知识写的** 5 家竞品塞进 parts（无联网核验），再 `validate_facts`/`detect_conflict`，最终 Final Answer 输出**畸形 JSON**（`"details": ,` 空值 + `, , , , , ]` 空数组项）。
4. **畸形 JSON 未被兜底净化**：`_extract_json_block`/`_strip_json_blocks` 都要求 `json.loads` 严格成功；畸形 JSON 两者都认不出 → `_parse_report` 返回 None → `_fallback_single_dimension` 把**整坨 JSON 原文**塞进 react 维度 summary（`_strip_json_blocks` 因 load 失败保留原字符）→ 前端看到 `{...}`/`[...]`。
5. **前端展示未关闭缺口**：`markdown_renderer.render` 固定输出 `## 未关闭缺口`（plan 6 维全未产出 → 6 条 PARTIAL），前端 markdown 面板原样渲染。
6. **前端引擎文案挤行 + 无价值阶段标记**：Lead 气泡里"Lead 编排: {task}"（`api.py:1577` phase_start）与"开始 ReAct 推理"（`react_loop.py:111` phase_start）**挤在一行**——两者都被 `_NARRATIVE_EVENTS`（web_app.py:73）收敛为 `text_delta`，而 `_text_delta`（web_app.py:195）payload **不带 turn**，前端 `appendSegment`（app.js:103-106）对"同 kind + 同 turn(null) + 未 done"的 text_delta **原地续写不换行** → 合成一个 `.text-seg`；且"开始 ReAct 推理"是 ReactLoop **引擎内部自证阶段**事件，对用户无信息价值，却被无差别打成正文文本。

### 1.2 根因链

```
TAVILY_API_KEY 已配置
   ↓（无代码读取）
web_search 是 stub（web_tools.py:83 仅返回提示文案）
   ↓
CompetitorDiscoverer._web_tool = None（web_app.py:160 未注入）
   ↓
web_search_candidates 返回 [] → Lead 无法枚举候选 → 无法 delegate
   ↓
plan 无 resolution/competitors + delegate_collector 空 → _plan_resolution 归 registry
   ↓
Lead 凭知识 aggregate_report → 畸形 JSON → _parse_report None → react 单维度 + JSON dump
```

## 2. Tavily API 调用方式（依据 `C:\Users\d\Desktop\Tavily API Platform.html`）

保存的页面为 app.tavily.com/playground（含 JS bundle 内嵌完整示例）。

### 2.1 端点与鉴权

- **Base URL**：`https://api.tavily.com`
- **端**：`POST /search`（搜索）、`POST /extract`（抓取 URL 列表）、`POST /crawl`（爬站，分页）
- **鉴权**：HTTP Header `Authorization: Bearer tvly-<KEY>`（Key 前缀 `tvly-`，官方示例 `tvly-YOUR_API_KEY`）；亦可 `TavilyClient(api_key=...)`（Python SDK，本仓库不用 SDK，直接 httpx）。
- **Content-Type**：`application/json`

### 2.2 请求体（search）

```json
{
  "query": "Who is Leo Messi?",
  "search_depth": "basic",          // "basic" | "advanced"（advanced 返回更长 content）
  "topic": "general",               // "general" | "news"
  "time_range": "w",                // 仅 news：d/w/m/y（日/周/月/年）；general 用 "days"
  "days": 7,                        // 仅 news
  "max_results": 5,                 // 1-20，默认 5
  "include_answer": false,          // true → 顶层带合成 answer 摘要
  "include_raw_content": false,     // true → results[] 每项带 raw_content 全文（RAG 用）
  "include_images": false,          // true → 顶层 images[]
  "include_image_descriptions": false, // 需 include_images=true 前置
  "include_domains": [],            // 限定域
  "exclude_domains": [],            // 排除域
  "chunks_per_source": 3            // 仅 advanced + include_raw_content：每源分块数
}
```

### 2.3 响应（search）

```json
{
  "query": "Who is Leo Messi?",
  "answer": "Lionel Messi, born in 1987...",   // include_answer=true 时
  "images": [],
  "results": [
    {
      "title": "Lionel Messi Facts | Britannica",
      "url": "https://www.britannica.com/facts/Lionel-Messi",
      "content": "Lionel Messi, an Argentine footballer...",   // 摘要片段
      "score": 0.81025416,
      "raw_content": null,           // include_raw_content=true 时为全文
      "favicon": "https://britannica.com/favicon.png"
    }
  ],
  "auto_parameters": { "topic": "general", "search_depth": "basic" }
}
```

### 2.4 extract / crawl

- `POST /extract`：`{"urls": ["https://..."], "extract_depth": "basic"|"advanced"}` → `{"results": [{"url":..., "raw_content":...}], "failed_results": [...]}`（抓多页正文，可替代现有 `web_extract` 的补源手段）。
- `POST /crawl`：`{"url": "https://docs.tavily.com", "max_depth": 3, "max_breadth": 30, "limit": 100, "select_paths": ["/documentation/.*"], "exclude_paths": ["/private/.*"], "allow_external": false, "extract_depth": "basic"}` → 分页站点抓取（本期不做）。

## 3. 目标设计

### 3.1 真实 Tavily 接入（落实 doc 61 设计但从未实现的代码）

> **MCP 工具现状**：`web_search` **已经是 MCP 工具**——`mcp_server/tools/__init__.py::TOOL_SPECS["web_search"]`（schema：`query` 必填 + `max_results` 可选）已注册，`mcp_server/server.py::create_server`（server.py:41-42）遍历 `TOOL_SPECS` 全量注册进 FastMCP（`mcp.tool(name=..., description=...)(TOOLS[name])`），描述/schema 只维护注册表一份（doc 40 契约）。同时经 `agent/tool_registry.py::build_react_dispatcher` 同一份 `TOOLS`/`TOOL_SPECS` 成为 Lead/子 Agent 的 ReAct 工具。**无需新增注册**——唯一缺的是 `web_tools.py::web_search` 的实现是返回提示文案的 stub（web_tools.py:83-90），从未接真实搜索引擎。本节把实现替换为真实 Tavily 调用，MCP 与 ReAct 两端自动同源受益。

**新文件 `competitor_agent/collector/search.py`**（按 doc 61 §3.1-3.2 契约落地）：

```python
@dataclass
class SearchHit:
    title: str
    url: str
    snippet: str

class SearchProvider(ABC):
    def search(self, query: str, max_results: int = 8) -> list[SearchHit]: ...

class TavilySearchProvider(SearchProvider):
    """httpx POST https://api.tavily.com/search；
    Authorization: Bearer <key>；search_depth="basic"；
    响应 results[] 映射 title/url/content→SearchHit；
    非 2xx/超时/网络错 → 抛可重试异常（上层降级返回空，不编造）。"""

def build_search_provider(cfg: CollectorConfig) -> SearchProvider | None:
    """cfg.search_provider=="tavily" 且环境变量 TAVILY_API_KEY 存在 → TavilySearchProvider；
    其他/缺 Key/未知名 → None（不启用，保持现状）。"""

def web_search_candidates(task, provider, llm, max_results=8) -> list[dict]:
    """hits → LLM 归纳为 [{"name","home","pricing","docs"}]；
    空/失败 → []（不编造）；复用 JsonLoadsArray 解析。"""
```

**MCP `web_search` 实现替换**（`mcp_server/tools/web_tools.py::web_search`，从 stub 改为真实调用）：

```python
def web_search(query: str, max_results: int = 5) -> str:
    """搜索竞品相关信息（MCP 工具，签名/返回值契约不变：入参 str、出参 str）。

    - 经 `build_search_provider(load_config().collector)` 取 provider（无 Key/未启用 → None）；
    - provider 为空 → 返回可读提示（与现状一致，不抛，不编造结果）；
    - 有 provider → `provider.search(query, max_results)` → 逐条格式化为
      `标题\nURL\n摘要` 文本返回（供 Lead/子 Agent 读取，对齐 `web_extract` 的 str 契约）；
    - 搜索失败（网络/超时/非 2xx）→ 返回可读错误文案（降级，不编造，守 doc 47）。
    """
```

- **两端同源**：`web_search` 的 schema/描述不变（`TOOL_SPECS` 无需改），仅实现替换——MCP Client（stdio/SSE）与 ReAct 子 Agent 调用同一函数、自动获得真实搜索。
- 独立于 `web_search_candidates`（后者是 DISCOVERY 候选枚举专用，走 `CompetitorDiscoverer` 注入链）；`web_search` 是通用搜索工具（子 Agent 补证/普查时 Lead 可自调）。两者共享 `SearchProvider`/`build_search_provider`。

**配置**（`config/loader.py::CollectorConfig` + `review_config.yaml::collector`）：
```python
search_provider: str = ""       # "tavily" / ""；空 = 不启用
search_max_results: int = 8
```
```yaml
collector:
  enable_external_sources: true   # 主开关（doc 61 契约；保 CI 无网络测试可关）
  search_provider: "tavily"
  search_max_results: 8
```
- Key **不落盘**，仅环境变量 `TAVILY_API_KEY`（`config/loader.py` 读 env 同 `COMPETITOR_AUTH_TOKEN` 模式）。
- `.env.example` 追加 `TAVILY_API_KEY=` 占位（.env 已 gitignore）。

**装配**（`facade/api.py::__init__` 发现器构造处，[api.py:242-243](file:///d:/trae_projects/first-agent/competitor_agent/facade/api.py#L242-L243)）：
```python
search_web_tool = web_tool
if search_web_tool is None and use_llm and llm is not None \
        and cfg.collector.enable_external_sources:
    provider = build_search_provider(cfg.collector)
    if provider is not None:
        search_web_tool = lambda task: web_search_candidates(
            task, provider, llm, max_results=cfg.collector.search_max_results)
self._discoverer = CompetitorDiscoverer(llm=llm, use_llm=use_llm, web_tool=search_web_tool)
```
- Web/CLI/MCP 三入口都经 `CompetitorAnalysisAPI` 构造，**零入口改动自动受益**（无需在 web_app.py 单独传 web_tool）。
- 显式注入 `web_tool`（测试/评测 mock）仍优先，不覆盖。
- **`web_tools.py::web_search`（Lead/子 Agent 的搜索工具）同步接真实 provider**：非 stub，改调 `TavilySearchProvider.search` → 返回 `标题\nURL\n摘要` 文本供子 Agent 读（keep 契约：返回 str）。降级：无 Key/未启用 → 返回可读提示（行为与现状一致，不抛）。

### 3.2 报告路径由主 Agent 决策对齐（Q3 根因修复）

**结论先行**：架构**本来就该由主 Agent（Lead）决策路径**——doc 62 §3.5 统一 `run()` 单 Lead loop，`resolution` 仅是 querySource 标注，Lead 回合内自调 `web_search_candidates`→`delegate`→`aggregate_report` 自主决定走哪条路，`run()` 内**无分派 if-else**。本次"固定走单报告路径"是**工具失效导致的降级**，不是代码写死。真正缺口在 `_plan_resolution` 的**兜底推断**不尊重 `parsed.resolution`。

**改动 `facade/api.py::_plan_resolution`**（[api.py:429-448](file:///d:/trae_projects/first-agent/competitor_agent/facade/api.py#L429-L448)）：
```python
resolution = str((plan or {}).get("resolution") or "").lower()
if resolution:
    return resolution
if (plan or {}).get("competitors") or candidate_count > 0:
    return "discovery" if parsed.resolution == ResolutionDecision.DISCOVERY else "compare"
# 新增：parse_task（LLM）明确判为 COMPARE/DISCOVERY 时，即使 plan 缺字段也尊重
# 主 Agent 的意图 → 走 comparison 组装（空候选矩阵 + 提示优雅降级，不落 registry）
if parsed.resolution in (ResolutionDecision.COMPARE, ResolutionDecision.DISCOVERY):
    return parsed.resolution.value
return "registry"
```
- 效果：本案例 `parse_task` 判 COMPARE → 即便 `plan.competitor` 单值 + 零候选，也走 `ComparisonReport`（空矩阵 + Lead 市场格局核心结论段），而不是把"coding-agent-market"当单竞品出报告。
- 配合 3.1 真实搜索：Lead 能枚举候选 → `delegate` 候选子 Agent → `delegate_collector` 非空 → comparison 组装出真矩阵。**路径由主 Agent 决策，代码只守硬上限与兜底对齐**。

### 3.3 畸形 JSON 兜底补强（doc 65 遗留）

`_extract_json_block`/`_strip_json_blocks` 对 `"details": ,`（空值）与 `, , , , , ]`（空数组项）这类**模型手滑畸形**识别失败。补强（`facade/react_report.py`）：

1. **`_extract_json_block` 增加"轻修复 + 再解析"**：候选块 `json.loads` 失败时，尝试两条轻修复再试：
   - 正则去 `"([a-zA-Z_]+)":\s*,` → `"$1": null`（空值）；
   - 去 `,\s*,` / `,\s*]`（空数组项）→ `,` / `]`；
   - 修复后仍失败才放弃（保持"认不出就不删"的保守语义不变）。
2. **`_strip_json_blocks` 用同一判定**：把"是否 JSON"的判定收敛到共享 helper（`_looks_like_json_block(candidate)`：含 `"competitor"` 或 `"dimensions"` 键的平衡块即视为 JSON dump 剔除，即使 json.loads 失败）——**只对"像报告 JSON 的块"强制剔除**，普通散文花括号不受影响。

### 3.4 前端隐藏未关闭缺口

**决策**：`gaps_pending` 保留在数据模型（resume/预算/导出/归档照旧消费），但**默认渲染进 Markdown 的 `## 未关闭缺口` 段在前端不再展示**。

- 改动 `core/markdown_renderer.py::render`（[markdown_renderer.py:49-58](file:///d:/trae_projects/first-agent/competitor_agent/core/markdown_renderer.py#L49-L58)）：默认**不渲染** `## 未关闭缺口` 段（删掉该段或 `show_gaps: bool = False` 参数化，CLI 侧已有独立 `[提示] N 个缺口未关闭`（cli.py:58-59），不依赖 markdown 段）。
- 报告导出 JSON（`report_exporter.py:94` `gaps_pending`）与归档（`_archive_report`）**保持**，不破坏 resume/预算/记忆。
- 前端（`static/app.js::renderReport` 渲染 `markdown_report`）随之不再显示缺口段，无需改前端代码。

### 3.5 前端阶段事件 todo 化（叙述流与引擎内部标记分层）

**问题**：`_NARRATIVE_EVENTS`（web_app.py:73 = `{phase_start, phase_complete, progress}`）被 `_text_delta`（web_app.py:195）**无差别收敛为正文 text_delta 且不带 turn** → ① 多条引擎 phase 事件因 turn 全为 null 被前端合并到同一 `.text-seg` 挤成一行；② "开始 ReAct 推理"等引擎内部自证阶段对用户无信息价值，却污染正文打字机。

**目标形态（对照 Claude Code 等 agent 的 todo 清单）**：Lead 的**推进动作**以**独立任务清单行**呈现（`[✓/…] 委派 feature 子Agent / 收集 pricing 证据 / 枚举候选竞品…`），不再是正文文本；引擎内部无价值 phase 直接丢弃；真正有信息量的叙述（真实推理链）继续走带 `turn` 的 `thinking_delta`/`text_delta` 正文分段。

**改动（后端为主，前端适配）**：

1. **后端分层收敛**（`web_app.py::_event_generator`，web_app.py:254-265）：
   - **丢弃引擎内部无价值 phase**：`phase_start "开始 ReAct 推理"` / `phase_complete "ReAct 推理完成"` / `progress`（无 payload 语义的纯推进）**不再进 text_delta**（`_NARRATIVE_EVENTS` 收敛逻辑移除这两类，或按 `phase="react"` + 固定文案过滤）。
   - **有价值推进动作 → 新 `task` 事件**：把 Lead 的真实动作（如 `phase_start "Lead 编排: {task}"`、`discovery.candidate` 已有、可选的 delegate/collect 阶段）转换为**独立 `task` 事件**（复用 `ProgressEvent`，`event="task"`，payload `{message_id, task, status}`），供前端渲染为清单行。
2. **前端 todo 清单**（`static/app.js`）：新增 `addTaskLine(s, text, status)`——在 Lead 气泡工具区（`ensureTools`）下渲染一行 `[✓]/[…] 任务文案`（复用现有 `.tool` 样式或新增 `.task` 类，strike/dim 已完成项）；`task` 事件按 `payload.task` 追加/更新，`task` 完成态（`phase_complete` 对应任务）标记 `[✓]`。
3. **`_text_delta` 语义收窄**：只承载**真实 LLM 叙述**（`_stream_sink` 的 `thinking_delta`/`text_delta`，带 turn 走正文分段），不再承载引擎 phase 文案——挤行问题随根因消除。

**契约说明**：`_NARRATIVE_EVENTS` 收敛移除引擎 phase 会影响既有 `test_web_sse_events.py`/`test_web_m2_streaming.py` 断言（phase 收敛为 text_delta），需同步改为断言"引擎 phase 被丢弃 / `task` 事件承载推进动作"。

## 4. 数据流（改造后）

```
run("分析市面上常见 coding agent 对比")
 ├─ parse_task → COMPARE（LLM 决策）
 ├─ Lead ReactLoop：make_plan（resolution 可空）
 │    → web_search_candidates → Tavily.search → hits → LLM 归纳候选
 │    → delegate(targets=候选) → 候选子 Agent（web_search/web_extract 各自采集核验）
 │    → aggregate_report(parts=候选 dimensions[], kind="compare")
 │    → Final Answer：REPORT_SCHEMA JSON（多竞品维度结论段）
 ├─ _plan_resolution(plan, parsed=COMPARE) → "compare"（3.2 兜底对齐）
 └─ assemble_comparison → ComparisonReport（矩阵 + 市场格局核心结论）
```

## 5. 验证方式

- **单测 provider**（`tests/unit/collector/test_search_provider.py`）：mock `httpx.post`——200 正常映射 title/url/snippet、空 results、非 2xx 抛、超时抛、缺 Key `build_search_provider→None`、未知名/空名→None、tavily+Key→实例。
- **单测 MCP `web_search` 工具**：`test_tool_registry` 扩展——`TOOL_SPECS["web_search"]` 描述/schema 不变；mock provider 返回固定 hits → 工具输出"标题/URL/摘要"文本；无 provider（未启用）→ 返回可读提示；provider 抛异常 → 返回错误文案不冒泡（MCP 工具契约 str→str 保持）。
- **单测候选归纳**：mock provider 固定 hits + mock LLM → `web_search_candidates` 输出规范候选；hits 空→[]；LLM 畸形→空（不抛）。
- **单测 `_plan_resolution`**：COMPARE/DISCOVERY 缺 plan 字段→分别归 compare/discovery（新增断言）；registry+单值仍归 registry（回归）；candidate_count>0 行为不变。
- **单测畸形 JSON 兜底**：`"details": ,`、`{, , ]`、空项数组 → `_extract_json_block` 轻修复后仍解析；`_strip_json_blocks` 对含 `"dimensions"` 的畸形块剔除、对纯散文花括号保留（doc 65 用例扩展）。
- **单测渲染**：`MarkdownRenderer.render` 默认不含 `## 未关闭缺口`；`gaps_pending` 数据仍在报告对象/JSON 导出。
- **单测阶段事件 todo 化**：`test_web_sse_events.py`/`test_web_m2_streaming.py` 扩展——引擎 phase（"开始 ReAct 推理"/"ReAct 推理完成"）不再收敛为 text_delta（被丢弃）；`task` 事件承载 Lead 推进动作（含 message_id/task/status）；带 turn 的 `thinking_delta`/`text_delta` 仍走正文分段不回归；前端 `addTaskLine` 渲染 `[✓]/[…]` 清单行。
- **集成**：注入假 provider（固定候选）→ `run()` 产出 `ComparisonReport` 而非单竞品；未配 Key/主开关关 → 行为与现状一致（降级不编造）。
- **回归**：全量 unit suite 绿（含 doc 65 的 40 新用例不回归）；ruff/mypy 改动文件干净。

## 6. 实现优先级与工作量

- 优先级：**高**（DISCOVERY/COMPARE 当前因搜索 stub 不可用；Tavily key 已配置被浪费）。
- 工作量：约 0.5-1 天。
  - `collector/search.py` + 配置 + `.env.example`：0.3 天；
  - `api.py` 装配 + `_plan_resolution` 对齐 + `web_search` 接真实：0.2 天；
  - 畸形 JSON 轻修复（`react_report.py`）：0.1 天；
  - 渲染隐藏缺口：0.05 天；
  - 阶段事件 todo 化（web_app.py 收敛分层 + app.js `addTaskLine` + 测试适配）：0.15 天；
  - 测试：0.2 天。
- 前置依赖：用户已提供 TAVILY_API_KEY（playground 可验证）；httpx 已是硬依赖。

## 核心技术点总结

- **Tavily 真实接入**：`POST https://api.tavily.com/search` + `Authorization: Bearer`；Key 只读环境变量 `TAVILY_API_KEY` 不落盘；`enable_external_sources` 主开关门控；无 Key/失败降级返回空不编造（守 doc 47）。
- **MCP 工具同源**：`web_search` 本就注册在 `TOOL_SPECS`（MCP/ReAct 共用，doc 40 契约），仅需替换 stub 实现为真实 Tavily 调用——MCP Client 与 ReAct 子 Agent 自动同源受益，schema/描述零改动。
- **路径决策归主 Agent**：`run()` 本就单 Lead loop 无分派；补 `_plan_resolution` 兜底尊重 `parsed.resolution`——COMPARE/DISCOVERY 意图即使 plan 缺字段也走 comparison 组装。
- **畸形 JSON 兜底**：轻修复（空值/空数组项）+ "像报告 JSON 就剔除"判定，杜绝 `{...}`/`[...]` 进报告正文（doc 65 补完）。
- **前端不展示缺口**：markdown 渲染层默认移除 `## 未关闭缺口` 段，数据模型/导出/归档保留。
- **阶段事件 todo 化**：引擎 phase 不再无差别收敛为正文 text_delta——无价值内部阶段丢弃，Lead 推进动作改 `task` 清单行（`[✓]/[…]`），带 turn 的真实推理链继续正文分段；消除"编排文案挤行"根因。
