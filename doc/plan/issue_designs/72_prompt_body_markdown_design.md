# 设计文档 72 —— 第二十二轮：`Agent.md`——类 CLAUDE.md 的全局提示词资产（可编辑项目级指令）

> 第二十二轮。目标：新增一份**全局 `Agent.md`**，作用对标 Claude Code 的 **CLAUDE.md**——随仓库版本管理、
> 用户可编辑、作为**项目级常驻指令/偏好**注入到每个 Agent（Lead / 维度子 Agent / 候选竞品子 Agent /
> 对话分支）的 system 上下文，让"加入项目级引导"不再需要改代码。
>
> 本文档为**设计**（暂不实现）。实现方向以 §6 接口、§7 注入时序、§9 实施计划为准。
>
> **归档依据**：沿用 `doc/plan/issue_designs/` 系列既有归档方式（`咱编号_design.md` 命名、
> 第 X 轮 header blockquote、分节含「问题现状 / 总体架构 / 接口设计 / 配置清单 / 测试验收 /
> 实施计划 / 风险权衡 / 核心技术点总结」、`README.md` 索引登记），格式模板参考 **doc 71**。
>
> **实现说明（2026-08-30，P1+P2 一次落地）**：`agent/prompts/loader.py` 新增 `PromptAsset`
> （复用 skills 的 frontmatter/reload 模式：`render("Agent", context)` 做 `{{key}}` 逐键替换、
> `get`/`version`、`PROMPTS_DIR`/`PROMPTS_USER_FILE`（扩展 B）env 覆盖、`get_prompt_asset`
> 单例 + 显式目录绕过缓存、`reset_prompt_asset`）；`assets/Agent.md` 内置资产（frontmatter
> version 1.0.0，正文含项目背景/语气风格/工具公约/禁止项/已知事实清单）；`react_system.py`
> 新增 `_agent_md_section()`（缺/坏/异常→空串、行数上限 Warning、字符硬截断 `_MAX_AGENT_MD_CHARS`、
> 版本漂移 Warning）+ `_with_agent_md()` 接入 **Lead / 对话 / 维度子 Agent / 候选竞品子 Agent**
> 四个 build_* 尾部（空段时输出逐字节不变 → 黄金回归）；`enrich_prompt` 尾拼记忆/知识库在
> Agent.md 之后（§4 顺序）；与 doc 71 §8.4 阶段二（make_plan 后 plan 适配段）正交。测试
> `tests/unit/agent/test_prompt_72.py` 25 条（存在/注入/降级回归/覆盖/用户文件/替换/有界/漂移/
> 阶段二正交）；顺带修正 skills 计数断言 9→10 并随附补提交 doc 71 §8.5 漏提交的
> `skills/comparison_reasoning.md`。全量 unit 1085 passed / integration+e2e 61 / benchmark 门禁
> 全过（field_accuracy=1.0 / hallucination=0 / tool_selection=0.9091 与基线一致）/ ruff+mypy 干净。
>
> **核心澄清**：`Agent.md` ≠ 替换角色角色提示词。它是**加在既有 system prompt 之上的一层
> "项目级上下文"**（CLAUDE.md 语义）：既有角色提示（`build_lead_system_prompt()` 等）仍是
> 引导位，`Agent.md` 作为**有界的补充段**在每次运行的**最早处**并入第一条 system 消息。
> 何时并入 + 现有 system prompt 如何生效，见 §1.2 与 §4。

---

## 0. 设计依据：为什么需要一份"整体 Agent.md"

现状"改项目级引导"要动 Python；而项目**已有** skills md 资产先例（`skills/*.md`），却没有一份
能表达"项目整体想要 Agent 怎么做"的常驻文件。CLAUDE.md 的价值正在于此：**项目偏好/公约/已知事实
一份可版本化的 md，随运行注入 context，用户随手改**。本项目缺口：

