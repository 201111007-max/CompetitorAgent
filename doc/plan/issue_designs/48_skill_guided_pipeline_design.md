# 设计文档 48 — 写死代码知识型规则 → skill 化，主体流程 LLM 驱动

> 触发：2026-08-17 评审——设计文档 47 后主路径"想"的部分（解析/规划/分析）已全部走 LLM，
> 但"知识/规范"仍以 Python 字符串常量与硬编码规则写在代码里（维度抽取要求、事实边界、置信度披露、
> 规划规范）。参考 Dota2-Agent（`D:\trae_projects\Dota2-Agent`）的 skill 机制——`.skills/*.md`
> （YAML frontmatter + 正文规范）经 `SkillLoader`（`utils/skill_loader.py`）两层注入 LLM prompt——
> 决策：**把"知识型"写死内容抽为 skill 文档注入 LLM，主体流程由 LLM 驱动；"保证型"逻辑（安全/路由/校验/
> 仲裁/聚合/阈值）保留为代码兜底不改**。仅涉及写死代码部分，已走 LLM 的部分（`parse_task`/`plan`/`analyze`
> 的调用结构与次数）不修改。
>
> 前置：设计文档 47（主路径单轨 LLM，无规则降级）；44（链式分析 `_analyze_with_llm`/`_base_messages` 已存在）。
> 参考实现：Dota2-Agent `utils/skill_loader.py`（frontmatter 解析 + `get_descriptions`/`get_content`）。

## 1. 问题现状

- 主路径已 LLM 化，但"领域知识"仍固化在 Python 字符串/字典里，改一个提示词、一条事实边界都要改代码并跑全量回归：

| 层 | 位置 | 硬编码知识内容 | 类型 |
|---|---|---|---|
| 规划 | `core/strategic_loop.py:52` `_PLAN_PROMPT` | 维度选择规则、priorities/budget/custom_sources 格式 | 知识 |
| 分析-维度 | 6 个分析器 `_build_prompt`（`pricing_analyzer.py:72` / `feature_analyzer.py:18` / `performance_analyzer.py` / `ecosystem_analyzer.py` / `sentiment_analyzer.py` / `roadmap_analyzer.py`） | "你是竞品X分析师…输出 JSON…不要编造…" 抽取规范 | 知识 |
| 分析-事实边界 | `analyzers/base.py:80` `_count_numeric_conflicts`（数值回溯原文核对） | "声称自原文的数字应在原文中找到"——**代码校验** | 保证 |
| 分析-补证查询 | `analyzers/base.py:36` `_DIMENSION_VERIFY_QUERIES` | 维度 → web_search 关键词 | 知识 |
| 校验-披露 | `team/validator_agent.py:46` `FactValidator`（`min_confidence=0.3`、`CLOSED_CONFIDENCE`） | 低置信告警、结论披露约束 | 保证+知识 |
| 选源 | `collector/source_selector.py:17/_GAP_TO_KINDS:28` | 维度 → 链接 key / 源 kind 路由表 | 保证（确定性） |

- **问题**：知识（该怎么做、不该说什么）与机制（校验、路由、阈值）混在代码里，无法独立演进；
  主体流程名义上 LLM 驱动，但"正确性规范"实际由代码硬编码约束，LLM 只填空。
- **不变量**：本次**不触碰已走 LLM 的部分**（`parse_task`/`plan`/`analyze` 的调用结构、次数、schema、
  `complete_json` 修复重试）；**不触碰保证型逻辑**（注入防护、选源路由、降级链、真值校验兜底、仲裁阈值、
  聚合权重、渲染、checkpoint/预算/取消）。

## 2. 目标设计

1. **知识型写死内容 → skill 文档**：新增 `competitor_agent/skills/*.md`（YAML frontmatter：name/description），
   把"规划规范、各维度抽取规范、事实边界指导、置信度披露"抽为可编辑 skill，运行时经 `SkillLoader` 注入 LLM prompt。
2. **主体流程 LLM 驱动**：skill 是给 LLM 的决策/表达规范（指导性），LLM 在既有骨架内按 skill 行事；
   代码只保留结构（JSON schema）、机制（校验/路由/阈值）与安全兜底。
3. **保证型逻辑保持代码兜底**：真值校验的**核对动作**、注入检测、选源路由、仲裁、聚合仍由代码强制执行，
   skill 只承载"规范/披露"指导，两者叠加（skill 指导 + 代码兜底）。
4. **确定性不回归**：skill 注入不改变 LLM 调用次数与 prompt 中"用户任务"、观察文本的段结构，
   `BenchmarkMockLLM` 的确定性抽取不受影响，benchmark 门禁与 891 全量测试保持。

## 3. 模块/接口设计

### 3.1 新增 `competitor_agent/skills/` 包

