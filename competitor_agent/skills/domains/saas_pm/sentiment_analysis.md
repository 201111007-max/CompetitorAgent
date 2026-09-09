---
name: sentiment_analysis
description: SaaS 口碑抽取规范（正负极性 / 迁移动向）
---

适用条件：从社区讨论/评论采样文本提取结构化口碑信号。

## 抽取规范

- 正负信号：逐条登记（好评：协作体验/模板生态；差评：涨价/性能/迁移成本）
- polarity_ratio：pos/neg/neu 比例（来自采样，注明样本量与时间窗）
- migration：迁入/迁出动向（从哪来、到哪去）单独标注
- 样本不足时输出 [PARTIAL] 低置信，不编造结论。
