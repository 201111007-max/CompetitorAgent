# 设计文档 67 — 竞品周报数据管线化 + 产品化闭环（社招作品集升级）

> 第十七轮。基于「三层改造路线」对照盘点当前项目：
> - **第 2 层（结构化评估框架）已完备**——golden set 38 条（`accuracy_cases.json`）+ `field_accuracy/hallucination_rate/F1` 字段级准确率 + 真实 LLM 评测 harness（`benchmark --llm real`，mock vs real 对照）+ `--gate` CI 门禁 + 消融/失败统计，面试可直说"事实准确率可量化、可回归"。
> - **第 1 层（数据管线化）存在缺口**：① 榜单无结构化直连（performance 靠 LLM 读网页解析）；② 舆情无采样源（sentiment 靠搜索+抓取，doc 24 分析器已在 doc 49 重写时删除）；③ 无内置调度器 + 无"本周变化"周报聚合（`run_scheduled` 靠外部 cron，只按竞品 diff 发告警）。
> - **第 3 层（产品化闭环）存在缺口**：④ 可视化导出全无（无雷达图/HTML 分享，pyproject 零图表库）；⑤ 无 human-in-the-loop 审批节点（报告直接落盘）；⑥ 告警无推送通道（仅文件+控制台）。
>
> 本文档补齐**第 1 层 + 第 3 层**。doc 66 已覆盖 web_search（Tavily）接入与报告路径对齐，本文档**不重复**。

## 1. 问题现状

### 1.1 已具备（不重复建设）

| 能力 | 现状 |
|------|------|
| 评估体系（第 2 层） | ✅ golden set + 真实 LLM 评测 + `--gate` CI（`evaluation/`、`tests/evaluation/`） |
| 编排/工具/可靠性 | ✅ 统一 `run()` 单 Lead loop + delegate/aggregate + 并行 tool_calls + 工具超时/校验/失败回灌 + SSRF 防护 + 可逆压缩 + 四层记忆 + Langfuse trace + Docker/CI |
| GitHub 数据源 | ✅ `github_tools.py` 真实 REST（stars/releases/commits，Token 经 SecretVault） |
| 定价抓取 | ✅ `analyze_pricing`（registry 官方定价页 + `web_extract`） |
| 定时雏形 | ✅ `run_scheduled`（`facade/api.py:584`，外部 cron 触发）+ `TimelineMemory.diff` → `report_diff` → `FileAlertSink` 告警文件 |
| 结构化导出 | ✅ `report_to_dict` / `export_competitor_json` / `export_comparison_json`（`report_exporter.py`） |

### 1.2 缺口（本文档覆盖）

1. **榜单无结构化直连**：`data_sources.md` 声称 SWE-bench/Aider leaderboard 抓取，但无专用采集器——`performance` 维度实际靠 Lead/子 Agent LLM 读网页（`web_extract`）解析，数字可信度与"直连榜单"名不副实（doc 25 仅留文档层面）。
2. **舆情无采样源**：`sentiment` 维度工具子集仅 `web_extract/web_search`（`subagent_registry.py:28`），无 X/Reddit/即刻专用采样；doc 24 的 SentimentAnalyzer 规则版已在 doc 49 重写时删除。
3. **无内置调度器 + 无周报聚合**：`run_scheduled` 依赖外部 cron；产出只有单竞品报告 + 告警文件，**没有"本周变化"汇总周报产物**（价格变动/新版本/榜单分数变化/新增竞品的跨竞品聚合）。
4. **可视化导出全无**：`pyproject.toml` 依赖仅 `httpx`/`pyyaml`（[dev] `pandas`），无 matplotlib/plotly/reportlab/weasyprint——分享只能 Markdown + 网页面板。
5. **无 human-in-the-loop 审批节点**：报告落盘即发布，重要结论（价格变化/高置信推荐/低置信 PARTIAL）无人工确认门。
6. **告警无推送通道**：`AlertSink` 只有 `ConsoleAlertSink`/`FileAlertSink`（`core/alerting.py`），无 webhook/IM/邮件推送。

### 1.3 根因链（以 #3 为例）

```
run_scheduled 依赖外部 cron（无内置调度）
   ↓
仅按单竞品 diff 发告警文件（无跨竞品周报聚合）
   ↓
"本周变化"不可见 → 数据无时间序列叙事 → 与"网页版即时快照"拉不开差距
```

## 2. 第 1 层设计：数据管线化

### 2.1 榜单结构化直连（benchmark source）