```
competitor_agent/skills/
├─ __init__.py        # 导出 SkillLoader / get_skill_loader（单例）
├─ loader.py          # SkillLoader（仿 dota-agent utils/skill_loader.py）
├─ planning.md            # name: planning            规划规范
├─ pricing_analysis.md    # name: pricing_analysis    定价抽取规范
├─ feature_analysis.md    # name: feature_analysis    功能抽取规范
├─ performance_analysis.md# name: performance_analysis 性能/榜单规范
├─ ecosystem_analysis.md  # name: ecosystem_analysis  生态抽取规范
├─ sentiment_analysis.md  # name: sentiment_analysis  口碑抽取规范
├─ roadmap_analysis.md    # name: roadmap_analysis    路线图抽取规范
├─ fact_verification.md   # name: fact_verification   真值/事实边界指导
└─ confidence_disclosure.md# name: confidence_disclosure 样本量/置信度披露
```

```python
class SkillLoader:
    def __init__(self, skills_dir: Path | None = None) -> None:  # 缺省读包内 skills/
    def reload(self) -> None: ...
    @staticmethod
    def _parse_frontmatter(text: str) -> tuple[dict[str, str], str]: ...  # 兼容 dota-agent 解析
    def get_descriptions(self) -> str: ...   # 一层：name + description 清单
    def get_content(self, name: str) -> str: ...  # 二层：<skill name="...">body</skill>
    def get(self, name: str) -> str | None: ...   # 直接取正文（缺失 None）
```

- frontmatter 解析、`get_descriptions`/`get_content` 语义与 Dota2-Agent `utils/skill_loader.py:15` 对齐；
- 目录可经环境变量 `SKILLS_DIR` 覆盖（测试/评测注入确定性内容）；
- 文件缺失/解析失败 → `get()` 返回 `None`，注入点静默跳过（不影响主流程）。

### 3.2 注入点（只加注入，不改调用结构）

- **`analyzers/base.py::_base_messages`**：组装子类 `_build_prompt` 之后，注入
  `<skill name="{self.dimension.value}_analysis">` + `<skill name="fact_verification">` + `<skill name="confidence_disclosure">`
  三个块（追加为一条 system 或并入末条 user 之前；skill 块**不含**"用户任务"/观察文本，不影响 mock 抽取段）。
  - 子类 `_build_prompt` 的 system 文案保留为"你是竞品X分析师"骨架（schema 契约仍在代码 `_details_properties`）。
- **`core/strategic_loop.py::_plan_messages`**：注入 `<skill name="planning">`。
- **可选（默认不做）**：`task_parser` 的 `_LLM_PARSE_PROMPT` 已走 LLM 且属"其余已用 LLM 部分"，
  本设计**不修改**，留作后续。

### 3.3 skill 文档内容规范（正文模板）

```markdown
---
name: <skill_name>
description: <触发/适用场景一句话>
---
<适用条件>
## 抽取/分析规范    （该维度要产出哪些字段、格式）
## 事实边界          （能说什么/不能编造什么/不确定怎么写）
## 披露约束          （低置信/样本不足如何标注）
## 推荐输出结构      （summary/details 形态）
```

- 各维度 skill 正文内容源自现有各 `_build_prompt` 的抽取要求 + 现有 `_details_properties` 的字段说明，
  **逐步平移**：先注入 skill（与代码 prompt 并存），后续版本再把 `_build_prompt` 内重复文案收敛为 skill 引用
  （本期不删 `_build_prompt` 文案，降低回归风险，见 §4.3）。
- `fact_verification`：来源自 `_count_numeric_conflicts` 的语义（"声称自原文的数值应能回溯原文；不能回溯时
  降低置信、标注无法核实"）——作为 LLM 自检指导；**代码核对动作保留**（`_verify_details` 仍是兜底强制执行）。
- `confidence_disclosure`：来源自 `FactValidator`/`CLOSED_CONFIDENCE` 的披露语义（低置信标注、局限性小节）——
  作为 LLM 表达指导；**阈值判定保留在代码**。

### 3.4 不宜改（保持代码，明确清单）

| 项 | 位置 | 理由 |
|---|---|---|
| 注入防护 | `agent/prompts/trust_boundary.py` `detect_injection`/`wrap_untrusted` + `base.py:204` 命中短路 | 安全，不能交给 LLM |
| 选源路由 | `source_selector.py:17/_GAP_TO_KINDS:28`、SPA 兜底 | 确定性：benchmark 门禁 tool_sel=0.9091 依赖固定路由的 mock oracle |
| 降级链/预算/取消/checkpoint | `gap_executor.py:121`、`budget.py`、`checkpoint.py`、`orchestrator.py:200` | 编排机制，非知识 |
| 真值校验动作 | `base.py:80 _count_numeric_conflicts`/`_verify_details`/`_VERIFY_NUMERIC_KEYS` | 强制兜底（LLM 不保证自觉遵守 skill） |
| 链式停止 | `base.py:47 _UNHELPFUL_TOOL_MARKERS`、`_needs_verification`/`_MAX_CHAIN_STEPS` | 防 stub/错误当证据、防无限循环 |
| 仲裁/校验阈值 | `validator_agent.py:46` `FactValidator`（`min_confidence`/证据 trust/冲突）、`arbitrate:115` | 正确性保证 |
| 聚合/渲染 | `report_builder.py:16 _DIMENSION_WEIGHTS`/`_aggregate`、`markdown_renderer` | 确定性输出 |
| schema 修复重试 | `llm/client.py:284 complete_json` | 健壮性 |
| 名称规范化 | `competitor_registry.py` `canonicalize`/`resolve_competitor` | 数据 |
| 结构化抽取 | `pricing_analyzer.py` `_parse_plan`/`_detect_tier`/`_estimate_costs` 等 | schema 归一化，非分析知识 |

