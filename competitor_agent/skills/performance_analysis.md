---
name: performance_analysis
description: 性能/榜单维度抽取规范（基准测试数据，榜单优先页面兜底）
---

适用条件：从评测页/榜单文本提取基准测试数据（SWE-bench / Aider polyglot / Terminal-Bench / LMArena 等）。

## 抽取规范

- benchmarks：每条含 name（基准名）与 score（数值/得分）。
- 同指标以权威榜单为准：若存在榜单直连数据，页面上的同指标数字让位给榜单，避免冲突。
- 仅页面数字而无权威榜单时，明确标注来源，不冒充权威数据。

## 事实边界

- 只提取文本中实际出现的基准名称与得分；未出现的基准 / 得分不编造。
- 榜单分数带单位/版本（如 SWE-bench Verified）时如实保留，不做跨基准换算。

## 披露约束

- 无权威榜单数据时降低 confidence 并注明"无权威榜单数据"，不编造性能数字。

## 输出结构

```json
{
  "summary": "一句话总结",
  "details": {"benchmarks": [{"name": "swe-bench verified", "score": 62}]},
  "confidence": 0.8
}
```
