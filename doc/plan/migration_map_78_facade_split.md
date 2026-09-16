# doc 78 — facade 拆分迁移映射表（Migration Map）

> 实施日期：2026-09-17。基线 commit：`5a8cfe2`（拆分前最后一个 main 提交）。
> 契约：`CompetitorAnalysisAPI` 公共签名冻结（`tests/unit/facade/_api_signature_baseline_78.json`
> + `test_api_signature_freeze_78.py` 守护）；既有测试断言零改动；benchmark 门禁全绿。

## 1. 模块格局

| 文件 | 职责 | 行数 |
|------|------|------|
| `facade/api.py` | 门面薄路由：`__init__` = 装配 + 三服务实例化；公共方法 = 薄路由 | 300 |
| `facade/assembly.py` | `Dependencies` 只读快照 + `build_dependencies`（原 `__init__` 装配体逐位迁移）+ `ServiceBase`（依赖展开/`_emit`/host 委派）+ `build_default_llm` | 346 |
| `facade/analysis_service.py` | 单竞品分析 + Lead 编排（`_react_loop` 闭包组整体）+ run/analyze/chat/langgraph + 记忆/RAG/复核/采集接线/导出簇 | 1454 |
| `facade/compare_service.py` | compare/discover/`_task_with_sources`/`_finalize_comparison_report`/`_export_comparison_json` | 128 |
| `facade/schedule_service.py` | run_scheduled/build_weekly_report/resume/continue_analysis/cancel/get_history/refresh_stale/report_diff/alerts/档案 | 408 |
| `facade/react_report.py` / `comparison_report.py` / `writer_pass.py` | 不动（doc 78 §2.1） | — |

## 2. 方法迁移映射（旧方法 → 新宿主）

### analysis_service.AnalysisService
`analyze`、`_finalize_competitor_report`、`_plan_resolution`(static)、`_web_search_candidates`、
`_record_timeline`、`_archive_report`、`_export_competitor_json`、`_export_competitor_html`、
`analyze_react`、`analyze_react_report`、`_run_react_loop`、`_run_langgraph_engine`、
`_react_loop`（plan_box/pinned_facts/delegate_collector/_lead_competitor_now/_collect_pinned
闭包组整体，§2.2 规则 1）、`_react_competitor`、`_lead_competitor`、`_react_memory_context`、
`_react_rag_context`、`_rag_ctx_for`、`_react_web_extract`、`_web_extract_checked`、
`_web_extract_for`、`_lead_web_extract`、`_build_kb_recall`、`_ingest_fetched`、
`_check_freshness`、`_select_source`、`_record_memory_success`、`_first_url_for`(static)、
`_save_checkpoint_for_resume`、`analyze_team`、`analyze_team_async`、`analyze_stream`、
`_disambiguate_with_history`、`_last_competitor_from_history`(static)、`run`、`_run_chat`、
`_latest_report_text`、`verify_report`、`_apply_verification_to_approval`、`_emit_report_skeleton`。

### compare_service.CompareService
`compare`、`discover`、`_finalize_comparison_report`、`_export_comparison_json`、`_task_with_sources`(static)。

### schedule_service.ScheduleService
`report_diff`、`run_scheduled`、`_build_alert_sink`、`build_weekly_report`、`_tracked_competitors`、
`_stale_for_schedule`、`_last_report_for`、`cancel`、`resume`、`_resume_task`(static)、
`_reconstruct_gaps_from_checkpoint`(static)、`get_history`、`continue_analysis`、`build_dossier`、`refresh_stale`。

### 留在门面（真实体）
`__init__`（装配委派 + `install_deps` 展开 + 三服务构造）、`_default_llm`（懒缓存单点，
构造下沉 `assembly.build_default_llm`）、`_memory_ctx_for`（测试实例级 patch 接缝）、
`_emit`、`memory`/`timeline` 属性、全部公共方法薄路由、19 个私有薄路由（兼容测试直调/patch，
见 §4）。模块级 `_SUBAGENT_HIDDEN_EVENTS`/`_subagent_event_sink`/`_delegate_section_url`
迁至 analysis_service，`_subagent_event_sink` 经 api.py 再导出（旧导入路径兼容）。

