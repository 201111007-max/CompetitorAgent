# 设计文档 44 — LLM 智力深度浅（单轮补全 + 规则化规划）

> 触发：2026-08-15 第三轮评审——分析器每个维度只做**一次 `complete_json` 抽取**（summary/details/confidence），
> 无多步推理、无迭代改进、无工具查证；规划器 `StrategicPlanner.plan` 基本是规则（`DIMENSION_PRIORITY` +
> `_FOCUS_KEYWORDS` 提权 + `_allocate_budget` 静态配比），LLM 只用于一次 `parse_task` 识别竞品/维度
> （core/task_parser.py:149）。agentic 程度 ≈ "包原文 → 抽一次 JSON"。
> 依赖：设计文档 34（`complete_json` + JSON Schema 约束 + 修复重试）、36（LLM 可靠性）、40（多工具可查证）；
> 与 43（主路径归属）互补——43 解决"在哪用"，44 解决"怎么用得更深"。

## 1. 问题现状

- **分析器单轮**：`BaseCompetitorAnalyzer._analyze_with_llm`（analyzers/base.py:138-165）＝ `_build_prompt` →
  注入 RAG/记忆 → 一次 `complete_json` → `_verify_details` 数值核对 → `_make_result`。无"抽取→校验→复核→修正"
  的迭代；无工具调用（拿不到页面外的数字/证据时只能靠原文或 RAG）。
- **规划规则化**：`StrategicPlanner.plan`（core/strategic_loop.py:67-81）＝ 规则解析竞品（注册表/ASCII）+ 固定
  6 维度优先级 + 关键词提权 + 静态预算分配（feature 3/pricing 2/...）；LLM 仅在 `parse_task` 做一次
  `llm.complete`（task_parser.py:149），且 `use_llm=False` 时纯规则。
- **影响**：复杂任务（多轮追问、交叉核验、需要联网查证的最新数字）答不上；"agent 会自主规划/多步推理"无实现支撑。

## 2. 目标设计

1. **链式分析**：LLM 先抽取 → 真值校验（已有 `_verify_details`）→ 置信度不足/冲突时经工具补证（`web_extract`/
   `web_search`，复用 40 的 dispatcher）→ 二次补全收敛；上限 2-3 步，规则兜底。
2. **规划 LLM 化**：任务 → 竞品 → 缺口清单 → 预算分配 全链路由 LLM 决策（结构化输出），规则为降级；
   LLM 规划结果复用现有 `CompetitorStrategy` 契约，旧调用零改动。
3. **结构化约束复用**：规划/分析均走 `complete_json`（34 的 schema + 修复重试 + 36 的多模型 fallback）。

## 3. 模块/接口设计

### 3.1 链式分析（`analyzers/base.py`）

```python
class BaseCompetitorAnalyzer:
    _MAX_CHAIN_STEPS = 2
    def _analyze_with_llm(self, observation, gap, context) -> DimensionResult:
        parsed = self._llm.complete_json(self._build_prompt(...), schema=self._schema_for(gap))
        for _ in range(self._MAX_CHAIN_STEPS):
            if not self._needs_verification(parsed, observation):   # 数值核对 + 置信度
                break
            evidence = self._verify_via_tools(gap, context)          # dispatcher web_extract/search
            if not evidence:
                break
            parsed = self._llm.complete_json(
                self._build_prompt(..., extra_evidence=evidence), schema=self._schema_for(gap))
        return self._make_result(...)
```

- `_needs_verification`：`_verify_details` 冲突 > 0 或 `confidence < 阈值` 或 details 关键键为空。
- `_verify_via_tools`：复用 `build_react_dispatcher`（40）做一次目标抓取/搜索，失败静默返回 `""`（不破坏降级）。
- 规则路径（`_analyze_with_rules`）与无 LLM 环境完全不变（回归安全）。

### 3.2 规划 LLM 化（`core/strategic_loop.py` / `interfaces/planner.py`）

```python
class StrategicPlanner:
    def plan(self, task, memory=None) -> CompetitorStrategy:
        if self._use_llm and self._llm is not None:
            parsed = self._llm.complete_json(             # 结构化：competitor/dimensions/priorities/budget
                [{"role": "user", "content": plan_prompt(task, memory_context)}],
                schema=PLAN_SCHEMA)
            return self._strategy_from_llm(parsed, memory)   # 复用 _apply_memory_boost
        return self._plan_with_rules(task, memory)           # 现状规则路径
```

- `PLAN_SCHEMA`：competitor（string）/ dimensions（array，枚举 6 维）/ budget（object，维度→次数）/
  custom_sources（object，可选）。
- `_strategy_from_llm` 校验枚举合法、budget 兜底（缺失维度给默认 1），非法输入回退规则路径。

## 4. 接入方式

```
analyze → StrategicPlanner.plan（LLM 结构化 ／ 规则降级）
       → 缺口闭环 → Analyzer._analyze_with_llm（抽取 → 校验 → 工具补证 → 二次补全）
                                     │（无 LLM / 失败 → _analyze_with_rules 原样）
所有产物仍为 CompetitorStrategy / DimensionResult，下游（采集/报告/评测）零改动
```

- 与 43 的关系：44 的"工具补证"依赖 40 的多工具 dispatcher 已就绪；43 把分析阶段整体迁到 ReAct 时，44 的链式
  可作为 ReAct 循环的"单缺口闭环"实现，两者可选其一先落地。

## 5. 验证方式

- **单测（链式）**：mock LLM 首轮返回数值与原文冲突（`_verify_details` 下调置信）→ 触发工具补证 → 二轮修正后
  通过；`_MAX_CHAIN_STEPS` 后仍冲突 → 保留降级置信不无限循环。
- **单测（规划）**：mock LLM 返回含非法枚举/budget 缺失 → 兜底回退；`use_llm=False` 纯规则结果与现状一致。
- **回归**：既有 `test_strategic_loop.py`/`test_analyzers.py`/评测（mock 下）全绿；规则路径行为不变。

## 6. 实现优先级与工作量

- 优先级：**中**（"会自主规划/多步推理"是 agent 卖点，但当前报告正确性已有保障，属深度增强）。
- 工作量：约 1-1.5 天。
  - 链式分析（校验触发 + 工具补证 + 二次补全）：0.6 天；
  - 规划 LLM 化（PLAN_SCHEMA + 兜底）：0.4 天；
  - 测试：0.3 天。
- 前置：34（结构化）、40（多工具）；可并行 43。低风险，规则路径全程兜底。
