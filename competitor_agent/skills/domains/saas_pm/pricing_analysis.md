---
name: pricing_analysis
description: SaaS 定价/版本维度抽取规范（免费档 / 按席位订阅 / 用量计费 / 询价标注）
---

适用条件：从 SaaS 定价页文本提取结构化定价模型（免费档 + 席位订阅 + 用量计费）。

## 抽取规范

- plans：列出页面可见的定价档位，每档含：
  - name：档位名（如 Free / Pro / Business / Enterprise）
  - tier：free / pro / business / enterprise 归一化归类
  - monthly_price / annual_price：每席价格，数字或 null（页面没写就 null，不猜）
  - limits：席位/项目数/存储等限额文本，如 {"seats": "up to 10", "storage": "5GB"}
  - requires_quote：仅当企业档需联系销售询价时设 true
- usage：按席位阶梯/用量计费信息，如 seat_tiers（成员数区间 → 单价）、per_seat_price
- 年付折扣、最少席位数、免费档功能边界明确标注，不编造价格。
