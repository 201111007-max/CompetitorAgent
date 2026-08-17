---
name: roadmap_analysis
description: 路线图/roadmap 维度抽取规范（版本发布节奏 + 计划内路线）
---

适用条件：从 GitHub Releases / 官方文档 / changelog 文本提取竞品版本发布与计划内功能。

## 抽取规范

- releases：近期发布，每条含 version、date、notes（发布要点）。
- upcoming：计划中 / 预告功能（roadmap 条目），每条一个字符串。

## 事实边界

- 只提取文本中明确出现的版本号 / 日期 / 计划功能；没有明确路线数据的字段给空列表，不编造具体版本或日期。
- 区分"已发布"（releases）与"计划中"（upcoming），不把预告当已发布。

## 披露约束

- 路线数据不足时降低 confidence，summary 注明"路线图数据有限"。

## 输出结构

```json
{
  "summary": "一句话总结",
  "details": {
    "releases": [{"version": "1.5.0", "date": "2026-07-01", "notes": "agentic 增强"}],
    "upcoming": ["background agents"]
  },
  "confidence": 0.8
}
```