## 3. 跨服务编排（服务间禁止互相 import，经 host=门面路由）

| 调用点 | 链路 |
|--------|------|
| schedule.run_scheduled/resume/refresh_stale → analyze | `self._host.analyze` → api 公共路由 → analysis |
| schedule.resume → `_record_timeline` | `self._host._record_timeline` → api 路由 → analysis |
| analysis.run → `_finalize_comparison_report` | `self._host._finalize_comparison_report` → api 路由 → compare |
| analysis.verify_report → `_build_alert_sink` | `self._host._build_alert_sink` → api 路由 → schedule |
| compare.compare/discover → run | `self._host.run` → api 公共路由 → analysis |
| 服务 → `_default_llm`/`_memory_ctx_for` | `ServiceBase` 委派 `self._host`（懒缓存单点 + 实例级 patch 接缝） |

## 4. patch/直调兼容接缝（api.py 私有薄路由）

测试在 api 实例上 patch/直调的私有成员保留薄路由，服务侧对应调用点经
`self._host.<名>` 委派回门面，**实例级 patch 语义与直调路径零改动**：
`_react_loop`、`_run_react_loop`、`_react_competitor`、`_react_memory_context`、
`_react_rag_context`、`_react_web_extract`、`_web_extract_checked`、`_lead_web_extract`、
`_ingest_fetched`、`_build_kb_recall`、`_export_comparison_json`、`_finalize_comparison_report`、
`_record_timeline`、`_build_alert_sink`、`_apply_verification_to_approval`、`_latest_report_text`、
`_task_with_sources`、`_tracked_competitors`、`_plan_resolution`(static)。

## 5. 测试改动清单（仅 patch 路径，断言零改动）

| 文件 | 改动 |
|------|------|
| `tests/unit/facade/test_chat_gate_64.py` | 类级 `_react_loop` spy 的 patch 目标由 `CompetitorAnalysisAPI` 改为 `analysis_service.AnalysisService`（1 处） |
| （其余 216 个 facade 用例 + 全量单测） | 零改动 |

> 既有偶发记录（与本拆分无因果）：`tests/integration/test_report_export.py::TestReportWebEndpoints`
> 在「unit+integration 合并单进程（xdist 默认分组）」下偶发失败（~40%），断言收到
> `# Cursor 报告`（单测 web FakeAPI 的内存报告文案）而非本测试 tmp 文件内容——
> 该测试类对全局 `web_app._config` 原地 monkeypatch + `report_file_path` 模块函数替换，
> 存在跨套件进程内隔离弱点；新测试文件改变 xdist 分组使其暴露。既定验证口径
> （unit 与 integration/e2e 分开跑）连续多轮全绿；web_app 端点无缓存、facade 改动
> 不触及 web 层。留待后续测试隔离专项处理。

## 6. doc 78 §4.3 行数上限偏差记录（用户拍板：映射优先）

「四服务各 ≤ 600 行」与「`_react_loop` 闭包组整体迁入 analysis_service（§2.2 规则 1 +
文档头批注映射）」算术不可兼得：仅 Lead 编排（~300）+ 单竞品入口（~400）+ 与闭包组互咬的
记忆/RAG/复核/采集簇（~350）即 ~1050 行。用户确认**映射优先**：analysis_service 1454 行
（行数口径 = UTF-8 `len(text.splitlines())`；PowerShell Get-Content 的 GBK 解码会吞行不可作准），
其余文件全部达标；已入 `test_api_signature_freeze_78.py::test_facade_file_size_budget`
守护（api ≤ 300，compare/schedule/assembly ≤ 600，analysis 豁免并指向本表）。

## 7. 回滚定位

拆分基线 `5a8cfe2` 的 `facade/api.py` 为单体版本；回滚 = revert 本轮提交或
`git checkout 5a8cfe2 -- competitor_agent/facade/api.py`（注意同时还原 assembly/三服务
文件与 `test_chat_gate_64.py`）。日志命名空间 `competitor_agent.facade.api` 在四模块
中保持不变（caplog 断言与运维面板兼容）。
