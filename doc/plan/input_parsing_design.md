# 用户输入解析与处理设计文档（input_parsing_design.md）

> 对照 hermes-agent 的"用户输入解析与处理"逻辑，梳理 competitor_agent 现状差距，
> 设计一套**统一入口 → 命令识别 → 浅清洗 → 任务语义解析 → API 执行**的输入管线。
> 本设计对应 `implementation_plan.md` 的 **M5 里程碑**。

---

## 1. 设计背景

### 1.1 hermes-agent 的输入处理逻辑（参考基准）

hermes-agent 是一个"AI Agent Runner"，其对用户输入的处理遵循以下四层结构：

1. **多入口归一化**：CLI（prompt_toolkit `TextArea`，`cli.py:14244`）、Web（xterm → `/api/pty` WebSocket → PTY → TUI，`web_server.py:15484`）、聊天平台（Telegram 等，`MessageEvent`，`gateway/platforms/base.py:1739`）各自读取原始输入，最终统一为内部消息 Schema `{"role":"user","content": str}`（`agent/turn_context.py:317`）。
2. **斜杠命令识别（唯一的结构化解析）**：不靠 regex 匹配命令名，只做前缀判定 `_looks_like_slash_command()`（`cli.py:3531`，排除 `/Users/...` 类文件路径），命令名经注册表 `COMMAND_REGISTRY`（`commands.py:64`，约 90 个 `CommandDef`）→ `resolve_command()`（`commands.py:275`）查表解析；参数由各 handler 自行 `split` 剥离。
3. **自由文本浅清洗 + 原样透传**：非命令文本不做语法树解析，只做粘贴包装剥离、终端泄漏剥离、`[Pasted text]`/`@file:` 引用展开（`cli.py:15216`/`15278`）、代理字符清理 `_sanitize_surrogates`（`turn_context.py:205`），然后原样交给 LLM。
4. **会话与恢复**：`conversation_history` 维护多轮，`-c/--continue` 恢复会话、`-z/--oneshot` 单发（`oneshot.py:425`）、`-q/--query` 单查询。

> **核心认知**：hermes-agent **不"提取"用户意图**——程序只做命令识别与浅层清洗，意图提取交给 LLM。

### 1.2 competitor_agent 现状（差距分析）

| 维度 | hermes-agent | competitor_agent 现状 | 差距 |
|------|-------------|----------------------|------|
| 入口 | CLI / Web / 平台归一化 | 仅 Web（`web_app.py:262`）、MCP（`mcp_server`）、编程（`api.analyze(task)`） | **无 CLI**（usage.md 写了 `python -m competitor_agent.cli` 但 `cli.py` 不存在） |
| 命令 | 斜杠命令注册表 | 无 | **无命令系统**（无法 `/history`、`/compare`、`/benchmark` 快捷触发） |
| 清洗 | 粘贴/终端泄漏/引用展开/代理字符 | 无 | **无输入净化**（提示注入防御只做展示层，无入站清洗） |
| 语义解析 | 交给 LLM；规则兜底 | `resolve_competitor()` 子串匹配 + `_build_gaps()` 关键词提权 | **解析过浅**：对比任务（`对比 A 和 B`）、维度限定（`只分析定价`）、自定义数据源均不支持 |
| 会话 | conversation_history + resume/oneshot | checkpoint 断点续跑（已有）但无交互式会话历史 | **无交互式多轮输入** |

---

## 2. 设计目标

对照 hermes-agent 四层逻辑，为 competitor_agent 补齐 **M5 输入解析与处理层**：

1. **补齐 CLI 入口**（`competitor_agent/cli.py`），与 usage.md 文档对齐，支持交互与非交互两种模式。
2. **命令注册表**：`/analyze`、`/compare`、`/history`、`/resume`、`/benchmark`、`/help` 等斜杠命令，识别逻辑沿用 hermes 的"前缀判定 + 注册表查表"。
3. **入站浅清洗**：剥离粘贴包装/终端泄漏，展开 `@file:`、`[Pasted text #N]` 引用，清理代理字符（复用 `Interfaces 防护层`）。
4. **任务语义解析增强**：保持"LLM 优先 + 规则降级"（与架构 `5.2` 一致），规则版支持对比任务、维度限定、自定义数据源。
5. **交互式会话**：`conversation_history` 支持多轮追问（如"再对比下 Windsurf"补全上下文）。