| 目标 | 现状 | 差距 |
|---|---|---|
| 项目级引导（品牌语气/报告偏好/工具使用公约/禁止项） | 硬编码散在 `react_system.py` | 改一句要改 code |
| 全 Agent 共享（Lead + 各子 Agent + 对话） | 只有 `build_*_system_prompt` 各写各的 | 无统一"项目上下文"注入点 |
| 用户/运维可编辑 | ❌ | 缺 CLAUDE.md 式资产 |
| 与 skills（领域技能）分离 | skills 已分离 | 缺"项目公约层"（更靠近 Charter/CLAUDE） |

**已核实事实（不臆测，均读文件）**：现有 system prompt 是 `react_system.py` 的 Python 函数拼出
字符串，经 `facade/api.py:891`(`build_lead_system_prompt`)、`api.py:1050`、`api.py:1808`
(`build_chat_system_prompt`) 装配，作为 `system_prompt_override` 传给 `ReactLoop` → 进 `ReactAgent`
第一条 `{role:"system"}` 消息；skills 已是 md（`skills/*.md`，`SKILLS_DIR` 可覆盖），`enrich_prompt`
把记忆/知识库拼在尾部；doc 71 §8.4 新增"make_plan 后按 plan 中途注入阶段二 system 段"。

---

## 1. 问题现状

### 1.1 现有 system prompt 是怎么起作用的（本设计的前置现状）

```
api.py:891   分析分支 → build_lead_system_prompt()      # react_system.py:84 返回一长串 str
api.py:1808  对话分支 → build_chat_system_prompt()       # react_system.py:125
  └ 内部：身份 + plan-first + 委派 + COMPARE + 两段式      # f-string 硬编码；L121 拼 _web_tool_section
           + _with_skills(...) 内联 skills/*.md          # L122；记忆/知识库由 enrich_prompt 尾拼
  ↓ 作为 system_prompt_override 传入
ReactLoop.run_with_result (react_loop.py:106)
  → agent.build_system_prompt(instructions=override, notes=记忆, knowledge=知识库)
  → 整段作为第一条 {role:"system"}                        # react_agent.py:177
  → LLMClient.complete_with_tools(messages, tools, ...)  # 每次推理都带这段 system
  └ 中途：doc 71 §8.4 —— make_plan 工具命中后，ReactLoop._on_plan 按 plan 再注入
    "报告结构/对比推理" 第二条 system 段（react_agent.py splice）
```

**要点**：现有 system prompt = **循环开始前一次性构建 → 进第一条 system 消息 → 该会话每次
LLM 调用都带着它**；动态调整靠两处——构建时按配置（`_web_tool_section` 选版、skills/记忆注入），
与循环中按 plan（阶段二注入）。它**不是从 md 读的**，是代码生成的字符串。

### 1.2 Agent.md 要补的"空位"

上述链路里，**没有一处表达"整个项目希望 Agent 遵守的公约/偏好"**——那部分被揉进了
`build_lead_system_prompt` 的硬编码叙事（品牌、报告风格、禁止项）。`Agent.md` 就是要把这层
抽出来做成**全局、有界、可编辑、全 Agent 共享**的资产，在 §1.1 的**构建时点**并入。

---

## 2. 总体架构

```
                        （每次运行的最早期：build system prompt 时）
                 ┌──────────────────────────────────────────────┐
                 │  build_*_system_prompt()    ← 既有角色引导（代码）  │
                 │     +   load agent_md → render("Agent", {})      │
                 │        → 产出 ≤N 行的"Agent.md（项目级指令）"段      │
                 │  ↓ 合并为一条 {role:"system"}                      │
   Agent.md ──────►  [system: 角色引导\n\nAgent.md 段（有界/末尾）]   │
  (全局常驻)      │  → ReactAgent._run_native 第一条 system 消息       │
                 │  → 每次 complete_with_tools 都携带                 │
                 └──────────────────────────────────────────────┘
  覆盖/注入源：  PROMPTS_DIR（env，仿 SKILLS_DIR）;  PROMPTS_USER_FILE（可选扩展 B，用户偏爱）
```

