# 设计文档 20 — 自主发现竞品 + 多竞品并排对比

> 对应 `implementation_plan.md` §13（P0，用户已确认，待办）

## 1. 问题现状

- 用户实测输入「帮我寻找现在市场上所有的ai coding agent并进行分析」→ 报告 0 维度。
- 根因链（`core/competitor_registry.py`）：
  1. `resolve_competitor(name)` 要求用户输入**具体竞品名**：先子串匹配注册表（`claude-code` / `cursor` / `copilot` / `codex`），不中则 exact 规范化匹配，再退化为 ASCII 提取把整句话拼成假竞品 `ai-coding-agent`。
  2. 假竞品无 `official_links` → `SourceSelector.candidates()` 0 候选 → 6 缺口全 BLOCKED → 0 维度。
- 对比能力仅两两：`facade/api.py` 的 `compare(self, a, b=None)`，`ComparisonReport` 数据模型已支持 `competitors: list[Competitor]`，但 `_build_comparison_markdown()` 只产"维度 × 置信度"两列表，无 N 向矩阵、无每维度最佳/汇总视图。
- `resolve_competitors()` / `TaskParseResult.competitors` 已支持 list（≤2），但**无"市场普查/发现"意图分支**，N≥3 无路径。
- `parse_task()` 已有 LLM-first 分支，但 LLM 只做竞品名归一化，**从未输出"该搜索还是该匹配注册表"的决策**——意图判断缺位，只能靠规则拼装。

## 2. 目标设计

1. **解析决策交给 Agent（LLM）**：走"联网搜索"还是"按名称匹配注册表"，由 Agent 用 LLM 判断，而不是代码用关键词启发式（`is_discovery_task`）猜测意图。LLM 在解析任务时输出结构化决策（`REGISTRY` / `DISCOVERY` / `COMPARE`），或通过工具调用（ReAct 的 Thought→Action）自主选择"注册表查询"或"联网搜索"工具。
2. **自主搜索发现竞品**：LLM 判定为普查/发现意图时，Agent 联网检索（Web 搜索 / MCP `web` / `github` / `review` 工具）枚举候选竞品清单（名称 + 官网），再逐个分析，而非把整句拼成假竞品导致 0 维度。
3. **N 向并排对比**：一次传入 ≥2 个竞品，产出"品类格局矩阵"（维度 × 竞品表 + 每维度最佳/汇总），而非仅 A vs B。
4. **规则降级兜底**：无 LLM Key / 网络不可用时，退化为当前规则解析（关键词启发式 + 内置兜底清单），保证不 0 维度——但这是**降级路径**，不是主决策。

## 3. 模块/接口设计

### 3.1 解析决策（LLM 驱动，主路径）+ 竞品发现器

**核心原则：意图判断由 Agent/LLM 做，代码只做兜底。** 决策来源二选一（推荐 3.1-a，工具调用形态的 3.1-b 作为增强）：

#### 3.1-a 结构化决策（主路径）：`parse_task` LLM-first 扩展

`core/task_parser.py` 的 `parse_task(task, llm, use_llm=True)` 已是 LLM-first。扩展其 LLM 输出 schema，增加 `resolution` 字段：

```python
class ResolutionDecision(str, Enum):
    REGISTRY = "registry"    # 任务点名具体竞品 → 按名称匹配注册表（不联网）
    DISCOVERY = "discovery"  # 任务为市场普查/发现（"所有 X""有哪些"） → 联网搜索枚举候选
    COMPARE = "compare"      # 任务点名 ≥2 个竞品 → N 向对比

@dataclass
class TaskParseResult:
    competitors: list[str]
    dimensions: list[str] | None = None
    custom_sources: dict[str, str] = field(default_factory=dict)
    raw_task: str = ""
    resolution: ResolutionDecision = ResolutionDecision.REGISTRY   # ← LLM 决定
    is_discovery: bool = False                                     # = resolution == DISCOVERY（派生）
```

- LLM 依据任务语义决定 `resolution`；同一次调用里也可让它顺带归一化竞品名（"Cursor 和 Windsurf"→ `["Cursor","Windsurf"]`，N 不设上限）。
- **代码不再用关键词硬判意图**；`is_discovery` 只是 LLM 决策的派生字段，供编排层路由用。

