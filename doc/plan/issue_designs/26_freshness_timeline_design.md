# 设计文档 26 — 新鲜度 / 陈旧度 + 定时重爬 + 竞品时间线

> 对应 `implementation_plan.md` §12.2 #5（P1）「无新鲜度/陈旧度管理」与 §12.3 #7（P2）「无趋势/时序」。
> 依赖：`core/checkpoint.py`、`memory/*`、设计文档 23（GitHub Releases 数据源）。

## 1. 问题现状

- `roadmap` 维度只抓官方 changelog URL（`source_selector._DIMENSION_LINK_KEY: roadmap → docs/changelog/home`），无真正的发布/版本追踪。
- 无"结论已 N 天"检测、无自动重爬；报告是时间点快照，无竞品变化追踪（"Cursor 于 X 日加入 background agents"）。
- 四层记忆（`memory/four_layer_memory.py`）存 source 成功率与技能沉淀，**无时序数据**；`checkpoint.py` 只保存单次分析快照。
- `session_archive` 存档含 `created_at` 但无跨会话 diff 能力。

## 2. 目标设计

1. **新鲜度标注**：每次分析产出 `ReportFreshness` 元数据（`collected_at`、各维度 `age_days`、数据源抓取时间）；超过维度 TTL 时报告标 `⚠️ 数据可能过期` 并提示 `re-analyze`。
2. **陈旧度检测 + 定时重爬**：`api.refresh_stale()` 扫描记忆/存档中过期报告按维度 TTL 自动重爬；提供 CLI `re-analyze --stale` 与配置 `config.freshness.dimension_ttl_days`。
3. **竞品时间线**：新增 `timeline` 记忆——跨分析 diff，把"版本发布 / 功能新增 / 价格变化 / 榜单变化"记为时间线事件；报告含 `## 竞品时间线` 段落（近 N 次变化，带日期与证据 URL）。
4. **趋势视图**：同一竞品多次分析后可绘制简单趋势（价格 / 榜单分数 / 功能覆盖数随时间），Markdown 表格输出，喂给设计文档 28 的结构化导出。

## 3. 模块/接口设计

### 3.1 新鲜度元数据 `domain_types/freshness.py`

```python
@dataclass
class ReportFreshness:
    analyzed_at: datetime
    dimension_ages: dict[str, float]     # dimension → 距最近抓取的天数
    source_retrieved_at: dict[str, datetime]  # source_name → 抓取时间
    stale_dimensions: list[str]          # age > ttl 的维度

    def markdown_note(self) -> str: ...
```

- 分析时由 `GapExecutor` 汇总各 `SourceEvidence.retrieved_at` 生成，附到 `CompetitorReport.freshness`。

### 3.2 陈旧度配置 `config/loader.py`

```python
@dataclass
class FreshnessConfig:
    dimension_ttl_days: dict[str, int] = field(default_factory=lambda: {
        "pricing": 7, "performance": 14, "feature": 30,
        "ecosystem": 30, "sentiment": 7, "roadmap": 14,
    })
    refresh_check_enabled: bool = True
```

### 3.3 `facade/api.py::refresh_stale`

```python
def refresh_stale(self, ttl_override: dict[str, int] | None = None) -> list[CompetitorReport]:
    """扫描记忆/存档中过期报告，按维度 TTL 逐竞品重分析，返回刷新后的报告。"""
```

- 实现：遍历 `FourLayerMemory.list_sessions()` → 读 `raw.markdown_report` 元数据/freshness → 过期则 `self.analyze(competitor, ...)`；并发安全沿用 `execution.mode`。

### 3.4 时间线记忆 `memory/timeline_memory.py`

```python
@dataclass
class TimelineEvent:
    competitor: str
    event_type: str        # version_release / feature_added / price_change / score_change
    summary: str
    occurred_at: str
    evidence_urls: list[str]
    diff_from: str | None  # 与上一次的对比基线

class TimelineMemory:
    def append(self, event: TimelineEvent) -> None: ...
    def events(self, competitor: str, limit: int = 20) -> list[TimelineEvent]: ...
    def diff(self, prev: CompetitorReport, cur: CompetitorReport) -> list[TimelineEvent]:
        """对两次报告做维度级 diff：价格/功能/榜单/版本变化 → 事件。"""
```

- 数据落盘 `~/.competitor_agent/memory/timeline/`（JSON，原子写对齐 `checkpoint`）。
- 报告渲染：`markdown_renderer` 新增 `render_timeline(events)` 输出 `## 竞品时间线` 表。

### 3.5 roadmap 升级

- `roadmap` 维度路由到 GitHub Releases（设计文档 23）产出版本时间线，替换"仅 changelog 页抓取"。

## 4. 接入方式

```
analyze() 完成 → 存 freshness 元数据 + TimelineMemory.diff(上一份, 本次) → 追加事件
CLI: python -m competitor_agent.cli re-analyze --stale [--all]
     python -m competitor_agent.cli timeline <competitor>
Web: /api/timeline/{competitor}（可选，配合设计文档 28 的导出）
config.freshness.dimension_ttl_days 注入 refresh_stale 的 TTL 判定
```

- 与四层记忆、checkpoint 并存：timeline 是新增独立记忆类型，不破坏现有 L1-L4 语义。

## 5. 验证方式

- **单测（freshness）**：构造不同 `retrieved_at` 的 evidence → `ReportFreshness` 正确计算 age、标出 stale 维度、`markdown_note` 含过期提示。
- **单测（diff/时间线）**：两次构造报告（价格 20→40、功能 +1、榜单 +3%）→ `TimelineMemory.diff` 产出 3 类事件；同值不产生事件（防噪声）。
- **单测（refresh_stale）**：mock memory 含过期/未过期会话 → 只重爬过期者，返回报告数正确；`ttl_override` 生效。
- **集成**：`analyze("Cursor")` 两次（第二次改 mock 数据）→ 报告含 `## 竞品时间线`，事件带日期与证据 URL。
- **回归**：无 timeline 记忆 / 首次分析（无 prev）不产生 diff、不报错；全量测试绿。

## 6. 实现优先级与工作量

- 优先级：**中**（P1；新鲜度影响"结论可信度"，时间线是差异化卖点）。
- 工作量：约 2-3 天。
  - `ReportFreshness` + 采集时间追踪：0.5 天；
  - `TimelineMemory` + diff：1 天；
  - `refresh_stale` + CLI + 配置：0.5-1 天；
  - 渲染 + 测试：0.5 天。
- 前置：设计文档 23（GitHub Releases 供 roadmap）；时间线 diff 复用于设计文档 28 的异动告警。
