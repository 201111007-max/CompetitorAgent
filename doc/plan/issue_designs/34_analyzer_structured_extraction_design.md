# 设计文档 34 — 分析器结构化抽取（深度补充）

> 对应 `implementation_plan.md` §16.1 分析器行（"LLM 一次调用 + 关键词兜底"）。
> 触发：2026-08-14 深度复查——各分析器仅 `_build_prompt`/`_parse_result`/`_rule_extract` 三件套（各几十行），
> LLM 路径（base.py:62-81）是"包原文 → 一次 complete → `json.loads`"，无链式推理/多轮验证/结构化约束，`json.loads` 解析 LLM 输出易碎。
> 依赖：`analyzers/base.py`、`analyzers/registry.py`、`llm/client.py`、`agent/prompts/trust_boundary.py`。
>
> **实现状态（2026-08-14）**：已落地 ✅。`LLMClient.complete_json` 增 `schema`（JSON Schema 子集校验）+ `retries=2` 修复重试（错误回灌 prompt）；`BaseCompetitorAnalyzer._analyze_with_llm` 走 `complete_json(messages, schema=_schema_for(gap))` + 真值校验 `_verify_details`（数值与原文交叉核对，冲突降置信度 `[PARTIAL]`）；五个维度 `_details_properties` 与评测 `extract_prediction` 抽取键对齐。详见 `doc/plan/issue_designs/README.md` 设计文档 34 修复说明。

## 1. 问题现状

- `BaseCompetitorAnalyzer._analyze_with_llm`（`analyzers/base.py:62-81`）：`self._llm.complete(messages)` → `self._parse_result(text)`（多数是裸 `json.loads`，如 feature_analyzer.py），**无 JSON Schema 约束、无修复重试**——模型输出不合法 JSON 即异常降级规则。
- 规则兜底 `_rule_extract` 多为关键词扫描（feature 的 `_FEATURE_MARKERS`），语义浅、无真值校验。
- 影响：抽取鲁棒性弱、结构不统一（各维度 details 键各异），评测（设计文档 03/29）的 `extract_prediction` 依赖脆弱解析。

## 2. 目标设计

1. **结构化输出约束**：LLM 调用改为 JSON Schema 声明（`response_format` / 工具调用强制 schema，`LLMClient.complete_json` 支持 schema 参数），输出结构由 schema 保证，`_parse_result` 仅做校验/缺省补全。
2. **解析修复重试**：schema 校验失败 → 带错误信息的修复重试（≤2 次）→ 仍失败降级规则。
3. **链式抽取（可选增强）**：pricing/feature 等维度拆"定位相关段落 → 逐项抽取"两步（先粗筛再精取），减少长文直接抽取的丢项。
4. **真值校验**：`details` 数值字段（价格/数量/占比）与原文证据交叉核对，冲突标 `[PARTIAL]` 低置信不编造（沿用设计文档 24 的护栏语义）。

## 3. 模块/接口设计

### 3.1 `LLMClient` 扩展（`llm/client.py`）

```python
def complete_json(self, messages: list[dict], schema: dict | None = None,
                  retries: int = 2) -> dict:
    """带 JSON Schema 约束的结构化补全；校验失败带错重试，仍失败抛 LLMUnavailableError。"""
```

- 实现：`response_format={"type": "json_object"}` 或工具调用强制 schema；`_validate_schema(data, schema)` 递归校验必填/类型/枚举；错误信息回灌 prompt 重试。

### 3.2 `BaseCompetitorAnalyzer` 扩展（`analyzers/base.py`）

- `_parse_result` 改为接收 `(text, schema)`，基类提供默认 `_schema_for(gap)`（按维度返回 schema，子类可覆盖）。
- `_analyze_with_llm` 改走 `complete_json(messages, schema=self._schema_for(gap))`，失败重试，仍失败降级规则（保留注入检测：`detect_injection` 命中不送 LLM）。
- 新增 `_verify_details(result, observation)`：数值/布尔字段与 `observation.raw_text` 证据交叉核对，不一致 → 降置信度（<0.5 → `PARTIAL`）。
- 各维度 `_schema_for` 与 `_parse_result` 对齐 `extract_prediction`（设计文档 29 的 `DIMENSION_KINDS`）命名空间——pricing `plans[]`、feature `features[]`、performance `benchmarks[]`、ecosystem `mcp_servers/plugins/vscode/...`、sentiment `polarity/positive/...`。

### 3.3 规则兜底增强（各分析器 `_rule_extract`）

- 保留现有关键词扫描，但输出结构统一为 schema 缺省填充（空列表/0/false），保证"无信号不编造"且结构可评测。

## 4. 接入方式

```
AnalyzerRegistry 构造不变 → BaseCompetitorAnalyzer._analyze_with_llm
  → LLMClient.complete_json(messages, schema)  → _parse_result 校验补全
  → _verify_details 与证据交叉核对 → DimensionResult（置信度含校验惩罚）
规则降级路径输出对齐同一 schema 命名空间 → 评测 extract_prediction 零改动
```

- 主流程零改动（analyze 签名/报告结构不变），仅内部抽取路径增强。

## 5. 验证方式

- **单测（complete_json）**：合法 JSON 通过；schema 校验失败重试 2 次后仍失败抛错；错误回灌后第二次成功。
- **单测（schema 对齐）**：各维度 schema 的必填键与 `extract_prediction` 可抽取键一致（防评测契约漂移）。
- **单测（校验惩罚）**：价格与原文证据冲突 → 置信度下调 → `[PARTIAL]`；一致 → `COMPLETE`。
- **集成**：mock LLM 输出半合法 JSON → 修复重试成功而非降级；真实链路字段准确率不降。
- **回归**：分析器/评测既有测试全绿（基准 mock 走规则路径，不受 LLM 路径改动影响）。

## 6. 实现优先级与工作量

- 优先级：**中**（抽取鲁棒性 + "怎么让 LLM 输出稳定"的答案）。
- 工作量：约 1 天。
  - `complete_json` + schema 校验/重试：0.4 天；
  - 基类 schema/校验惩罚 + 各维度 schema 对齐：0.4 天；
  - 测试：0.2 天。
- 前置：设计文档 03/29（评测抽取契约稳定，作为 schema 对齐基准）；与 36（LLM 层可靠性）共享 `complete_json`，可同批落地。