---

## 3. 目标架构

```
                        ┌──────────────────────────────┐
                        │  入口层（统一归一化到 TaskText） │
                        │  CLI(新) / Web / MCP / 编程     │
                        └──────────────┬───────────────┘
                                       │ 原始用户文本
                                       ▼
                        ┌──────────────────────────────┐
                        │  command_dispatch(新)         │
                        │  _looks_like_slash_command    │
                        │  → 命中? → CommandRegistry    │
                        └──────────────┬───────────────┘
                                       │ 非命令 → 浅清洗
                                       ▼
                        ┌──────────────────────────────┐
                        │  input_sanitizer(新)          │
                        │  粘贴/泄漏剥离 · @file 展开    │
                        │  surrogate 清理               │
                        └──────────────┬───────────────┘
                                       │ 清洗后任务文本
                                       ▼
                        ┌──────────────────────────────┐
                        │  task_parser(新/增强)          │
                        │  resolve_competitor(增强)     │
                        │  dimension 限定 · 对比拆分    │
                        │  LLM 优先 / 规则降级           │
                        └──────────────┬───────────────┘
                                       │ CompetitorStrategy
                                       ▼
                        ┌──────────────────────────────┐
                        │  CompetitorAnalysisAPI        │
                        │  analyze / compare / history  │
                        │  resume（会话历史挂载）         │
                        └──────────────────────────────┘
```

**数据流**：入口原始文本 → 命令判定（命中则走命令处理器）→ 浅清洗 → 任务解析（产出 CompetitorStrategy）→ API 执行。命令识别与语义解析解耦，与 hermes-agent 一致。

---

## 4. 对照 hermes-agent 的模块映射

| hermes-agent 组件 | 位置 | competitor_agent 对应（M5 新增） |
|-------------------|------|----------------------------------|
| REPL 输入控件 | `cli.py:14244` TextArea | `competitor_agent/cli.py`（新增，prompt_toolkit 可选，先 argparse + `input()`） |
| 斜杠命令判定 | `cli.py:3531` `_looks_like_slash_command` | `core/command_registry.py` 的 `_looks_like_slash_command()`（新增） |
| 命令注册表 | `commands.py:64` COMMAND_REGISTRY | `core/command_registry.py` 的 `CommandDef` + `resolve_command()`（新增） |
| 入站清洗 | `cli.py:15216`、`turn_context.py:205` | `core/input_sanitizer.py`（新增：`strip_paste_wrappers` / `expand_references` / `sanitize_surrogates`） |
| 任务语义解析 | 交给 LLM（无规则层） | `core/task_parser.py`（新增）：`parse_task()`，LLM 优先 + 规则降级 |
| 竞品识别 | — | `core/competitor_registry.py:49 resolve_competitor()`（增强：对比拆分） |
| 会话历史 | `cli.py:12221` conversation_history | `facade/api.py` 新增 `conversation_history` 参数 + `continue_analysis()` |
| 单发/恢复 | `oneshot.py:425`、`-c/--continue` | `cli.py` `-z/--oneshot`、`-c/--continue` 参数（新增） |

---

## 5. 模块设计

### 5.1 CLI 入口（`competitor_agent/cli.py`，新增）

对照 usage.md 已承诺的接口补齐实现：

```
python -m competitor_agent.cli analyze "Claude Code"
python -m competitor_agent.cli analyze "对比 Cursor 和 Windsurf" --out reports/
python -m competitor_agent.cli history --competitor cursor
python -m competitor_agent.cli benchmark
python -m competitor_agent.cli -z "分析 Cursor"          # oneshot，脚本化
python -m competitor_agent.cli -c session_id              # 恢复最近/指定会话
```

- `main(argv)`：argparse 顶层分发（`analyze/history/benchmark` 子命令 + `-z/-c` 全局 flag）。
- 交互模式（无子命令时）：`input()` REPL，维护 `conversation_history`，斜杠命令经 `command_dispatch()` 路由。
- 非交互模式：直接构造 `CompetitorAnalysisAPI` 并 `analyze()`。