**目标**：`performance` 维度结论的数字来自**结构化榜单数据源**而非 LLM 读网页。

**新增 `collector/benchmark_sources.py`**（对齐 doc 66 的 `SearchProvider` 策略模式，不引入新依赖，纯 `httpx`）：

- `BenchmarkHit`（dataclass）：`benchmark`（如 swe-bench / terminal-bench / aider）、`rank`、`model`、`score`（通过率）、`date`、`source_url`、`fetched_at`。
- `BenchmarkSourceProvider`（Protocol）：`fetch(benchmark: str) -> list[BenchmarkHit]`。
- `TerminalBenchProvider` / `SweBenchProvider`：对官方榜单页/API 的结构化解析（Terminal-Bench 有公开结果表；SWE-bench 官方 leaderboard 抓 HTML 表；Aider 列表）。解析失败返回可读提示，不抛（守 doc 47 降级不编造）。
- `build_benchmark_provider(config, vault) -> BenchmarkSourceProvider | None`：无网/无 Key/主开关关 → `None`。
- **接入点**：新增 MCP 工具 `benchmark_scores(benchmark)`（注册进 `TOOLS`/`TOOL_SPECS`，MCP/ReAct 同源，描述注明"结构化榜单数据"），`performance` 维度子 Agent 工具白名单（`subagent_registry.py:27`）加 `benchmark_scores`；`report_exporter._benchmark_scores` 已存在，数据路径自然贯通。
- **时间序列**：每次抓取记入 `TimelineMemory`（`score_change` 事件，`_EVENT_TYPE_BY_DIM` 已含 `performance→score_change`），周报聚合据此出"榜单分数变化"。

### 2.2 舆情采样源（sentiment source）

**目标**：`sentiment` 结论带**样本量与时间窗**（data_sources.md R13 缓解），不靠泛搜索碰运气。

**新增 `collector/sentiment_sources.py`**：

- `SentimentSample`（dataclass）：`platform`（reddit / x / jike / hn）、`text`、`source_url`、`posted_at`、`fetched_at`、`sample_size`。
- `SentimentProvider`（Protocol）：`sample(competitor: str, max_samples: int) -> list[SentimentSample]`。
- `RedditProvider`（JSON 端点 `https://www.reddit.com/r/<sub>/search.json?q=<competitor>&restrict_sr=1`，可配 `REDDIT_*` 可选）、`HackerNewsProvider`（`https://hn.algolia.com/api/v1/search?query=<competitor>`，公开免 Key）、`JikeProvider`（无公开 API → 用 web_search + `web_extract` 采样即刻话题链接，或可配 RSS 列表）；X 公开 API 受限 → 用 web_search 采样（标注 platform="search"）。
- `build_sentiment_provider(config, vault) -> SentimentProvider | None`。
- **接入点**：新增 MCP 工具 `sentiment_sampling(competitor, platform)`（注册进 `TOOLS`/`TOOL_SPECS`），`sentiment` 维度子 Agent 工具白名单（`subagent_registry.py:28`）加 `sentiment_sampling`；结论强制带 `sample_size` + 时间窗（prompt 契约 + 维度 JSON schema 加字段）。

### 2.3 内置调度器 + 周报聚合

**目标**：不依赖外部 cron 也能持续运转；产出"本周变化"跨竞品周报（时间序列叙事）。

**2.3.1 内置调度器（轻量，无新硬依赖）**

- 新增 `core/scheduler.py`：`WeeklyScheduler`——daemon 线程 + 配置 `schedule.enabled` / `schedule.interval_hours` / `schedule.cron_expr`（cron_expr 用简单解析器，不引 apscheduler；缺省 interval 模式即可）。每次唤醒调 `api.run_scheduled()`，失败记日志不崩进程（守 doc 54 纪律）。
- 装配：`web_app` 启动时若 `schedule.enabled` 则 `start()`（复用现有 `run_scheduled` 语义，不新起分析路径）；CLI `schedule --daemon` 前台跑。
- 说明：外部 cron 仍可用（`cli schedule` 已是 cron 入口），内置调度器是**可选补充**，二者互斥由配置决定。

**2.3.2 周报聚合（核心产物）**

