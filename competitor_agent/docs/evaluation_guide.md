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

- ground truth 标明该信息缺口应优先用哪个数据源，与实际 Lead/子 Agent 的 ReAct 工具选择比对。

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

### 2.1 生态 / 口碑 / 时间线字段标注（设计文档 29）

新增三维度的 ground truth 落在各自的结构化 payload 上（对应设计文档 24 的 `EcosystemAnalyzer` / `SentimentAnalyzer`、26 的 `TimelineMemory`）：

```json
{
  "case_id": "cursor_ecosystem_mcp_ide_2026",
  "competitor": "cursor",
  "dimension": "ecosystem",
  "task": "只分析 cursor 的生态",
  "tags": ["ecosystem", "normal"],
  "page": "MCP server: GitHub integration\nMCP server: Slack integration\nSupports VSCode and JetBrains IDE plugins.",
  "ground_truth": {
    "mcp_servers": 2,
    "vscode": "true",
    "jetbrains": "true"
  }
}
```

```json
{
  "case_id": "cursor_sentiment_positive_2026",
  "competitor": "cursor",
  "dimension": "sentiment",
  "task": "只分析 cursor 的口碑",
  "tags": ["sentiment", "normal"],
  "page": "Users love the fast autocomplete.\nGreat IDE experience.\nHighly recommended.",
  "ground_truth": {
    "polarity": "pos",
    "positive": "true"
  }
}
```

```json
{
  "case_id": "timeline_first_run_no_events_2026",
  "competitor": "aider",
  "dimension": "roadmap",
  "task": "只分析 aider 的定价",
  "tags": ["roadmap", "boundary", "timeline"],
  "page": "Pro $25/month",
  "ground_truth": {
    "has_events": "false"
  }
}
```

**新维度字段抽取与判定口径**（`evaluation/benchmark.py` `extract_prediction`）：

| 维度 | kind | 可抽取字段 | 判定口径 |
|------|------|-----------|---------|
| ecosystem | `ecosystem_signal` | `mcp_servers`（数量 int）、`plugins`（数量 int）、`stars`（int）、`vscode`/`jetbrains`/`terminal`（`true`/`false`）、`ide`（合并串） | 数量精确匹配；IDE 支持按 `ide_support` 子集命中 |
| sentiment | `sentiment_signal` | `polarity`（`pos`/`neg`/`neu`）、`positive`/`negative`/`neutral`（`true`/`false`）、`pos`/`neg`/`neu`（占比） | 极性按 `polarity_ratio` 主导项命中（无主导 → `neu`）；正负有无按占比 >0 |
| roadmap | `timeline_event` | `has_events`（`true`/`false`） | 报告内嵌「竞品时间线」段落是否存在；首轮无基线 → 无事件 |

**空数据护栏**：`ecosystem` / `sentiment` 的空数据用例（tags 含 `empty_signal`）期望抽取为 `0` / `false` / `neu`，系统不得因数据缺失而编造具体结论——这是"信号不足 → `[PARTIAL]` 不编造"的评测侧断言。

---

## 3. 用例分类与规模

> 覆盖类型按 benchmark_design.md §5 组织：正常 / 边界 / 工具失败 / 安全。

| 类别 | 数量(当前) | 覆盖 | 维护频率 |
|------|-----------|------|---------|
| 定价抽取 | 8+ | 各定价模型（SaaS/开源/试用/多币种） | 每季度刷新 |
| 功能抽取 | 4+ | 核心功能矩阵 | 每季度 |
| 性能抽取 | 3+ | 榜单/延迟/胜率等基准 | 随榜单更新 |
| 生态抽取 | 4+ | MCP server 数量 / IDE 支持 / 插件市场 / 空数据护栏（设计文档 29） | 每季度 |
| 口碑抽取 | 5+ | 正/负/混合极性、单信号、空数据护栏（设计文档 29） | 每季度 |
| 时间线 | 1+ | 首轮无基线不产生事件（设计文档 29 边界） | 随版本 |
| 边界 | 5+ | 罕见定价/多币种/多语言/空缺字段 | 随采集覆盖 |
| 安全/拒绝 | 2+ | 无证据不臆断、冲突证据拦截 | 每月抽样 |
| 工具失败(降级链) | 3+ | 404/反爬/5xx → 降级 | 随采集覆盖 |

> 当前 38 条（27 accuracy + 11 strategy），真实执行版，满足设计文档 §5 的 ≥20 最小集。
> 门禁含维度拆分：新维度（ecosystem/sentiment/roadmap）字段准确率 ≥ 0.80、生态/口碑空数据幻觉率 ≤ 0.02。
> 每个分数必须附带 harness 版本号（benchmark + subset + harness，当前 v0.5.0）。

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
| 新维度覆盖 | CI / 手动跑 evaluation | ecosystem/sentiment/roadmap 字段准确率 < 80% 或空数据幻觉率 > 2% 阻断合并（设计文档 29） |
| 新增采集器 | 新 collector 提交 | 必须附带覆盖该源的正/负样本 case |

