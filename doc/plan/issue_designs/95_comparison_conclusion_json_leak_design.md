# 设计文档 95 —— 第四十五轮：市场格局核心结论段泄漏原始 JSON（ ComparisonReport 走 writer 通道）

> 第四十五轮。来源：2026-09-17 web 实测排查（doc88 步骤 7 两段式退役后的真实模型回归）。
> 用户在 web 前端报告面板看到「## 市场格局核心结论」段落内容为 JSON 形态的结构化垃圾
> （原始 JSON 文本或 `{'matrix': ...}` Python dict repr），而非 prose 结论。
>
> **用户已选定 方案 B：结论走 writer 通道**（writer LLM pass 从结构化事实生成
> prose，不再依赖 Lead Final Answer 契约）。方案 A（`_extract_conclusion` 加固）/
> 方案 C（prompt 契约强化 + 自修复重试）不实施。
>
> **✅ 已实施（2026-09-17）**：与 §3 设计的偏差有两处——① doc78 服务拆分后接线点
> 实为 ``compare_service._finalize_comparison_report``（非 analysis_service），
> ``_emit_report_skeleton`` 同步上提 ServiceBase 供两路径共用；② ``lead_answer``
> 参数整体删除（组装层零消费，签名清理）。prompt 侧 ``react_system.py`` 与
> ``aggregate_tool.py`` 的 conclusion 字段契约同步退役。全量 tests 1731 passed
> （含 2 个 discovery 优雅降级用例改钉代码提示文案）、ruff/mypy 清。

---

## 1. 现象

- web 前端 ComparisonReport 报告面板的「## 市场格局核心结论」段展示的不是市场格局
  prose 结论，而是 JSON 形态文本（两种形态）：
  - 原始 comparison JSON 正文（带 `{`/`"` 的结构化文本）；
  - `{'competitors': [...], 'matrix': ...}` 风格的 Python dict 字符串（单引号）。
- 后端日志/trace 层面无任何告警——组装全程"成功"，垃圾文本静默进入报告正文并落库
  （`save_report_markdown`）与 SSE `report` 事件（前端渲染）。

## 2. 根因

结论提取唯一入口 `facade/comparison_report.py::_extract_conclusion`（doc 88 步骤 7
【市场格局核心结论】marker 字符串契约删除后，结论统一取 comparison JSON
`conclusion` 字段）。三条路径：

```
Lead Final Answer → _extract_json_block（括号配平提取）
  ├─ dict 且 payload["conclusion"] 非空 → str(conclusion)          （正常路径）
  ├─ dict 但无 conclusion 字段 → ""（矩阵兜底，§assemble 不拼结论段）
  └─ 非 dict（解析失败）→ return 整段原文                          （缺陷入口）
```

**路径 A（解析失败 → 原文兜底）**：`comparison_report.py:118-123`。设计意图是
"真实 LLM 未遵约时不丢结论"（宁可展示原文也不丢内容），但 doc88 两段式退役后
Lead Final Answer **默认就是 JSON**（react_system.py:210"以 comparison JSON 作
Final Answer"）——模型输出的 JSON 只要带尾逗号/未引号键/嵌套超限/`_extract_json_block`
括号配平失败等任一瑕疵，整段 JSON 原文就被兜底进「市场格局核心结论」段。
**契约越强，兜底越容易把结构化垃圾当 prose 展示**——这是 doc88 副作用。

**路径 B（conclusion 字段类型未约束）**：`comparison_report.py:120-121`。
契约只说"conclusion 字段写市场格局核心结论"，未约束其为字符串。模型输出
`"conclusion": {"summary": ..., "winner": ...}`（嵌套对象）时，`str(payload["conclusion"])`
产出 Python dict repr（单引号形态），即用户看到的第二种形态。

两路径均无校验、无日志——静默降级，与 doc 52 §2.2"消除静默降级"原则相悖。

**结构性根源**：doc88 的 writer 体系（`facade/writer_pass.py`：蒸馏事实 → 三槽
切分 → 逐槽 LLM prose + N2 数字保真校验 + N3 引用锚定 → 注入骨架）只覆盖
**单竞品 CompetitorReport**（`_finalize_competitor_report` 汇聚点触发）；
ComparisonReport（compare/discovery）组装是**纯代码执行层、不经 LLM**
（`comparison_report.py` 模块 docstring），结论段只能靠解析 Lead Final Answer——
契约烂一路烂。

## 3. 方案（已选定 B）：comparison 结论段接入 writer 体系

