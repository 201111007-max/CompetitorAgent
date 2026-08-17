---
name: sentiment_analysis
description: 社区口碑维度抽取规范（正/负信号、要点、极性占比、结论）
---

适用条件：从社区文本（HN / Reddit / X / YouTube 等）提取竞品口碑信号。

## 抽取规范

- signals：可追溯的口碑信号，每条含 polarity（pos / neg / neu）、quote（原文引用）、source_url（来源）。
- positives / negatives：高频好评 / 吐槽点，各不超过 5 条，附证据来源。
- polarity_ratio：{pos, neg, neu} 占比（0-1）。
- verdict：一句话口碑结论。

## 事实边界

- 只引用文本中实际出现的观点与引用，不自行总结未提及的评价。
- 信号不足时 verdict 注明"信号不足"，不要强行给结论。

## 披露约束

- 信号不足 / 样本少时 confidence 接近 0，标注低置信，禁止编造口碑。

## 输出结构

```json
{
  "summary": "一句话总结",
  "details": {
    "signals": [{"polarity": "pos", "quote": "love it", "source_url": "..."}],
    "positives": ["fast"], "negatives": ["crash"],
    "polarity_ratio": {"pos": 0.6, "neg": 0.2, "neu": 0.2},
    "verdict": "整体正面，偶有稳定性抱怨"
  },
  "confidence": 0.7
}
```