## 4. 接入方式

### 4.1 SkillLoader 生命周期

- `competitor_agent/skills/__init__.py` 暴露模块级单例 `get_skill_loader()`（懒加载 + 缓存）；
- `SkillLoader` 构造时 `reload()` 读包内 `skills/*.md`；`SKILLS_DIR` 环境变量覆盖目录（测试注入用）；
- 注入点调用 `get_skill_loader().get(name)`，返回 `None` 则跳过（零依赖降级）。

### 4.2 prompt 段结构不变（mock 确定性保证）

- `BenchmarkMockLLM`（`evaluation/benchmark.py:193`）的确定性抽取只依赖两段：
  ① 解析/规划 prompt 的"用户任务：<task>"段（`_infer_competitor`，`benchmark.py:302`）；
  ② 分析 prompt 中 `wrap_untrusted(observation.raw_text...)` 的页面内容块（按维度抽取）。
- skill 块以 `<skill name="...">` 独立追加，不进入上述两段 → mock 抽取不受影响；
- 新增 `tests/evaluation/test_skill_injection.py`：断言注入后 mock 全量门禁仍过（字段 1.0/幻觉 0/工具选择 ≥0.85/trace 100%）。

### 4.3 测试处理（先不动断言，做最小适配）

| 类别 | 处理 |
|---|---|
| 新增 | `tests/unit/skills/test_skill_loader.py`（frontmatter 解析、`get`/`get_content`/缺失降级、SKILLS_DIR 覆盖、reload）；`tests/evaluation/test_skill_injection.py`（注入后门禁） |
| 新增 | 注入点测试：分析器 `_base_messages` 含 `<skill name="pricing_analysis">`/`fact_verification`；规划 prompt 含 `planning`；skill 缺失不注入 |
| 回归 | 全量 `pytest`（891）——若个别断言锁定 system 文案的测试（如 `test_trust_boundary.py` 对 `_build_prompt` 的断言）不受影响，因为注入点在 `_base_messages` 层、`_build_prompt` 不变 |
| benchmark | mock 全量门禁回归不变（§4.2） |

### 4.4 文档收口

- README / `docs/usage.md` / `docs/evaluation_guide.md`：补"skills 目录 + 环境变量 SKILLS_DIR"；
- `implementation_plan.md`：登记设计文档 48；
- 本文件在 `issue_designs/README.md` 索引登记（实施完成后标 ✅）。

## 5. 验证方式

- **单测（新增）**：`SkillLoader` frontmatter 解析/缺失/覆盖目录/reload；注入点含/不含 skill 两种路径；
  `BenchmarkMockLLM` 门禁在注入后不变。
- **集成**：`mock_llm` fixture 下跑通 `analyze` 全链路，报告维度齐全、prompt 含 skill 块。
- **回归**：全量 `pytest`（891 passed / 2 skipped / 1 环境性）通过；benchmark 门禁不变；mypy 不新增错误。
- **实测**：有 Key 环境 `analyze("Claude Code")` 出报告；对比注入前后一次分析的 LLM 调用次数**不变**。

## 6. 实现优先级与工作量

| 阶段 | 内容 | 预计 |
|---|---|---|
| P0 | `skills/loader.py` + 9 个 skill md（规划 1 + 维度 6 + fact_verification + confidence_disclosure） | 0.5 天 |
| P1 | 注入点：`base.py::_base_messages` + `strategic_loop.py::_plan_messages`（skill 块追加，不删现有文案） | 0.5 天 |
| P2 | 新增 2 个测试文件 + 全量回归 + 文档收口 | 0.5 天 |

- 依赖：47（主路径单轨 LLM）、44（`_base_messages`/链式结构）。
- 风险：skill 文案与现有 `_build_prompt` 提示词语义不一致 → LLM 行为漂移。缓解：本期**保留** `_build_prompt`
  原文案，skill 只追加不替换，先观察注入收益；后续再收敛去重。
- 范围外（不修改）：`task_parser` 提示词、ReAct 路径、已走 LLM 的调用结构。
