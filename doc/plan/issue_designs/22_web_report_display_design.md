# 设计文档 22 — Web 端显示 / 导出报告

> 对应 `implementation_plan.md` §15（P0，用户已确认，待办）

## 1. 问题现状

- 用户在 Web UI 输入竞品跑出「报告生成完成，N 维度」后，**页面只显示一行状态，报告正文不展示、也不导出文件**。
- 根因：
  1. `web_app.py` 的 `report` 事件 payload 只带元信息（`web_app.py:142-148`）：`competitor` / `terminal_state` / `overall_confidence` / `dimensions`（维度名列表），**不含 `markdown_report` 正文**。
  2. 前端 `onmessage`（`web_app.py:271-279`）对 `report` 事件只 `addLog(data.message)`，从不渲染正文。
  3. 报告正文仅在分析结束 `archive_session()` 时写入 L1 记忆 JSON（`raw.markdown_report`），用户"看不到也拿不到"；没有独立的 `.md` 文件落盘（CLI `--out` 才写，Web 路径不写 `reports/competitor/`）。
- 配置 `config.report.output_dir`（默认 `reports/competitor`）在 Web 路径**从未被使用**（呼应计划 §11.2 #5 配置加载已修，但报告落盘消费方缺失）。

## 2. 目标设计

1. **Web 端展示报告正文**：`report` 事件的 SSE payload 携带 `markdown_report`，前端把 Markdown 渲染为可读报告（而非仅状态日志）。
2. **一键导出 / 自动落盘**：分析完成自动保存为 `reports/competitor/<竞品>.md`（对齐 `config.report.output_dir`）；前端提供"下载 / 复制"入口。

## 3. 模块/接口设计

### 3.1 SSE 携带报告正文（`web_app.py`）

```python
# _event_generator() 的 report 事件
yield ProgressEvent(
    event="report",
    phase="report",
    progress=1.0,
    message=f"报告生成完成，{len(report.dimension_results)} 个维度",
    payload={
        "competitor": report.competitor.name,
        "terminal_state": report.terminal_state,
        "overall_confidence": report.overall_confidence,
        "dimensions": [r.dimension for r in report.dimension_results],
        "markdown_report": report.markdown_report,   # ← 新增
        "session_id": session_id,                     # ← 新增（供前端/导出使用）
    },
).to_sse()
```

- `markdown_report` 已存在于 `CompetitorReport`（`report_builder.build()` 里 `to_markdown()` 已生成），直接放进 payload，无额外计算。
- 单条 SSE 可能较大（报告几十 KB），但 `text/event-stream` 无单帧上限问题；如超长可拆 `report_chunk` 事件 + `report_end`，本期默认单事件。

### 3.2 自动落盘报告文件

新增 `core/report_archiver.py`（或在 `facade/api.py` 内）：

```python
def save_report_markdown(
    report: CompetitorReport,
    output_dir: Path | None = None,        # 默认 config.report.output_dir
    filename: str | None = None,           # 默认 <competitor>.md
) -> Path:
    """原子写 reports/competitor/<竞品>.md（复用 checkpoint 的原子写模式）。"""
```

- 调用时机：`web_app.py` 分析完成（`_event_generator` 拿到 `report` 后）与 `facade/api.py` 的 `analyze()` 收口处均触发（CLI `--out` 可复用同一函数，消除重复）。
- 路径解析：`output_dir` 未显式给出时取 `AppConfig.report.output_dir`，相对路径相对项目根解析；父目录不存在则 `mkdir(parents=True, exist_ok=True)`。
- 文件名：默认 `<competitor.name>.md`，允许 `{competitor}_{date}.md` 模板（本期固定 `<competitor>.md`）。

### 3.3 下载端点（`web_app.py`）

```python
@app.get("/api/reports/{competitor}")
async def report_file(competitor: str, _: None = Depends(require_auth)) -> FileResponse:
    """返回 reports/competitor/<competitor>.md；不存在返回 404。"""

@app.get("/api/reports/{competitor}/download")
async def report_download(...) -> FileResponse:
    """以 Content-Disposition: attachment 返回，触发浏览器下载。"""
```