原则：**「## 市场格局核心结论」段的唯一合法来源 = writer LLM 从蒸馏事实生成的
prose**。Lead 的 comparison JSON conclusion 字段从报告链路退役；解析兜底
（`_extract_conclusion` 路径 A/B）随之整体删除——垃圾无入口，而非出口过滤。

### 3.1 改动点

1. **`facade/comparison_report.py`**：`assemble_comparison` 删除 `conclusion =
   _extract_conclusion(lead_answer)` 与结论段追加分支（§83-97）；`lead_answer`
   参数保留（矩阵排序等暂不用则一并清理签名，以实际引用为准）。`_extract_conclusion`
   函数删除，其单测同步退役。
2. **`facade/writer_pass.py` 新增 `maybe_run_comparison_writer_pass(comparison,
   *, llm, stream_sink, config, on_skeleton)`**：
   - 事实蒸馏：对 `comparison.reports`（每候选最小 CompetitorReport）逐个
     `distill_report` → `DimensionFacts`，**competitor 名并入事实载荷**
     （facts payload 增 `competitor` 字段，writer 依据它写"谁在何维度领先"）；
   - 单槽 `NarrativeSlot(slot_id=SLOT_CONCLUSION, heading="市场格局核心结论",
     input_facts=全部候选维度事实)`，复用既有 `_write_slot`（N2 数字保真重试、
     N3 引用锚定、降级注记语义原样继承；`slot_allowed_numbers` 口径不变）；
   - `build_writer_messages` 增 comparison 形态：system 指令改为"维度 × 竞品
     横向格局结论（谁在何维度最优/整体胜负/替代关系）"，其余硬性规则（只依据
     facts/禁 URL 年份/[n] 占位/字数）不动；
   - 注入：prose 成功 → `comparison.markdown_report` 追加
     「## 市场格局核心结论」段（幂等：已有该标题则跳过）；prose 为 None
     （writer 关闭/LLM 异常/N2 两败/零候选）→ **不追加任何结论段**——矩阵自身
     说话，绝不回退到解析 Lead 文本。
3. **`facade/analysis_service.py::_finalize_comparison_report`**：`assemble_comparison`
   之后、落盘/返回之前调用 `maybe_run_comparison_writer_pass`（单竞品路径的
   `maybe_run_writer_pass` 同位汇聚点；`llm/stream_sink/config` 取自现有依赖，
   `on_skeleton` 透传给 SSE `report_skeleton` 事件可选）。
4. **配置**：沿用 doc88 `report.writer_pass` 总开关（默认 false，行为面零变化）；
   开启时 comparison 路径同步生效。成本 +1 次 LLM 调用/对比报告（与单竞品路径
   一槽位同量级）。
5. **零候选**：无 reports → 无事实 → 槽位跳过，保持 `_ZERO_CANDIDATE_HINT`
   现状（与结论段正交）。

### 3.2 明确不做的

- 不修 `_extract_conclusion` 的解析健壮性（随函数一起退役）；
- 不把 Lead comparison JSON conclusion 作为 writer 输入（其可能含 facts 之外的
  数字/URL，注入即破坏 N2 允许集口径）——react_system.py:210 的"conclusion 字段"
  提示语同步删除，避免模型做无用功；
- 不引入第二轮结论修复重试（方案 C）。

## 4. 测试验收

- `tests/unit/facade/test_comparison_report_70.py` 重构：
  - 删除 `_extract_conclusion` 既有用例（marker/JSON 解析语义已退役）；
  - 新增：`prose_override` 直注 → 结论段为注入 prose；conclusion 为 dict /
    Final Answer 为烂 JSON → **报告正文无任何 JSON 泄漏**（回归核心用例）；
    writer 关闭/异常 → 无结论段、矩阵完好；
- `tests/unit/agent/test_writer_slots.py`：comparison 形态 messages
  （competitor 字段入 payload、横向格局指令）；
- `tests/unit/facade/test_writer_pass.py`：`maybe_run_comparison_writer_pass`
  降级三形态（整体异常/单槽失败/N2 两败）均不追加结论段；
- 真实 LLM 回归：Tavily Key 恢复后跑一轮 discovery，人工核验结论段为 prose 且
  数字与矩阵一致（N2）。

实施补充（2026-09-17）：另适配 `test_run_unified_62.py`（e2e 断言 writer 关闭时
无结论段）、`test_report_sanitize_73.py`（零候选提示恰好 1 处，布尔双追加守卫随
结论兜底消亡）、`test_plan_fields_70.py`（conclusion 字段契约退役反向断言）、
`test_discovery.py` / `test_discovery_flow.py`（优雅降级改钉代码提示文案）。