#### 3.1-b 工具调用决策（增强）：`react_agent` / 编排层

复用现有 ReAct 层（`agent/react_agent.py` + `tool_dispatcher`），把"解析决策"建模为工具选择：

```
Tools:
  registry_lookup(name)   → 按名称匹配注册表，返回 Competitor 或 not_found
  web_search_competitors(task) → 联网检索候选竞品清单（名称+官网）

Agent 决策链：LLM 读任务 → 判断走 registry_lookup（点名具体竞品）还是
web_search_competitors（普查/发现）→ 按结果继续逐个分析。
```

- 工具实现与 3.1-a 的 `CompetitorDiscoverer` 底层复用同一检索逻辑。

#### 3.1-c 发现器 `core/competitor_discoverer.py`（底层能力，不含意图判定）

```python
class CompetitorDiscoverer:
    def __init__(self, llm: LLMClient | None = None, use_llm: bool = True,
                 web_tool: Callable[[str], list[dict]] | None = None) -> None: ...

    def discover(self, task: str) -> list[Competitor]:
        """联网检索候选竞品列表（名称 + official_links）。仅当 LLM 已判定 DISCOVERY 时被调用。
        1) 注册表命中优先；
        2) 未知 → 调用 web_tool / MCP 搜索（名称、主页/定价/文档链接），
           use_llm=True 时用 LLM 归纳去重、补全 official_links；
        3) 返回 list[Competitor]（≥1，去重）。
        """
```

- **职责边界**：`CompetitorDiscoverer` 只负责"怎么找"，**不负责"该不该找"**；"该不该找"由 LLM 决策（3.1-a/b）。
- `web_tool` 注入点：默认走 `mcp_server` 的 `web_extract` / `github_stars`（复用现有 MCP 工具），测试注入 mock（设计文档 11 的 `FakeExtractor` 模式）。
- 无 Key / 无网络时规则版可枚举注册表内置候选 + 常见 AI coding agent 静态清单（硬编码兜底，保证不 0 维度）。

### 3.2 解析与规划改造

- `core/competitor_registry.py`：`resolve_competitors()` 保持"按名称匹配"，不塞意图分支；当编排层拿到 `resolution == DISCOVERY` 时才改走 `discover()`（N 不设上限）。
- `core/task_parser.py`：`TaskParseResult` 增 `resolution` / `is_discovery`（见 3.1-a）；**LLM-first 是主路径，规则版 `_parse_task_rule` 仅作无 Key 降级**（此时 `resolution` 由弱启发式推断）。
- `core/strategic_loop.py`：`plan()` 保持单竞品，N 向 / 发现场景由上层（`api.py`）对每个竞品各规划一次（复用现有 `analyze` 单竞品路径），无需新 `MultiCompetitorStrategy`。

### 3.3 N 向对比 `facade/api.py`

```python
def compare(self, *competitors: str) -> ComparisonReport:
    """接受 ≥2 个竞品（原 compare(a, b=None) 保留签名兼容，委托本方法）。"""
```

- 逐个 `self.analyze(name, mode=...)`（复用现有单竞品流水线，含记忆/取消/并行）。
- `ComparisonReport` 已有 `competitors: list[Competitor]` + `reports: list[CompetitorReport]`，直接复用数据模型。

### 3.4 品类格局矩阵渲染

- `core/report_builder.py` 新增 `build_comparison(reports: list[CompetitorReport]) -> ComparisonReport`（聚合维度并集、每维度置信度表、每维度最佳/最差、缺失维度标注 N/A）。
- `core/markdown_renderer.py` 新增 `render_comparison(report: ComparisonReport) -> str`：
  - **品类格局矩阵**：`| 维度 | 竞品A | 竞品B | ... | 最佳 |`
  - **每维度最佳**：按置信度 + 状态（`[OK]` > `[PARTIAL]` > `[N/A]`）排序给出最佳竞品与一句话摘要。
  - **汇总视图**：整体置信度排名 + 维度覆盖缺口汇总。