### 5.2 命令注册表（`core/command_registry.py`，新增）

```python
class CommandDef:
    name: str                # 命令名（不含 /）
    aliases: list[str]       # 别名
    handler: str             # 处理器标识，如 "analyze" / "history" / "benchmark"
    args_hint: str           # tab 补全/帮助用参数提示，如 "[competitor] [--out DIR]"

COMMAND_REGISTRY: list[CommandDef] = [
    CommandDef("analyze",   ["a"], "analyze",  "[competitor]"),
    CommandDef("compare",   ["c"], "compare",  "A 和 B"),
    CommandDef("history",   ["h"], "history",  "[--competitor X]"),
    CommandDef("resume",    ["r"], "resume",   "[session_id]"),
    CommandDef("benchmark", ["b"], "benchmark", ""),
    CommandDef("help",      ["?"], "help",     "[command]"),
]

def _looks_like_slash_command(text: str) -> bool:
    """前缀判定：以 / 开头且首词不含第二个 /（排除 /Users/foo 类路径）"""
    ...

def resolve_command(name: str) -> CommandDef | None:
    """lstrip('/') + 注册表查表（name + aliases）"""
    ...
```

- 识别逻辑照搬 hermes `_looks_like_slash_command` 的"前缀 + 排除路径"做法，不写命令名 regex。
- `command_dispatch(text, ctx) -> bool`：命中命令返回 True 并执行处理器；否则返回 False 走浅清洗 + 任务解析。

### 5.3 入站浅清洗（`core/input_sanitizer.py`，新增）

对照 hermes `cli.py:15216-15218` / `15278` / `turn_context.py:205`：

```python
def strip_paste_wrappers(text: str) -> str:      # 剥离 [Pasted text #N] / 粘贴包装
def strip_terminal_leaks(text: str) -> str:      # 剥离终端响应泄漏（^[[0m 等）
def expand_references(text: str) -> str:         # @file:path → 读文件内容嵌入
def sanitize_surrogates(text: str) -> str:       # 代理字符清理，防 json 序列化崩溃
def sanitize_task(task: str) -> str:             # 组合调用上述全部
```

- `sanitize_surrogates` 必须放在入站最早处，避免后续 `json.dumps` 崩溃（hermes `turn_context.py:205` 的教训）。
- `expand_references` 支持 `@file:reports/foo.md` 将本地文件内容作为分析上下文嵌入。
- 同时承载提示注入的**入站净化**（架构 `R16` 三层防御的第一层，当前仅有展示层，需前置到管线）。

### 5.4 任务语义解析（`core/task_parser.py`，新增 + 增强 `strategic_loop.py`）

**保持"LLM 优先 + 规则降级"**，与架构 `5.2`、`llm/client.py` 现有能力一致：

```python
class TaskParseResult:
    competitors: list[str]        # 1 个 = 单竞品，2 个 = 对比
    dimensions: list[str] | None  # None = 全部维度；["pricing"] = 只分析定价
    custom_sources: dict[str, str]  # 维度 → 自定义 URL（@url: 引用）
    raw_task: str                 # 保留原文（进会话历史 / checkpoint）

def parse_task(task: str, llm: LLMClient | None = None,
               use_llm: bool = False) -> TaskParseResult:
    """LLM 优先解析 → 规则降级（resolve_competitor + 关键词提权）"""
```

- **规则版增强 `resolve_competitor()`**（`competitor_registry.py:49`）：
  - 对比拆分：识别 `对比 A 和 B` / `A vs B` / `A 与 B`，返回两个竞品（注册表内直接命中，未注册竞品各走 ASCII 提取）。
  - 维度限定：识别 `只分析定价` / `重点看性能和定价` 等（复用 `strategic_loop._FOCUS_KEYWORDS`，扩展为产出 `dimensions` 白名单）。
  - 自定义源：识别 `官网是 https://...` / `定价页 https://...` → `custom_sources`，注入 `InfoGap.sources_tried` 前置。