- 受 `require_auth` 保护（对齐现有 `/api/*` 端点，问题 8 已加认证）。
- 竞品名规范化：下载路径用 `canonicalize(name)`（`competitor_registry.py`）与落盘文件名保持一致，防路径穿越。

### 3.4 前端渲染与导出（`web_app.py` 的 `index()`）

- **报告面板**：新增 `<div id="report">`，`report` 事件时用轻量 Markdown→HTML 渲染（前端注入受信任的最小解析器，或后端预渲染）。保守方案：后端预渲染 `<div>` 后前端直接注入；若引入第三方渲染库，注意 XSS（用 `wrap_untrusted` / 转义，承接问题 6 思想）。
- **导出入口**：
  - 「复制 Markdown」按钮：`navigator.clipboard.writeText(data.payload.markdown_report)`；
  - 「下载 .md」按钮：跳转 `/api/reports/<competitor>/download`（自动落盘已保证文件存在），或前端 `Blob` 下载兜底。
- **布局**：上方保留实时进度日志（`.event` 列表），下方 `report` 事件后展示报告正文区，二者并存而非互斥。
- **取消 / 失败态**：`cancelled` / `error` 事件清空报告区并提示，不残留上次报告。

## 4. 接入方式

```
analyze 完成 → _event_generator 拿到 CompetitorReport
   ├─ 1) save_report_markdown(report, output_dir=config.report.output_dir)   # 自动落盘
   ├─ 2) report 事件 payload 携带 markdown_report + session_id               # SSE
   └─ 3) 前端 onmessage:
            data.event === "report" → renderReport(data.payload.markdown_report)
                                      + 显示 复制/下载 按钮
```

- `save_report_markdown` 复用原子写（设计文档 09 的 `_atomic_write` 模式），避免写一半损坏。
- 归档照旧：`archive_session()` 仍写 L1 记忆（`raw.markdown_report` 保留），落盘文件为**额外导出**，两者不冲突。

## 5. 验证方式

- **单测（SSE payload）**：`report` 事件 payload 含 `markdown_report`（长度 >0）与 `session_id`；断言与 `CompetitorReport.markdown_report` 一致。
- **单测（落盘）**：`save_report_markdown` 写出 `reports/competitor/<竞品>.md`，内容与报告一致；`output_dir` 缺省时用 `config.report.output_dir`；父目录自动创建；重复写原子替换不损坏。
- **集成**：mock LLM + `FakeExtractor` 跑一次 `analyze`（走 `_event_generator` 链路），断言：
  - `reports/competitor/<竞品>.md` 文件存在且含 `# <竞品> 竞品分析报告`；
  - `report` 事件 payload 的 `markdown_report` 可被 `extract_prediction`（复用评测）解析。
- **Web e2e**：浏览器分析完成后页面渲染出报告正文；「下载 .md」返回 `Content-Disposition: attachment` 文件；`/api/reports/{competitor}` 未鉴权时 401。
- **回归**：`archive_session` 归档 schema 不变（`raw.markdown_report` 仍在）；现有 `web_app` 测试（取消 / auth / history）全绿。

## 6. 实现优先级与工作量

- 优先级：**高**（P0，Web 是用户主要入口，"看不到报告"直接摧毁可用性）。
- 工作量：约 1.5-2 天。
  - SSE payload + `save_report_markdown` + 下载端点：0.5-1 天；
  - 前端渲染面板 + 复制/下载按钮：0.5 天；
  - 测试（SSE payload / 落盘 / 集成 / web e2e）：0.5 天。
- 前置依赖：`config.report.output_dir` 已存在（问题 5 修复后 `AppConfig.report` 就位）；原子写复用设计文档 09 模式；与 §14 日志共用"分析完成"钩子，可一并接。