### 3.5 Web 前端多竞品输入（`web_app.py`）

- 输入框支持逗号 / 换行 / 顿号分隔多个竞品；「开始分析」把多竞品任务转发到 `compare(*names)`。
- 普查类任务（"所有 AI coding agent"）提示"将自动发现竞品并逐个分析"，SSE 事件带 `discovery` 阶段（候选清单可实时推送）。

## 4. 接入方式

```
parse_task(task)  ← LLM 决定 resolution（3.1-a 结构化输出；无 Key → 3.1-a 降级规则）
  ├─ REGISTRY（点名具体竞品）  → 现有 analyze() 路径（不变）
  ├─ COMPARE（≥2 名）          → compare(*names) → 逐个 analyze → build_comparison → render_comparison
  └─ DISCOVERY（普查/发现）    → CompetitorDiscoverer.discover(task) → 候选 list[Competitor]
                                     → 逐个 analyze → 合并为品类格局报告
增强（3.1-b）：react_agent 以工具调用决策（registry_lookup vs web_search_competitors）
```

- `CompetitorDiscoverer` 在 `CompetitorAnalysisAPI.__init__` 装配（可注入 `web_tool` / `llm`），与 `config`、`memory` 同层。
- `api.analyze()` 依据 `TaskParseResult.resolution` 路由（`is_discovery` 派生），避免 0 维度回归。
- 编排层把 `resolution` 与 `discover` 过程作为事件发到日志（呼应 §14 埋点：`task.parsed` 含 `resolution`、`discovery.candidates`）。

## 5. 验证方式

- **单测（LLM 决策）**：mock LLM 返回 `resolution=DISCOVERY` → `parse_task` 产出 `is_discovery=True`，编排路由到 `discover()`；mock LLM 返回 `REGISTRY` → 走注册表匹配且**不触发** `web_tool`；返回 `COMPARE` 且 3 个竞品名 → `competitors` 长度 3。
- **单测（决策 schema 鲁棒性）**：LLM 输出畸形 / 字段缺失 → 安全 fallback 到规则解析，不抛异常；规则版对"所有 AI coding agent"负例 → `resolution=DISCOVERY`（无 Key 降级）。
- **单测（发现器）**：mock `web_tool` 返回 N 个候选 → `discover()` 返回去重列表；"所有 AI coding agent"不再产出 `ai-coding-agent`；无 Key 走静态兜底清单。
- **单测（矩阵渲染）**：构造 3 份 mock `CompetitorReport` → `render_comparison` 产出含"维度 × 竞品"表 + 每维度最佳；缺失维度标 N/A。
- **集成**：`compare("Cursor", "Claude Code", "Copilot", "Codex")` 产出 ≥4 列品类矩阵；普查任务（mock LLM 决策 DISCOVERY + mock 搜索）产出真实候选而非 0 维度。
- **端到端**：Web 输入多竞品 / 普查任务，SSE 流含 `discovery` + `report` 事件，页面展示矩阵视图。
- **回归**：`tests/unit/core/test_competitor_registry.py` / `test_task_parser.py` / `tests/unit/facade/` 全绿；单竞品 `analyze` 行为不变；`use_llm=False` 全链路不触发真实网络。

## 6. 实现优先级与工作量

- 优先级：**高**（P0，用户明确诉求；0 维度是体验致命伤）。
- 工作量：约 4 天。
  - `TaskParseResult.resolution` + LLM 决策 schema + 降级规则：1-1.5 天；
  - 发现器 `CompetitorDiscoverer` + 兜底清单：1 天；
  - N 向 compare + 矩阵渲染：1-1.5 天；
  - Web 多竞品输入 + discovery 事件：0.5 天；
  - 测试（LLM 决策 / 发现器 / 集成 / e2e）：0.5 天（随上并行）。
- 前置依赖：第 12.1 #1（扩 `SourceSelector` 路由）可增强发现后的采集质量，但不阻塞本项；复用设计文档 11 的测试基础设施（`FakeExtractor` / `mock_llm`）；LLM 决策依赖 `LLMClient`（DeepSeek 已配置）。