- 新增 `core/weekly_report.py`：`WeeklyReportBuilder`——读取 `<data_dir>/reports/**/*.json` + `TimelineMemory`（`<data_dir>/memory/timeline.json`）+ `alerts/<date>.md`，聚合近 N 天（配置 `schedule.weekly_window_days`，缺省 7）的跨竞品变化：
  - 本周价格变动（`price_change`）
  - 本周版本/功能发布（`version_release`/`feature_added`）
  - 榜单分数变化（`score_change`）
  - 新增/移除竞品（候选发现差异）
  - 各竞品整体置信度对比表
- 输出：`<data_dir>/reports/weekly/<YYYY-Www>.md` + `.json`（复用 `report_to_dict` 字段命名习惯），`created_at` 起止时间窗标注。
- **接入点**：`facade/api.py::build_weekly_report()`；CLI `weekly` 子命令；`run_scheduled` 末尾可选触发周报（`schedule.weekly_report: bool`）。

## 3. 第 3 层设计：产品化闭环

### 3.1 可视化导出（雷达图 / HTML 分享）

**目标**：输出物不只有 Markdown——可分享、可看图。

**新增 `core/report_visuals.py`**：

- `render_radar(report: ComparisonReport, out_path) -> Path | None`：六维置信度雷达图。**matplotlib 为可选依赖**（pyproject 增 optional extra `visuals = ["matplotlib>=3.7"]`），缺失时 `None` 并记日志（降级不炸）；中文标签注入系统字体黑名单规避（缺字体用英文轴标签）。
- `render_html(report: CompetitorReport | ComparisonReport, out_path) -> Path`：**单文件自包含 HTML**——内嵌 CSS + 报告 markdown 正文 + 结构化数据（`report_to_dict`），用 `marked` CDN 走 `static/` 现有渲染思路但**离线内嵌一份**（拷贝 `marked.min.js`/`DOMPurify.min.js` 到模板或允许 CDN 缺省离线降级），生成 `<data_dir>/reports/competitor/<name>.html` / `comparison/<names>.html`。
- **接入点**：CLI `report --visual` / `--html` 开关；`save_report_markdown` 之后可选触发（`report.export_html: bool` 配置）。

### 3.2 human-in-the-loop 审批节点

**目标**：重要结论入报告前有人工确认门，展示"知道生产系统长什么样"。

**新增 `core/approval_gate.py`**：

- 状态机：`draft → pending_review → approved` / `rejected`（rejected 附原因回灌注释）。
- 触发规则（`ApprovalPolicy`，可配置）：`price_change`、`score_change`、新增竞品、`overall_confidence` 超阈值或任一维度 PARTIAL 低置信（如 `<0.4`）、周报含 high-impact 项。未命中规则的报告直通 `approved`（不打扰）。
- 落盘：报告 JSON 增 `status` / `reviewed_at` / `reviewer_note` 字段（`report_to_dict` 扩展，向后兼容旧 JSON）；未 approved 报告前端标注"待人工确认"徽章，不默认进"正式报告"区。
- **接入点**：CLI `report --approve <name>` / `report --reject <name> --note "..."`；Web 增 `/api/reports/{name}/review` POST（与现有 `/api/reports/{name}/download` 同域）。

### 3.3 告警推送通道

**目标**：`AlertSink` 从"文件+控制台"升级到"可推送"。

- 扩展 `core/alerting.py`：
  - `WebhookAlertSink(url, headers, timeout)`：POST JSON 告警载荷（竞品/kind/summary/old→new/证据 URL/时间），支持企业微信/钉钉/飞书机器人 webhook（同一 JSON 格式，各自适配简单）。
  - `EmailAlertSink`（可选，`EmailAlertSink(host, port, from, to)` 走标准库 `smtplib`，无新依赖）：汇总近 N 条告警发一封。
  - 失败静默降级（记日志不崩 `run_scheduled`），超时读 `CollectorConfig.timeout_seconds`。
- **配置**：`ReportConfig` 增 `alert_push`（webhook 列表）/`alert_email`（可选）字段；`run_scheduled(alert_sink=...)` 组装为复合 sink（`FileAlertSink` + 推送 sink，`CompositeAlertSink` 逐个 emit）。

## 4. 数据流（改造后）

```
[内置调度器 或 外部 cron]
   └─ run_scheduled ── 逐过期竞品 analyze
        ├─ performance → benchmark_scores（结构化榜单源）→ 写 report JSON + Timeline score_change
        ├─ sentiment   → sentiment_sampling（采样源，带 sample_size/时间窗）
        ├─ 报告 JSON（增 status: pending_review/approved + 雷达/HTML 导出）
        ├─ 变更 → report_diff → Alert → CompositeAlertSink（文件 + webhook/邮件推送）
        └─ 到期 → build_weekly_report → reports/weekly/<周>.md + .json（本周变化聚合）
[审批] 待人工确认项 → CLI approve/reject / Web /api/reports/{name}/review
```

