# 评测体系规范（evaluation_guide.md）

> 竞品分析 Agent 的质量评测：指标口径、ground truth 标注格式、用例管理与回归。

---

## 1. 评测指标与口径

### 1.1 字段准确率（Extraction Accuracy）

```
字段准确率 = (抽取正确字段数) / (ground truth 字段总数)
```

- 字段指定价、版本号、支持的 IDE、语言等**可精确核对**的值。
- 判定：预测值与 ground truth 完全一致（字符串规范化后）。

### 1.2 幻觉率（Hallucination Rate）

```
幻觉率 = 无证据支撑的断言数 / 总断言数
```

- 审计每个 `DimensionResult.summary` 的子断言是否可回溯到 `SourceEvidence`。
- 无法回溯或证据与结论方向相反 ⇒ 幻觉。

### 1.3 工具选择准确率（Tool Selection Accuracy）

```
工具选择准确率 = 对正cycle选用正确工具的步数 / 总决策步数
```

- ground truth 标明该信息缺口应优先用哪个数据源，与实际 SourceSelector→ReAct 选择比对。

### 1.4 成本效率（Cost Efficiency）

```
成本效率 = ground truth 达成核心缺口的成本 / 实际达成核心缺口的成本
```

---

## 2. Ground Truth 标注格式

`tests/evaluation/fixtures/*.json`

```json
{
  "case_id": "cursor_pricing_2026",
  "competitor": "cursor",
  "dimension": "pricing",
  "expected": {
    "price_monthly": 20,
    "price_pro_monthly": 20,
    "free_tier": true,
    "currency": "USD"
  },
  "expected_tool": "pricing_source",
  "sources": [
    {"name": "official_pricing", "url": "https://cursor.com/pricing"},
    {"name": "docs_pricing", "url": "https://cursor.com/docs"}
  ],
  "tags": ["pricing", "usd"]
}
```

**标注规范**：
1. `case_id` 唯一，含竞品+维度+年月。
2. 所有 `expected` 值必须来自标注时官网快照（存 `sources` 便于复核）。
3. 每个 case 可跑多次平均，报告均值±方差。

---

## 3. 用例分类与规模

| 类别 | 数量(MVP) | 覆盖 | 维护频率 |
|------|-----------|------|---------|
| 定价抽取 | 5+ | 各定价模型（SaaS/开源/试用） | 每季度刷新 |
| 功能抽取 | 5+ | 核心功能矩阵 | 每季度 |
| 版本/回志 | 3+ | 最新版本号/发布日期 | 版本发布后刷新 |
| 生态Ubuntu集成 | 2+ | 支持 IDE/平台 | 每季度 |
| 口碑 | 2+ | 社区结论合理性 | 每月抽样 |
| 多语言 | 2+ | 中/英/日文档 | 随采集覆盖 |

> MVP 目标 10+ case，长期扩充至 30+。

---

## 4. 运行命令

```bash
# 全量评测
pytest tests/evaluation -v

# 单 case
pytest tests/evaluation -k cursor_usage

# 输出指标 CSV / 报告
python -m competitor_agent.evaluation.benchmark --out reports/benchmark.csv
```

---

## 5. 回归与门禁

| 门槛 | 触发 | 阻断 |
|------|------|------|
| 核心指标回归 | CI / 手动跑 evaluation | 字段准确率 < 90% 或 幻觉率 > 5% 阻断合并 |
| 新增采集器 | 新 collector 提交 | 必须附带覆盖该源的正/负样本 case |

---

## 6. 新增用例流程

1. 采集（或 mock）官网当前真实快照，形成值。
2. 填 `expected` + `expected_tool` + `sources`。
3. 加 `tags` 便于筛选。
4. 首次跑一遍确认指标，纳入基准。
5. 若该 case 因网站改版失效，更新 `sources` 快照并在 commit 说明。

---

## 7. 评测报告输出

`reports/benchmark_<date>.md`：
- 各 case 指标明细
- 均值/方差
- 幻觉实例清单（审计通过/失败）
- 工具选择混淆矩阵（可选）