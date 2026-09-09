# 设计文档 80 —— 第三十轮：跑分口径 provenance（工单 6：数据陷阱的系统级防线）

> **实施说明（2026-09-09，全链路落地）**：
> ① **共享契约**（`domain_types/benchmark.py`）：`provenance_note`（`[口径: 第三方实测·swebench·scaffold=v2.1·model=…·collected=…date]`，未声明显式 `[口径未声明]`）/ `provenance_note_from_entry` / `provenance_complete`（source_type+model_version 齐全）/ `first_benchmark_entry` / `has_vendor_self_reported`。collected_at 语义由既有 `fetched_at` 承担（不新增重复字段）。
> ② **采集**：`BenchmarkHit` 增 `source_type`（默认 third_party）/`provider_name`/`scaffold_version`/`model_version`（to_dict 同步）；`_HEADER_ALIASES` 增 scaffold/harness/version 别名列，`_parse_leaderboard_table` 解析落值（解析不到留空——留空即诚实）；`TableBenchmarkProvider` 增 `source_type` 参数（厂商自报源预留接入位 §2.3，本设计零新增联网源）。
> ③ **消费点标注**：`benchmark_scores` 工具每行尾注（str→str 契约不变）；performance 子 Agent 与候选子 Agent prompt 增口径纪律段（performance 专属，其他维度 prompt 零变化保 mock 确定性）；`MarkdownRenderer` performance 段厂商自报条目前加 `> ⚠ 以下含厂商自报口径数据，未经第三方复核`（结构性区分）；`TimelineMemory._summarize_change` performance 事件摘要强制携带口径尾注（无口径 → 「口径未声明」）——周报 `score_changes` 行复用事件摘要**自动携带**（零改动）；`report_diff` 对口径不完整（缺 source_type/model_version）的 score_change 告警降级 `severity="info"`（Alert 增 severity 字段，默认 warn 行为不变，to_dict/Console/File 透传）。
> ④ **测试**：`test_provenance_80.py` 23——契约助手/解析（带口径列落值 + 无列留空）/工具尾注/渲染 ⚠/时间线尾注（含未声明）/告警降级与 complete 保持 warn/prompt 纪律段/周报行携带；相关既有 51 用例（alerting/renderer/timeline/freshness/benchmark_sources/weekly）+ skill 注入/benchmark extract 全绿。

> 目标：coding agent 领域最大的数据陷阱是「跑分不可比」（厂商自报 vs 第三方实测、scaffold/模型版本差异）。本设计给每条跑分记录强制携带 provenance 元数据，并在报告/时间线/告警全链路显式标注口径——把「数据可信」做成系统级能力而非人工注意。
>
> 本文档为**设计**（不实现）。
>
> **已确认决策（doc 75 §2）**：按建议执行；投入产出比进入前三。

---

## 1. 问题现状

```
collector/benchmark_sources.py（doc 67 落地，已核对）：
  BenchmarkHit           # 现有字段：model/score/rank/date（无任何口径信息）
  BenchmarkSourceProvider(ABC)  # TableBenchmarkProvider / SweBenchProvider / TerminalBenchProvider / AiderProvider
  benchmark_scores(benchmark)   # MCP/ReAct 工具，performance 维度子 Agent 白名单成员
下游消费：
  performance 子 Agent → REPORT_SCHEMA.details.benchmarks
  MarkdownRenderer 渲染 performance 段
  TimelineMemory score_change 事件 → 周报「榜单分数变化」（high_impact 触发项）
缺口：
  ① hit 无 source_type——厂商自报与第三方实测不可区分；
  ② 无 scaffold_version / model_version——不同 scaffold 下的分数直接可比是伪等价；
  ③ 渲染无口径标注——读者无法知道「52.4%」怎么来的；
  ④ score_change 告警不带口径——分数变化可能只是换榜/换模型版本，非真实涨跌。
```

---

## 2. 目标设计

### 2.1 数据模型扩展（全部带默认值，向后兼容）