> **skill 注入与 mock 确定性（设计文档 48）**：分析 / 规划 prompt 注入的 `<skill name="...">` 块是独立 system
> 消息，不进入 `BenchmarkMockLLM` 依赖的「用户任务」/观察文本段 → mock 全量门禁（字段 1.0 / 幻觉 0 /
> 工具选择 ≥0.85 / trace 100%）与既有断言保持（`tests/evaluation/test_skill_injection.py` 验证）。
> 技能目录可用 `SKILLS_DIR` 环境变量覆盖（评测注入确定性内容），注入点对缺失静默降级。

> **ReAct-scripted mock 编排（设计文档 49 重写）**：`BenchmarkMockLLM` 按 ReAct 脚本驱动 Lead 会话
> （make_plan → delegate → 子 Agent 按维度确定性抽取，复用既有 details 命名空间 → Final Answer
> REPORT_SCHEMA JSON），conversation-safe（按消息推导阶段，无共享状态）；HARNESS_VERSION 0.7.0
> 重定门禁（字段 ≥0.90 / 幻觉 ≤0.05 / 工具选择 ≥0.85 / trace 100%）。消融的 `no-llm-rule` 变体
> 已改为 `no-tools`（单发 plan + Final Answer 无工具循环），保 5 列对比。

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

---

## 8. 消融 / 对比实验（设计文档 30）

回答「加 RAG / 加记忆 / 加工具循环到底有没有用」（设计文档 47：主路径仅 LLM，无规则降级变体；
设计文档 49：`no-llm-rule` 变体改为 `no-tools`）——
对同一批确定性用例逐变体跑真实执行链路，产出「变体 × 指标」对比表。

### 8.1 运行

```bash
# 5 变体全跑 + 落盘 reports/ablation/ablation_<date>.md/.json
python -m competitor_agent.cli benchmark --ablate

# 仅跑默认评测（不加消融）
python -m competitor_agent.cli benchmark
```

### 8.2 变体矩阵

| 变体 | enable_rag | enable_memory | 工具循环 | 说明 |
|------|:---:|:---:|:---:|------|
| full | ✅ | ✅ | ✅ | 完整链路（默认行为） |
| no-rag | ❌ | ✅ | ✅ | 关知识库检索 |
| no-memory | ✅ | ❌ | ✅ | 关四层记忆副作用 |
| no-rag+no-memory | ❌ | ❌ | ✅ | 双关 |
| no-tools | ✅ | ✅ | ❌ | 单发 make_plan + Final Answer，无工具循环（设计文档 49） |

> 设计文档 47/49：主路径仅 LLM 且无规则降级，`no-llm-rule` 变体已删除——确定性由
> `BenchmarkMockLLM` 在 LLM 版接口上 ReAct-scripted 固定返回承担；`no-tools` 衡量
> ReAct 工具循环本身的增益。

每变体用独立目录的共享 `FourLayerMemory` 与 `CompetitorStore`（跨用例累积），
使 RAG / 记忆差分可测（no-rag 检索不到先前摄入片段、no-memory 无成功率/技能累积）。

### 8.3 读表口径

- 对比表每行标粗最优；幻觉率与平均命中排名**越小越好**，其余越高越好。
- 「幻觉率差分 vs full」段落为门禁标注：`[OK]` = 不差于 full，`[WARN]` = 劣于 full。
- 工具选择/成本效率在无记忆变体下可能更优——这是记忆成功率信任提升重排选源（`_record_memory_success`
  按 `sources_tried[-1]` 记账）带来的真实记忆效应，需结合差分集成测试解读，而非开关故障。

### 8.4 差分测试（RAG/记忆收益的独立证据）

`tests/evaluation/test_ablation.py`：
- 预置知识库含答案而页面无答案 → `full` 从片段命中、`no-rag` 缺失；
- 前一用例摄入片段 → 后一用例（页面无答案）经 RAG 检索命中；
- `enable_memory=False` 时记忆零写入（无 archive/skill/outcome）。

---

## 9. 失败类型统计（设计文档 31）

回答「这个 case 为什么没命中？」，支撑归因优化与简历/面试的"失败类型统计"证据。

### 9.1 五类失败（`evaluation/failure.py` `FailureType`）

