# 设计文档 78 —— 第二十八轮：facade/api.py 拆分 + 并发压测（工单 8 + 9'）

> **实施说明（2026-09-09，§2.3 压测落地 / §2 拆分待实施）**：
> ① **并发压测 ✅**（新 `tests/evaluation/test_concurrency_stress.py`，5 用例 11.6s）：DelegateRunner 满负荷 6 并发 + 脚本化子 Agent（固定调用次数/文本长度 → 逐调用成本确定性）——**A1 成本恒等**（并行 vs 串行同负载 `total_cost_usd` round(,9) 逐位一致，容忍求和顺序）、**A2 无丢失**（runner 6/6 状态完成 + compare 6 候选 `delegate_collector` 全收集）、**A3 wall 收敛**（并行 < 串行×0.6，防假并行）、**A4 取消传播**（取消信号贯穿编排 60s 内终止）。asyncio 迁移维持否决不实施。
> ② **facade 拆分 📝 待实施**（1.5 天工作量，建议独立会话执行）：方法清点已完成（api.py 2063 行 / ~50 方法；迁移映射：schedule 簇 run_scheduled/build_weekly_report/get_history/resume/refresh_stale → schedule_service；compare/discover/_task_with_sources/_export_comparison_json → compare_service；Lead 编排 `_react_loop` 闭包组整体 → analysis_service；`__init__` 装配 → assembly.Dependencies）。验收三件套不变：签名冻结 + 既有断言零改动 + benchmark 全绿。

> 目标：① 把 ~1700 行的 `facade/api.py`（god object）按职责拆为「门面路由 + 四个服务模块」，`CompetitorAnalysisAPI` 公共签名逐位不变；② 落地并发压测断言（工单 9 降级后的保留项）：`max_parallel_subagents` 满负荷下成本核算误差 = 0。
> **本设计包含一次显式否决**：asyncio 迁移被砍（doc 75 §1 工单 9——论据不成立 + 改动面叠加），本文档只做纯重构 + 压测。
>
> 本文档为**设计**（不实现）。
>
> **已确认决策（doc 75 §2）**：每工单一分支；验收 = 外部行为零改动 + 既有全量测试断言不改动 + benchmark 全绿。

---

## 1. 问题现状

`facade/api.py` 当前承载全部职责（已核对的实际分节）：

| 现有职责段 | 代表成员 | 规模 |
|-----------|---------|------|
| 依赖装配 | `__init__`（llm/memory/retriever/ingester/timeline/event_sink/tracer/budget/alert sink/extractor…约 20 个依赖） | ~200 行 |
| Lead 编排 | `_react_loop`（plan_box/pinned_facts/delegate_collector 三组闭包互咬）、`_run_react_loop`、`_react_competitor`、`_lead_web_extract`、`_subagent_loop` | ~300 行 |
| 分析入口 | `run/analyze/analyze_react_report/analyze_stream/_run_chat/_run_langgraph_engine` | ~400 行 |
| 对比/发现 | compare/discover 入口、`_web_search_candidates`、comparison 组装路由 | ~250 行 |
| 记忆/RAG/时间线 | `_memory_ctx_for/_rag_ctx_for/_build_kb_recall/_ingest_fetched/_record_timeline` | ~250 行 |
| 复核工具装配 | validate_facts/detect_conflict/check_freshness/select_source 工厂 | ~100 行 |
| 调度/周报/历史 | `run_scheduled/build_weekly_report/get_history/resume` | ~200 行 |

问题：任一改动都在同一文件冲突；评审/面试官翻到即扣分；Lead 编排闭包与入口路由耦合导致测试 monkeypatch 范围过大。

---

## 2. 目标设计

### 2.1 拆分结构（facade 包内，不建新顶层包）

```
facade/
├── api.py               # 门面：CompetitorAnalysisAPI 保留，方法体 = 薄路由（≤300 行）
├── assembly.py          # 依赖装配：build_dependencies(config, llm, ...) → Dependencies dataclass
├── analysis_service.py  # 单竞品分析 + Lead 编排（_react_loop 全家 + run/analyze/chat/langgraph 路径）
├── compare_service.py   # compare/discover/aggregate 路由 + comparison 组装
├── schedule_service.py  # run_scheduled/weekly/resume/get_history/alerts
├── react_report.py      # （已存在）不动
└── comparison_report.py # （已存在）不动
```

### 2.2 拆分规则（防「按行数均分」）

