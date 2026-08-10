# 评测体系规范（evaluation_guide.md）

> 竞品分析 Agent 的质量评测：指标口径、ground truth 标注格式、用例管理与回归。
> 评测基准设计与 benchmark 组合见 `doc/benchmark_design.md`；CI 门禁含 `tests/evaluation/`。

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

accuracy case（真实执行版：只含 task + ground_truth + 确定性采集配置，prediction 由系统真实产出）：

```json
{
  "case_id": "cursor_pro_team_2026",
  "competitor": "cursor",
  "dimension": "pricing",
  "task": "只分析 cursor 的定价",
  "tags": ["pricing", "normal"],
  "mode": "single",
  "page": "Pro $20/month\nTeam $40/month",
  "ground_truth": {
    "pro": "$20/month",
    "team": "$40/month"
  }
}
```

strategy case（策略/降级：`best_url` 标任务应首选（或降级后应命中）的源 URL，`fail_urls` 模拟首候选源故障）：

```json
{
  "case_id": "cursor_pricing_degraded_2026",
  "competitor": "cursor",
  "dimension": "pricing",
  "task": "只分析 cursor 的定价",
  "tags": ["tool_failure", "degradation"],
  "page": "Pro $20/month",
  "fail_urls": ["https://www.cursor.com/pricing"],
  "best_url": "https://www.cursor.com"
}
```

**标注规范**：
1. `case_id` 唯一，含竞品+维度+年月。
2. `ground_truth` 必须落在 `extract_prediction` 的可抽取命名空间（pricing→plan 名、feature→特征词、performance→基准名），值来自 `page` 固定内容。
3. 每个 case 可跑多次平均，报告均值±方差。

---

## 3. 用例分类与规模

> 覆盖类型按 benchmark_design.md §5 组织：正常 / 边界 / 工具失败 / 安全。

| 类别 | 数量(当前) | 覆盖 | 维护频率 |
|------|-----------|------|---------|
| 定价抽取 | 8+ | 各定价模型（SaaS/开源/试用/多币种） | 每季度刷新 |
| 功能抽取 | 4+ | 核心功能矩阵 | 每季度 |
| 版本/回志 | 2+ | 最新版本号/发布日期 | 版本发布后刷新 |
| 生态Ubuntu集成 | 1+ | 支持 IDE/平台 | 每季度 |
| 边界 | 5+ | 罕见定价/多币种/多语言/空缺字段 | 随采集覆盖 |
| 安全/拒绝 | 2+ | 无证据不臆断、冲突证据拦截 | 每月抽样 |
| 工具失败(降级链) | 3+ | 404/反爬/5xx → 降级 | 随采集覆盖 |

> 当前 26 条（17 accuracy + 9 strategy），真实执行版，满足设计文档 §5 的 ≥20 最小集。
> 每个分数必须附带 harness 版本号（benchmark + subset + harness）。

---

## 4. 运行命令

```bash
# 全量评测
pytest tests/evaluation -v

# 单 case
pytest tests/evaluation -k cursor_usage

# 输出指标 CSV / 报告（mock=确定性评测/CI；real=真实 LLM 评估本地质量）
python -m competitor_agent.evaluation.benchmark --llm mock --out reports/benchmark.csv
python -m competitor_agent.evaluation.benchmark --llm real --out reports/benchmark_real.csv
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