- **LLM 版**：当 `use_llm=True` 且 LLMClient 可用时，用一次轻量调用解析上述结构；解析失败或 LLM 不可用时回退规则版（不崩溃，沿用 M1 fallback 精神）。
- `strategic_loop.plan()` 改为接收 `TaskParseResult`（保持 `plan(task)` 签名向后兼容，内部先 `parse_task`）。

### 5.5 会话历史与恢复（`facade/api.py`，增强）

对照 hermes `conversation_history`：

- `analyze(task, conversation_history: list[ChatMessage] | None = None)`：传入则把上轮 `competitor/gaps 摘要` 拼入上下文，支持多轮追问（"再对比下 Windsurf" 能引用上一轮的 Cursor）。
- `compare(a: str, b: str) -> CompetitorReport`：新方法，直接构造两个竞品的对比策略（内部复用 `parse_task` 的对比拆分）。
- `continue_analysis(session_id) -> CompetitorReport`：复用现有 `checkpoint.resume()`，补齐 hermes `-c/--continue` 语义。
- `get_history()` 已有（M4），CLI `/history` 直接调用。

---

## 6. 验证方式（M5 出口条件）

| 能力 | 验证 | 通过标准 |
|------|------|---------|
| CLI 补齐 | `python -m competitor_agent.cli analyze "Claude Code"` | 输出 Markdown 报告，exit 0 |
| 命令注册表 | 单测 `_looks_like_slash_command` + `resolve_command` | 前缀判定/别名/路径排除 3 分支覆盖 |
| 浅清洗 | 单测 `sanitize_task` | 粘贴包装剥离、@file 展开、surrogate 清理各一例 |
| 对比解析 | `parse_task("对比 Cursor 和 Windsurf")` | 返回 2 个竞品 |
| 维度限定 | `parse_task("只分析 Cursor 定价")` | dimensions=["pricing"] |
| 会话历史 | 单测：两次 analyze 带 history | 第二轮的 Context 含第一轮摘要 |
| 回归 | `pytest` 全量 + `ruff` + `mypy` | 0 失败（新 CLI/解析器需 80% 覆盖率） |

---

## 7. 实施清单（对应 implementation_plan.md M5 步骤）

| # | 任务 | 交付物 |
|---|------|--------|
| 5.1 | CLI 入口补齐 | `competitor_agent/cli.py`（argparse + 交互 REPL + `-z/-c`） |
| 5.2 | 命令注册表 | `core/command_registry.py`（CommandDef + `_looks_like_slash_command` + `resolve_command` + `command_dispatch`） |
| 5.3 | 入站浅清洗 | `core/input_sanitizer.py`（strip_paste/leaks + expand_references + sanitize_surrogates） |
| 5.4 | 任务语义解析 | `core/task_parser.py` + 增强 `competitor_registry.py` / `strategic_loop.py`（对比/维度限定/自定义源） |
| 5.5 | 会话历史与恢复 | `facade/api.py`（conversation_history + `compare()` + `continue_analysis()`） |
| 5.6 | 测试补全 | `tests/unit/core/test_command_registry.py` + `test_input_sanitizer.py` + `test_task_parser.py` + `tests/unit/facade/test_api_history.py` |
| 5.7 | 文档收口 | usage.md CLI 章节与实现对齐、api.md 补 `compare/continue_analysis`、本设计文档落定 |

---

## 8. 设计决策记录

1. **命令识别不写 regex**：沿用 hermes "前缀判定 + 注册表查表"，命令名集中管理，新增命令只加一个 `CommandDef`。
2. **清洗在命令判定之后**：斜杠命令先路由（hermes 同款顺序），非命令文本才做 `sanitize_task`，避免破坏命令参数。
3. **LLM 优先、规则兜底**：任务语义解析不因 LLM 缺失而崩，延续 M1 已验证的 fallback 路径。
4. **向后兼容**：`analyze(task)` 签名不变，新增参数全部可选；`strategic_loop.plan()` 保持旧签名。
5. **不引入第三方 CLI 框架**：argparse + `input()` 足够，避免依赖膨胀；若后续需要补全体验再评估 prompt_toolkit。
