---
name: pricing_analysis
description: 定价/版本维度抽取规范（档位 / 按量计费 / 成本场景 / 询价标注）
---

适用条件：从定价页文本提取结构化定价模型（档位 + 按量计费 + 典型用量成本估算）。

## 抽取规范

- plans：列出页面可见的定价档位，每档含：
  - name：档位名（如 Pro / Business / Enterprise）
  - tier：free / pro / business / enterprise 归一化归类
  - monthly_price / annual_price：数字或 null（页面没写就 null，不猜）
  - limits：限额文本，如 {"requests": "1000 requests/month"}
  - requires_quote：仅当企业档需联系销售询价时为 true
- usage：按量计费信息，含 unit（如 request）、per_unit_price、quantity（档内包含量）、model_tiers（不同模型档位单价）
- 企业档需询价 / 无公开价格时明确标注，不编造价格。

## 事实边界

- 只提取页面实际出现的价格与档位；页面没有的档位 / 价格一律给 null 或空，不编造。
- 免费档 / 试用期 / 促销价要按页面原文描述，不自行换算或假设。

## 披露约束

- 只有标价而无按量信息时，不要臆测成本；无法估算的场景标注"需询价 / 数据不足"。

## 输出结构

```json
{
  "summary": "一句话总结",
  "details": {
    "plans": [
      {"name": "pro", "tier": "pro", "monthly_price": 20, "annual_price": 200,
       "limits": {"requests": "1000 requests/month"}, "requires_quote": false}
    ],
    "usage": {"unit": "request", "per_unit_price": 0.01, "quantity": 1000,
              "model_tiers": {"basic": 1.0, "advanced": 2.0}}
  },
  "confidence": 0.8
}
```