**Agent.md 的定位**（明确分层，防与角色提示/技能混淆）：
- 角色提示（`build_lead_system_prompt` 等）= 该意图的**宪章/引导位**（不进 Agent.md）；
- `Agent.md` = **项目级常驻指令/偏好**（进 Agent.md）：语气、报告风格偏好、工具使用公约、
  禁止项、仓库已知事实/清单、升级约定——CLAUDE.md 语义；
- skills（`skills/*.md`）= 领域专项技能（`{{skills}}`/`_with_skills`，已有，不并入 Agent.md）。

---

## 3. Agent.md 内容构成（类 CLAUDE.md）

```markdown
# Agent.md —— 项目级 Agent 指令（CLAUDE.md 语义，全 Agent 注入）
---
name: Agent
version: 1.0.0
description: 项目级常驻指令/偏好（语气/报告风格/工具公约/禁止项/已知事实）
---
## 项目背景
本项目是竞品情报分析 Agent…（1–3 句）

## 语气与风格
- 中文、简洁、直接；结论先行。          ← 报告风格偏好

## 工具使用公约
- 事实性数值（价格/版本/榜单）须经 web 核验，不得凭印象下结论。
- 遵守 doc 71 联网两步法（摘要充足不 fetch）。

## 禁止项
- 不得编造证据 URL；不得把未核验细节当已知。

## 已知事实 / 清单（可选，随项目演进）
- 竞品规范名 / 官网 / 定价页：如 Cursor、Windsurf…
- 常用数据源有效性备注（可引 skills）
```

长度**有界**（建议 ≤ 40 行，超出 Warning），避免像"把整本说明书塞 system"那样稀释注意力。

---

## 4. 注入时序——Agent.md 在什么时候加入主流程（本设计的关键回答）

| 阶段 | 时点 | Agent.md 是否参与 |
|---|---|---|
| **构建期（每次运行最早期）** | `build_*_system_prompt()` 时，与角色引导一起 `render("Agent", …)` | ✅ **ADDED——进第一条 system 消息**（Lead/子 Agent/对话都加） |
| **循环内（首轮前）** | `ReactAgent._run_native` 组装 `messages` | 已含在第一条 system，不重复注入 |
| **循环中（make_plan 后）** | doc 71 §8.4 阶段二 | ❌ 不介入（那是按 plan 的任务适配段，与项目常驻指令正交） |
| **记忆/知识库** | `enrich_prompt`（尾拼） | Agent.md 在其**之前**（常驻在前、动态记忆在后） |
| **跨轮次/多轮会话** | 每轮带同一 system 消息 | ✅ 天然持久，历史回灌不丢失 |

**结论**：Agent.md 在**每次运行的 system-prompt 构建期**并入，进**第一条** system 消息，**对
每个 Agent（Lead/子 Agent/对话）生效、贯穿该次运行全部 LLM 调用**；它不依赖 plan、不在循环中
中途注入（与阶段二正交）。会话内改文件不影响当前会话，**下次运行/新会话生效**（CLAUDE.md 同语义）。

---

## 5. 接口设计

```python
# agent/prompts/loader.py（复用 skills.loader：frontmatter + reload + env 覆盖）
class PromptAsset:
    def render(self, stem: str, context: dict[str, str] | None = None) -> str: ...   # {{key}} 逐键替换
    def get(self, stem: str) -> str | None: ...
    def version(self, stem: str) -> str | None: ...
get_prompt_asset() -> PromptAsset

# 注入点：react_system.py 各 build_* 开头统一叠一层
def _agent_md_section() -> str:
    tpl = get_prompt_asset()
    body = tpl.render("Agent") if tpl else ""          # 缺失/异常 → 空串（不炸）
    return body[:MAX_AGENT_MD_CHARS]                   # 有界，防膨胀
```
各 `build_lead/chat/subagent_system_prompt` 返回前 `return f"{主体}…\n\n{_agent_md_section()}"`
（空串时无附加，现状逐字节不变 → 黄金回归安全）。可选扩展 B：`PROMPTS_USER_FILE` 指向用户 md，
串在 `_agent_md_section()` 之后（追加"个人偏爱"层，默认关）。

