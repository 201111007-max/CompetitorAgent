---
name: planning
description: 竞品分析战略规划规范（维度选择 / 优先级 / 预算 / 自定义源输出约束）
---

适用条件：为竞品分析任务产出结构化规划（competitor / dimensions / priorities / budget / custom_sources），只输出 JSON，不要其他文字。

## 规划规范

- 竞品规范名：取任务明确提到的竞品（注册表规范名）；未知竞品用任务原文中的名称，不自行发明。
- 维度选择：只列任务明确要求的维度（如任务只说定价就只列 pricing）；任务没提维度则列出全部 6 个维度
  （pricing / feature / performance / ecosystem / sentiment / roadmap）。
- 优先级：体现任务侧重（如强调价格则 pricing 优先），取值 1-10 整数；缺省用系统默认。
- 预算：每维度迭代次数整数，缺省每维度 1。
- 自定义源：仅当用户提供了具体 URL 才填 custom_sources（key 为 home / pricing / docs），否则留空。

## 输出结构

```json
{
  "competitor": "竞品规范名",
  "dimensions": ["pricing", "feature"],
  "priorities": {"pricing": 9, "feature": 7},
  "budget": {"pricing": 2},
  "custom_sources": {"pricing": "https://example.com/pricing"}
}
```

## 披露约束

- 用户任务未明确的维度不要臆测加入；分辨率（单竞品 / 发现 / 对比）由解析层决定，规划不输出该字段。