| 类型 | 判定 | 对应底层信号 |
|------|------|-------------|
| `source_unavailable` | 源抓取失败 / 降级链全灭 / BLOCKED；strategy miss 且无有效源 | `DataSourceUnavailableError`、fail_urls 全灭、`BLOCKED` |
| `hallucination` | 预测字段无真值支持（命中现有幻觉判定） | `hallucination_instances` |
| `no_data` | 源有响应但内容不含目标信息（预测全空 → 低置信/`[N/A]`，不编造） | 低置信 `[PARTIAL]` / `[N/A]` |
| `parse_failure` | 有内容但抽取/归一化错误（预测非空但 F1<1 且非幻觉）；strategy miss 但有源未选最优 | prediction 非空但 F1<1 |
| `budget_exhausted` | 预算 / 迭代耗尽提前终止 | `terminal_state` / 预算触停 |

`classify_case(case, prediction, ground_truth, report, status_hints)` 判定优先级：
**幻觉 > 预算触停 > 源不可用/BLOCKED > 无数据 > 解析错误**；全部字段命中返回空。
判定口径复用 `accuracy_eval` 归一化（`_normalize`/`_tokens`），与 `hallucination_instances` 一一对应。
`status_hints` 提供分类无法自行推导的信号：`budget_exhausted` / `source_unavailable` / `blocked`。

### 9.2 聚合与报告

- `Benchmark.run()` 对 accuracy 未命中 case（`classify_case`）+ strategy miss case（无有效源 → `SOURCE_UNAVAILABLE`、有源未选最优 → `PARSE_FAILURE`）
  按 `(case_id, type)` 去重聚合 → `BenchmarkReport.failure_stats`（type→count）+ `failure_records`（逐条样本，含 case/dimension/type/detail/evidence_urls）。
- `to_dict()` 同步携带两字段（供设计文档 28 结构化导出复用）。
- Markdown 报告新增「## 失败类型分布」：`| 类型 | 计数 | 占比 |` + 逐 case 样本表（证据 URL 可回溯）；CSV 增 `failure.{type}` 与 `failure.total` 行。

### 9.3 确定性护栏

`build_benchmark_api` 注入每 case 独立的空 `TimelineMemory`（临时目录）——「首轮无基线不产生事件」边界
（设计文档 26/29）不受外部共享时间线状态污染，失败统计可信可复现。

`tests/evaluation/test_failure_stats.py`：classify_case 5 类场景 + 优先级 + 全命中空、
`_classify_failures` 聚合计数/去重、自定义 fixtures 集成（真实链路 mock LLM + 固定页面）、默认 38 用例报告含分布表与 CSV failure 行。

---

## 10. 真实 LLM 评测（设计文档 37）

回答「评测是不是自证」：mock（`BenchmarkMockLLM` 确定性解析）验证的是 **harness 自洽**，
`--llm real` 产出的才是**真实模型端到端质量**——简历/面试说"字段准确率 90%+"时能拿出真实数据。

### 10.1 命令与前置

```bash
# 前置：配置 API Key（OPENAI_API_KEY / DEEPSEEK_API_KEY / LLM_API_KEY），否则 --llm real 明确报错不回退 mock
python -m competitor_agent.evaluation.benchmark --llm real --tag normal --cost-limit 1.0 \
  --out reports/benchmark_real_<date>.csv --report reports/benchmark_real_<date>.md

# 全量 38 用例（成本更高）；无 --tag 默认全量
python -m competitor_agent.evaluation.benchmark --llm real

# CLI 透传
python -m competitor_agent.cli benchmark --llm real --tag normal --cost-limit 1.0
```

- 缺省输出：real 落 `reports/benchmark_real_<date>.csv/.md`（mock 落 `reports/benchmark_<date>.csv/.md`）。
- **口径**：real 报告内嵌同子集 mock 基线「mock vs real」对比段（mock=harness 回归，real=真实质量）；
  真实幻觉率/成本以 real 列为准，mock 列是"链路正确"的自洽基线。
- **成本核算**：复用 `llm._log_call` 的 `cost_usd` 累计（`LLMClient.total_cost_usd` 跨 case 共享实例累计），
  报告含单用例成本（`per_case_cost`）与总成本（`cost_usd`），CSV 含 `cost_usd`/`cost.case.<id>` 行。

### 10.2 成本护栏（`--cost-limit`）

- real 模式默认 `cost_limit_usd = 1.0`；累计成本达到上限即中止，未运行 case 记 `budget_exhausted`
  （复用设计文档 31 失败分类），报告 `budget_aborted=True` 并标注「⚠️ 预算中止」。
- 先用 `--tag normal` 控制成本，再按需扩到全量。

### 10.3 验证

`tests/evaluation/test_real_evaluation.py`：报告字段（llm_mode/cost_usd/per_case_cost）、共享实例成本累计、
`--tag` 子集过滤、成本护栏中止（budget_exhausted）、mock/real 渲染分支 + mock vs real 对比段、CSV 成本列；
real 冒烟在无 Key 时 `skipif`（不卡 CI）。mock 评测输出与既有断言兼容（回归不变）。