---

## 6. 配置清单

| 项 | 说明 |
|---|---|
| `agent/prompts/assets/Agent.md` | 内置全局资产（进包，版本管理） |
| `PROMPTS_DIR`（env） | 覆盖资产目录（仿 `SKILLS_DIR`）；未设读包内 |
| `PROMPTS_USER_FILE`（env，可选扩展 B） | 用户级 md，渲染后追加为偏爱段 |
| `frontmatter.version` | 资产版本，漂移 Warning |

---

## 7. 测试与验收

| 路径 | 预期 |
|---|---|
| Agent.md 存在/parse/有界 | frontmatter 完整；>40 行 Warning |
| 注入后 Lead/子 Agent/对话输出**尾部**含 Agent.md 段 | 三段 build_* 都带该段 |
| 缺 assets / 渲染异常 / 空 Agent.md | `_agent_md_section()` 返回 ""，build_* 输出=现状（黄金回归） |
| PROMPTS_DIR 覆盖 | 改 Agent.md → build_* 输出随之变（证明"改 md 生效"） |
| 与阶段二正交 | make_plan 后注入的是 plan 适配段，不含重复 Agent.md |

---

## 8. 实施计划

| 阶段 | 内容 | 预计 |
|---|---|---|
| P1 最小 | `PromptAsset` 渲染器 + `assets/Agent.md` + `_agent_md_section` 接入 4 个 build_* | 1 天 |
| P2 覆盖/扩展 B | `PROMPTS_DIR` + `PROMPTS_USER_FILE` + 有界/漂移 Warning + 测试 | 0.5 天 |

总 **1.5 天**；P1 即达成"类 CLAUDE.md 可编辑资产"，产出可独立验证。

---

## 9. 风险与权衡

| # | 风险 | 兜底 |
|---|---|---|
| 1 | Agent.md 与角色引导/技能重复 | 明确分层（§2）；只放项目级公约 |
| 2 | 无界膨胀挤占 context | 强制行数/字符上限 + Warning |
| 3 | 用户改坏 md | 渲染 try/except → 空串/回退现状 |
| 4 | 与阶段二/记忆拼接顺序 | 固定顺序：角色+Agent.md｜记忆｜(阶段二独立) |
| 5 | 与"主体 md 化"目标的边界 | Agent.md 是**追加层**（CLAUDE.md 语义），角色**主体模板化**为另项扩展（本 doc 不展开，留 §10 尾注） |

---

## 10. 核心技术点总结

- **新增全局 `Agent.md`**（CLAUDE.md 语义）：项目级常驻指令/偏好，可编辑、可版本化、全 Agent 注入。
- **注入时点**：每次运行的 **system-prompt 构建期**并入第一条 system 消息 → 贯穿该次所有 LLM 调用、
  跨轮次天然持久；与按 plan 的阶段二适配正交。
- **分层不重复**：角色提示=宪章引导位，`Agent.md`=项目约定层，skills=领域技能，三者叠加不互相污染。
- **降级/有界**：缺/坏/空 → 空串（现状逐字节不变，黄金回归安全）；行数上限防膨胀。
- **复用资产机制**：`PromptAsset` 复用 skills 的 frontmatter/reload + `PROMPTS_DIR` 覆盖；
  `PROMPTS_USER_FILE` 提供可选"个人偏爱"追加层。

> **尾注**：本 doc 聚焦"整体 Agent.md（追加层，CLAUDE.md 语义）"。角色角色**主体 md 化**（把
> `build_lead/chat/*` 的硬编码叙事迁成 `lead.md/chat.md/…` 模板）是另一方向的扩展，与 Agent.md
> 互补可并存，按需另立 doc。