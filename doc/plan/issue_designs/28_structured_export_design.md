# 设计文档 28 — 结构化输出 + 定时跑 + 异动告警

> 对应 `implementation_plan.md` §12.3 #8（P2）「输出仅 Markdown」。
> 依赖：`core/report_archiver.py`（已有 .md 落盘）、设计文档 26（时间线 diff / 新鲜度）、27（PricingProfile）。

## 1. 问题现状

- 输出链路为 `report_builder → markdown_renderer`，落盘只有 Markdown（`core/report_archiver.py::save_report_markdown`）。无结构化 JSON / 矩阵导出。
- 无定时跑：`api.analyze()` 只能手动触发，无法"每天对 N 个竞品重爬并对比"。
- 无竞品异动告警：价格 / 功能 / 版本 / 榜单变化不会主动通知。

## 2. 目标设计

1. **结构化 JSON 导出**：每次分析落盘 `reports/competitor/<name>.json`（机器可读：competitor、dimensions、evidence、freshness、pricing.profile、benchmark_scores），与 .md 同名同目录；比较报告另出 `reports/comparison/<names>.json`（品类矩阵数据）。
2. **矩阵 JSON 导出**：`ComparisonReport` 导出"维度 × 竞品"矩阵数组，供前端 / 外部工具消费。
3. **定时跑**：`api.run_scheduled(competitors, cadence)` 或 CLI `schedule`——按 `config.freshness` TTL 周期性对跟踪竞品重分析（可用 cron 包装，不做常驻守护进程）。
4. **异动告警**：`api.report_diff(prev, cur)`（复用设计文档 26 的 `TimelineMemory.diff`）产出异动清单 → `AlertSink` 输出（控制台 / 文件 `reports/alerts/<date>.md` / Web `/api/alerts`），含竞品、变化类型、前后值、证据 URL。

## 3. 模块/接口设计

### 3.1 `core/report_exporter.py`（新增）

```python
def export_competitor_json(report: CompetitorReport, output_dir: Path) -> Path:
    """写 reports/competitor/<name>.json（原子写，对齐 checkpoint 模式）。"""

def export_comparison_json(report: ComparisonReport, output_dir: Path) -> Path:
    """写 reports/comparison/<names>.json：{matrix: [[维度×竞品]], best_per_dimension, summary}。"""

def report_to_dict(report: CompetitorReport) -> dict:
    """稳定 schema：competitor / dimensions[{field,status,confidence,summary,evidence[{url,trust}]}]
       / freshness / pricing.profile / benchmark_scores / created_at / terminal_state。
       （schema 版本号随 HARNESS_VERSION 思路：REPORT_SCHEMA_VERSION = "1.0.0"）"""
```

- `ReportConfig` 增 `export_json: bool = True`、`comparison_dir: str = "reports/comparison"`（`config/loader.py`）。

### 3.2 定时跑 `facade/api.py`

```python
def run_scheduled(self, competitors: list[str] | None = None) -> list[CompetitorReport]:
    """对跟踪竞品执行一次调度轮：过滤未过期（freshness 内）的竞品 → 逐个 analyze。

    cadence 由外部调度器（cron）控制调用时机；本方法只保证"过期才重爬"语义。
    """
```

- CLI `python -m competitor_agent.cli schedule --competitors cursor,copilot`（内部调 `run_scheduled` + `export_competitor_json` + 告警）。

### 3.3 异动告警 `core/alerting.py`

```python
@dataclass
class Alert:
    competitor: str
    kind: str            # price_change / feature_added / version_release / score_change / roadmap_update
    summary: str
    old_value: str = ""
    new_value: str = ""
    evidence_urls: list[str] = field(default_factory=list)

class AlertSink(Protocol):
    def emit(self, alert: Alert) -> None: ...

class FileAlertSink:
    def __init__(self, output_dir: Path): ...   # 追加 reports/alerts/<date>.md
```

- `api.report_diff(prev, cur) -> list[Alert]` 复用 `TimelineMemory.diff`（设计文档 26）映射为 Alert；Web `/api/alerts`（可选，配合设计文档 21 的日志端点风格）。

## 4. 接入方式

```
analyze() 完成 → export_competitor_json（config.report.export_json 开启时）
compare()  完成 → export_comparison_json
schedule 轮  → run_scheduled → analyze → export → report_diff(prev, cur) → AlertSink.emit
报告正文末尾追加"已导出 JSON 路径"提示
```

- 与 `report_archiver`（.md）并存不冲突：JSON 是结构化副本，同目录同名不同扩展名。

## 5. 验证方式

- **单测（导出 schema）**：构造 `CompetitorReport` → `report_to_dict` 字段齐全、JSON 可解析、schema 版本号存在；写盘后文件存在且原子写（无 `.tmp` 残留）。
- **单测（比较导出）**：3 竞品 `ComparisonReport` → `export_comparison_json` 的 matrix 维度×竞品对齐、含 best_per_dimension。
- **单测（diff/告警）**：两次报告价格 20→40 → `report_diff` 产出 `price_change` Alert（old/new/证据）；无变化 → 无 Alert；`FileAlertSink.emit` 落盘追加。
- **集成**：mock LLM + 固定页面，`analyze("Cursor")` 后 `reports/competitor/cursor.json` 存在且含 pricing.profile；`run_scheduled` 只重爬过期竞品。
- **回归**：`export_json=False` 时行为与现状一致；全量测试绿。

## 6. 实现优先级与工作量

- 优先级：**中低**（P2；结构化导出是接入外部工具/CI 的前提，告警是差异化卖点）。
- 工作量：约 2-3 天。
  - `report_to_dict` + `export_competitor_json` / `export_comparison_json`：1 天；
  - `run_scheduled` + CLI `schedule` + 配置：0.5-1 天；
  - `AlertSink` + `report_diff`：0.5 天；
  - 测试 + 文档（api.md）：0.5 天。
- 前置：设计文档 26（diff 复用）、27（PricingProfile 进 schema）。
