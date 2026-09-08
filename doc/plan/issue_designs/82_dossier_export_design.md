# 设计文档 82 —— 第三十二轮：竞品档案（Dossier）导出（工单 7）

> 目标：基于现有 `TimelineMemory` + 历史报告 + 知识库，产出**单竞品完整档案**——历史报告索引、价格/版本/跑分变化曲线、证据链接。这是「增量跟踪」叙事的实体产物，也是对外发布的内容形态（工单 12 两周跟踪的收口物）。
>
> 本文档为**设计**（不实现）。
>
> **已确认决策（doc 75 §2）**：按建议执行；输出形态 = Markdown + JSON 双份（与周报惯例一致）。

---

## 1. 问题现状

| 现有资产 | 位置 | 缺口 |
|---------|------|------|
| 竞品时间线 | `memory/timeline_memory.py`（price_change/score_change/version_release/feature_added 事件，含 diff_from/evidence_urls） | 只有事件流，无按竞品的**聚合视图** |
| 历史报告 | `<reports_dir>/*.json`（`WeeklyReportBuilder._load_report_dicts` 已有「按竞品取最新/全量」读取逻辑） | 散落文件，无单竞品时间轴索引 |
| 置信度演进 | 报告内 `overall_confidence`/`terminal_state`/`created_at` | 无跨报告趋势呈现 |
| 知识库 | `CompetitorStore.by_competitor`（含 source_url 的 chunk） | 档案未引用 |
| 现有按竞品查询 | `api.get_history(competitor)`、`GET /api/timeline/{name}`（doc 68 前端已用） | 返回裸数据，无可交付的档案文档 |

## 2. 目标设计

### 2.1 模块与数据模型

```
competitor_agent/core/dossier.py（新）
  @dataclass Dossier
    competitor: str
    generated_at: str
    reports: list[DossierReportRef]        # {created_at, terminal_state, overall_confidence, freshness, md_path}
    confidence_trend: list[tuple[str, float]]   # (日期, overall_confidence) 时间序列
    changes: dict[str, list[dict]]         # price_change / score_change / version_release / feature_added
                                           #   每条含 occurred_at/summary/diff_from/evidence_urls/provenance(若 doc 80 已合入)
    evidence_index: list[dict]             # {source_url, dimension, first_seen, last_seen}（来自知识库 chunk 聚合）
    open_questions: list[str]              # 近 N 份报告 gaps_pending 的并集（去重）

  class DossierBuilder:
    def __init__(self, reports_dir, data_dir, *, timeline: TimelineMemory | None = None): ...
    def build(self, competitor: str, *, window_days: int | None = None) -> Dossier
    def render_markdown(self, dossier: Dossier) -> str
    def write(self, dossier: Dossier) -> tuple[Path, Path]   # <reports>/dossiers/<competitor>.md + .json（原子写）
```

### 2.2 Markdown 档案结构（对外发布形态）

```
# <竞品> 档案（截至 YYYY-MM-DD）
> 覆盖 N 份历史报告 / M 条变化事件 · 数据窗口 [首份报告日期 ~ 今日]

## 1. 置信度演进        # 表格 + 简易 ASCII/内联趋势（复用 doc 67 report_visuals 的可选 matplotlib 降级纪律）
## 2. 价格变化          # [日期] 旧→新（来源 URL）
## 3. 跑分变化          # 分数变动 + provenance 尾注（doc 80 契约；未合入时省略）
## 4. 版本与功能发布    # 时间线列表
## 5. 历史报告索引      # 表：日期/终态/置信度/文件链接
## 6. 证据来源索引      # 去重 source_url 清单（含维度与首见日期）
## 7. 待跟进问题        # gaps_pending 并集
```

### 2.3 入口接线

| 入口 | 形态 |
|------|------|
| CLI | `python -m competitor_agent.cli dossier --competitor cursor [--window-days 90]` |
| API | `CompetitorAnalysisAPI.build_dossier(competitor)`（门面薄路由，doc 78 拆分后落 schedule_service 旁的 report 服务位） |
| Web | `GET /api/dossier/{name}`（JSON）+ 前端档案按钮（doc 68 档案台已有 rail，增入口） |
| 调度 | `run_scheduled` 末尾按配置为当轮竞品刷新档案（`schedule.refresh_dossiers: false` 默认关，避免跟踪期磁盘膨胀） |

## 3. 验证方式

| # | 验收项 | 通过标准 |
|---|--------|---------|
| 3.1 | 聚合正确 | fixture 报告 3 份 + 时间线事件 5 条 → 档案各节计数/排序正确（时间升序） |
| 3.2 | 空态 | 无报告无事件竞品 → 产出含「暂无数据」占位的合法档案（不崩、不编造） |
| 3.3 | 双格式 | .md 与 .json 内容一致（json 为结构化真源，md 为渲染）；原子写（复用 `_write_bytes_atomic`） |
| 3.4 | 入口 | CLI/Web 各一集成用例；`get_history` 行为零变化 |
| 3.5 | 回归 | 全量 pytest + benchmark 门禁 + ruff/mypy 干净 |

## 4. 实现优先级与工作量

P2，约 1 天。依赖：doc 80（provenance 字段可选融合，未合入时档案省略口径列）；被依赖：工单 12（两周跟踪收口产出即本档案）。

## 5. 核心技术点总结

1. **纯聚合零新采集**：Dossier 只读现有三类存储（reports/timeline/knowledge_base），不触网、不调 LLM——成本为零，随时重放。
2. **与周报的分工**：周报 = 时间窗内跨竞品变化（新闻）；档案 = 单竞品全历史（百科）。两者共用读取层但互不依赖。
3. **跟踪叙事的实体证据**：工单 12 结束时，`dossiers/` 目录就是「系统在真实运行」的展示物，直接支撑 README 的素材位。