## 5. 验证方式

- **单测 benchmark_sources**（`tests/unit/collector/test_benchmark_sources.py`）：mock `httpx`——Terminal-Bench/SWE-bench HTML 表解析成 `BenchmarkHit`、字段缺失容错、非 2xx/超时/解析失败返回可读提示不抛、`build_benchmark_provider` 无开关→None。
- **单测 sentiment_sources**（`tests/unit/collector/test_sentiment_sources.py`）：HN Algolia mock 返回 `SentimentSample`（含 sample_size/时间窗）、Reddit JSON 解析、平台缺失/失败降级、provider 无→None。
- **单测 scheduler**：`WeeklyScheduler` 间隔唤醒调 `run_scheduled`、`enabled=False` 不启动、cron_expr 简单解析器、异常不崩线程（mock api）。
- **单测 weekly_report**（`tests/unit/core/test_weekly_report.py`）：从 timeline.json + alerts + 报告 JSON 聚合出周报（价格/版本/榜单/新增竞品/置信表）、时间窗过滤、无数据空周报、markdown+json 双产物字段。
- **单测 visuals**：`render_radar` 无 matplotlib → None（不炸）；`render_html` 单文件含 markdown 正文 + 结构化数据 + 自包含 CSS（不依赖外网资源或离线降级）。
- **单测 approval_gate**：规则触发（price_change/低置信/新增竞品）→ pending_review；不触发 → approved；approve/reject 状态流转 + reviewer_note 落 JSON；旧 JSON（无 status 字段）向后兼容读为 approved。
- **单测 alerting 推送**：`WebhookAlertSink` mock POST 载荷正确、超时/非 2xx 静默降级；`CompositeAlertSink` 聚合多个 sink 逐个 emit（失败不影响后续）；`EmailAlertSink` mock `smtplib`。
- **集成**：注入假 provider（固定榜单/舆情 hits）→ `run()` 出 performance/sentiment 结构化结论；`run_scheduled` 一周内触发周报 + 推送 + 待审报告标记；未配推送/无 Key → 与现状一致（降级不编造）。
- **回归**：全量 unit suite 绿（含 doc 65 的 40 新用例 + doc 66 用例）；ruff/mypy 改动文件干净。

## 6. 实现优先级与工作量

- 优先级：**高**（补完即"数据管线化 + 产品化闭环"两层闭环，可讲完整社招叙事）。
- 工作量：约 1.5-2 天。
  - `benchmark_sources.py` + 工具注册：0.3 天；
  - `sentiment_sources.py` + 工具注册：0.3 天；
  - `scheduler.py` + `weekly_report.py` + CLI `weekly`：0.4 天；
  - `report_visuals.py`（雷达可选 + HTML 自包含）：0.3 天；
  - `approval_gate.py` + Web 审批接口 + 报告 status 字段：0.3 天；
  - alerting 推送（Webhook/Email/Composite）+ 配置：0.2 天；
  - 测试：0.4 天。
- 前置依赖：无新增硬依赖（图表走 optional extra；邮件走标准库）；榜单/舆情走公开端点或可配 Key。

## 核心技术点总结

- **数据管线化**：榜单/舆情从"LLM 读网页"升级为**结构化源直连**（`BenchmarkSourceProvider`/`SentimentProvider`，对齐 doc 66 `SearchProvider` 策略模式），每次抓取记时间线 → 周报聚合出"本周变化"——私有数据 + 时间序列的护城河成立。
- **内置调度器**：轻量 daemon 线程（无 apscheduler 依赖），与外部 cron 二选一；`run_scheduled` 语义不变。
- **产品化闭环**：雷达图/HTML 自包含分享（图表可选降级）+ human-in-the-loop 审批（`draft→pending_review→approved/rejected`，规则化触发不打扰）+ 告警推送（Webhook/Email，复合 sink 失败不互扰）。
- **评估体系（第 2 层）已完备不再动**：golden set + 真实 LLM 评测 + `--gate` CI，是面试主叙事，本次只补数据与产品两层。
- **不引入假亮点**：所有新配置字段有真消费方（调度/周报/推送/审批都进 `run_scheduled`/CLI/Web 路径），图表缺失/推送失败均显式降级不炸（守 doc 54 纪律）。