1. **闭包随编排走**：`_react_loop` 内 `plan_box`/`pinned_facts`/`delegate_collector`/`_lead_competitor_now`/`_collect_pinned` 是一组互咬闭包，**整体**迁入 `analysis_service`，不拆散。
2. **共享依赖显式化**：`assembly.py` 产出 `Dependencies`（llm/memory/retriever/ingester/timeline/builder/config/event_sink/tracer/budget…只读快照），四个服务构造时注入；服务间**禁止**互相 import（门面统一编排）。
3. **签名冻结**：`CompetitorAnalysisAPI` 的公共方法（run/analyze/analyze_react_report/analyze_stream/discover/compare/get_history/run_scheduled/build_weekly_report/resume/memory/timeline 属性…）**名称、参数、返回类型逐位不变**；web/CLI/MCP/benchmark 四入口零改动。
4. **迁移映射表**（实施时登记进 `doc/plan/migration_map.md` 风格的表）：`旧方法 → 新宿主`，供 review 与回滚定位。
5. 测试不改断言：现有 `tests/unit/facade/*` 的 monkeypatch 目标若指向 `api.py` 私有名，允许在**测试文件顶部**统一改 patch 路径（行为断言一字不动），在 PR 描述中列明。

### 2.3 并发压测（工单 9'，半天）

```python
# tests/evaluation/test_concurrency_stress.py（新）
场景：BenchmarkMockLLM + max_parallel_subagents=6，一次 compare 任务同时委派 6 个候选子 Agent，
     每子 Agent 固定 LLM 调用次数（脚本化）。
断言：
  A1 成本恒等：runner 完成后 llm.total_cost_usd == 各线程单独累加的理论和（误差 == 0.0，浮点用 ==，因加法顺序需稳定——
     压测中 _cost_lock 已保证原子，但加法顺序不保证 → 断言 round(a,9)==round(b,9) 并另设「理论值按 permutation 枚举一致」检查）
  A2 无丢失：delegate_collector 键数 == 6；全部 status ∈ {done}
  A3 wall 收敛：并行 wall < 串行 wall × 0.6（线程池确实并发，防「假并行」回归）
  A4 取消传播：session cancel 后全部子 Agent 在 timeout 内终止
```

**明确不做**：asyncio 迁移、LLMClient 改异步、事件循环改造。压测同时是面试叙事素材（「我们测过并发下的成本正确性」）。

---

## 3. 接入方式

- `api.py` 顶部 `from .assembly import build_dependencies`；`__init__` 缩为「装配 + 四服务实例化 + 公共方法路由」。
- 循环依赖防护：assembly 不 import 任何 service；services 不 import api。
- CLI/Web/MCP/benchmark：零改动（依赖签名冻结）。
- LangGraph 路径（`_run_langgraph_engine`）随 analysis_service 迁移，`run_langgraph` 调用形态不变。

## 4. 验证方式

| # | 验收项 | 通过标准 |
|---|--------|---------|
| 4.1 | 行为不变 | 全量 pytest 断言零改动（仅允许 patch 路径调整，PR 列明）；benchmark 门禁 10/10 全绿 |
| 4.2 | 签名冻结 | `inspect.signature` 快照单测：公共方法签名与拆分前基线逐位一致 |
| 4.3 | 文件规模 | api.py ≤ 300 行；四服务各 ≤ 600 行；无 `api` 反向 import |
| 4.4 | 压测 | A1~A4 全绿并入 evaluation 测试组 |
| 4.5 | 静态检查 | ruff + mypy 干净；`doc/plan/migration_map.md` 迁移表完整 |

## 5. 实现优先级与工作量

P2，拆分 1.5 天 + 压测 0.5 天。依赖：无（但建议在工单 1/2 合入后进行，减少并行冲突）；被依赖：doc 79/80/82 的接线改动将在拆分后的新宿主上做。

## 6. 核心技术点总结

1. **重构的验收标准先于重构本身**：「签名冻结 + 断言零改动 + benchmark 全绿」三件套让 1700 行拆分变成低风险机械活。
2. **闭包组整体迁移**是唯一有技术含量的部分——拆散 `plan_box`/`pinned_facts` 会把隐性时序依赖变成显性 bug。
3. **压测断言 A1 的浮点细节**：锁保证原子性但不保证加法顺序 → 断言写法必须容忍顺序差异（round 或集合枚举），否则压测本身不稳定。
4. asyncio 否决留痕于 doc 75：同一段代码不做两次大手术。
