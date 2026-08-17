---
name: feature_analysis
description: 功能维度抽取规范（核心功能点清单）
---

适用条件：从官网/文档文本提取竞品核心功能列表。

## 抽取规范

- features：从文本提取核心功能点，每条一个字符串（短语级，如 "terminal support"、"agentic tool-use"）。
- 只提取明确描述的功能；泛泛宣传语（"best in class" 等）不列为功能点。

## 事实边界

- 页面未出现的功能不要自行补全或联想；不确定是否为功能点时宁可不列。

## 披露约束

- 功能很少 / 页面信息有限时降低 confidence，并在 summary 注明局限。

## 输出结构

```json
{
  "summary": "一句话总结",
  "details": {"features": ["terminal support", "agentic tool-use"]},
  "confidence": 0.8
}
```