```python
@dataclass
class BenchmarkHit:
    model: str
    score: float
    rank: int | None = None
    date: str = ""
    # provenance（新增，本设计核心）
    source_type: str = "third_party"      # vendor_self_reported | third_party
    provider_name: str = ""               # swebench / terminalbench / aider / ...
    scaffold_version: str = ""            # 榜单页声明的 harness/scaffold 版本（解析不到留空）
    model_version: str = ""               # 被测模型版本（与 model 名分离，空 = 未声明）
    collected_at: str = ""                # 采集时间 ISO（provider 落地时打）
```

各 provider 实现填写：现有 4 个 provider 全部 `third_party`（SWE-bench/Terminal-bench/Aider 榜单均第三方）；`scaffold_version`/`model_version` 从榜单表头/脚注解析（`_normalize_header` 别名映射扩展），解析不到留空——**留空即诚实，不编造**（doc 47 纪律）。

### 2.2 全链路标注

| 消费点 | 标注形态 |
|--------|---------|
| `benchmark_scores` 工具输出文本 | 每行尾部 `[第三方实测·swebench·scaffold=v2.1·collected=2026-09-08]`；未声明字段省略 |
| performance 子 Agent prompt | 增指引：「引用跑分必须复述口径；无 provenance 的分数标注『口径未声明』」 |
| `MarkdownRenderer` performance 段 | 厂商自报数据行前加 `> ⚠ 以下为厂商自报口径，未经第三方复核`（结构性区分，非逐行徽标） |
| `TimelineMemory` score_change 事件 | event payload 携带 provenance 字段；周报 score_changes 行带口径尾注 |
| 告警 sink | score_change 触发时 provenance 不完整（缺 source_type/model_version）→ 告警降级为 info 级（防口径变化误报） |

### 2.3 厂商自报源的接入位（预留）

`build_benchmark_provider` 工厂保持 provider 注册表模式；未来接入厂商自报页（如官方 blog 跑分）只需新 provider 标 `source_type="vendor_self_reported"`——本设计**不新增任何联网源**，只建立口径契约。

---

## 3. 接入方式

- `collector/benchmark_sources.py`：`BenchmarkHit` 扩字段 + 各 provider 解析/落值；`_normalize_header` 别名表增 scaffold/model 版本列。
- `mcp_server/tools/web_tools.py::benchmark_scores`：输出格式化加口径尾注（str→str 契约不变）。
- `agent/prompts/react_system.py`：performance 子 Agent 系统提示增口径指引段。
- `core/markdown_renderer.py`：渲染 performance details 按 `source_type` 分组。
- `memory/timeline_memory.py` / `core/weekly_report.py`：事件与周报行透传 provenance。
- `report_builder`/REPORT_SCHEMA：`details.benchmarks` 条目透传 provenance 字段（schema properties 增可选键）。

## 4. 验证方式

| # | 验收项 | 通过标准 |
|---|--------|---------|
| 4.1 | provider 解析 | fixture HTML 含 scaffold/model 列 → 解析落值；不含 → 留空不报错（既有 provider 用例扩展） |
| 4.2 | 工具输出 | benchmark_scores 文本含口径尾注；无 provenance 时显示『口径未声明』 |
| 4.3 | 渲染 | 厂商自报块带 ⚠ 引导行；第三方实测无该行（renderer 单测） |
| 4.4 | 时间线/周报 | score_change 事件含 provenance；周报行带尾注（weekly 用例扩展） |
| 4.5 | 告警降级 | 口径缺失的 score_change → info 级（alerting 单测） |
| 4.6 | 回归 | 全量 pytest + benchmark 门禁 + ruff/mypy 干净；mock 确定性不受影响（BenchmarkMockLLM 固定返回含 provenance 的样例） |

## 5. 实现优先级与工作量

P1，约 1 天。依赖：无；被依赖：doc 82（Dossier 的跑分变化曲线直接复用带 provenance 的事件）、doc 76（golden 断言的 performance 类断言可引用口径）。

## 6. 核心技术点总结

1. **留空即诚实**：解析不到的口径字段留空并在展示层显式声明「口径未声明」——与 doc 47「不编造」纪律同源。
2. **告警降级是点睛**：口径不完整的异动只发 info，防止「换模型版本」被当成「竞品暴涨」制造告警疲劳。
3. **契约先行**：本设计不接入任何新数据源，先把 provenance 契约铺满全链路（采集→工具→报告→时间线→告警），厂商自报源未来即插即用。
