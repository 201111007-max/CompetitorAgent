# 设计文档 18 — single / team 两套平行流水线语义分裂

> 对应 `implementation_plan.md` 第 11 节问题 20（P2）

## 1. 问题现状

- 同一 `analyze(task)` 根据 `mode` 走向两条**各自实现**的流水线：
  - **single**：`analyze()` → `_run_gaps` → `_run_gap` → `TacticalLoop` → `GapExecutor`（采集→分析→记忆→checkpoint，已有完整闭环与并行/取消/预算支持）。
  - **team**：`analyze_team()` → `TeamOrchestrator`（Collector→Analyzer→Validator→Reporter）各自实现"采集→分析→记忆"，**不写 checkpoint、无预算强约束、无并行、取消检查方式不同**。
- `facade/api.py` 因此膨胀到 600+ 行，orchestration / RAG / streaming / history 混装，可读性差、易回归。
- 行为分歧点（用户/面试评审可见）：
  1. **取消语义**：single 在取消后保留 checkpoint 供 `/resume`；team 路径无此保证。
  2. **记忆沉淀**：两条路径 `record_skill` / `record_outcome` 调用时机与内容不一致。
  3. **checkpoint**：仅 single 路径有，team 中断即丢进度。
  4. **配置一致性**：streaming（问题 17）另起实例又丢 config，加剧分裂。

## 2. 目标设计

收敛为**统一编排层**，让两条路径共享同一核心闭环，仅在"调度形态"上不同：

- **核心闭环单一来源**：`GapExecutor`（设计文档 12 已抽取）承担"选源→采集→降级→分析→缺口状态更新"。single 与 team 都复用它，保证记忆/预算/取消/checkpoint 行为一致。
- **team 仅作编排差异**：team 的意义是"多角色分工 + 校验/降级决策"，而不是重写采集分析。Collector 只负责采集（仍经 `GapExecutor` 的采集段），Analyzer 复用 `GapExecutor` 分析段，Validator 做质量裁决，Reporter 汇总。
- **取消/checkpoint/预算**：无论 single 还是 team，都经同一 `is_cancelled(sid)` 检查、同一 `save_checkpoint` / `delete_checkpoint`、同一 `BudgetController`。
- `facade/api.py` 瘦身为"入口 + 编排选择"，把 orchestration 逻辑外移到 `core/` 与 `team/` 模块。

## 3. 模块/接口设计

### 3.1 统一编排接口

```python
class AnalysisOrchestrator(Protocol):
    def run(
        self, strategy, iteration_budget, sid, task, *, event_sink, memory, observability
    ) -> list[DimensionResult]: ...
```

- `SingleOrchestrator`：包装现有 `_run_gaps`（串行/并行）。
- `TeamOrchestrator`：事件驱动地驱动各 Agent，但每个 Agent 的"执行"委托 `GapExecutor`，仅在其上叠加角色决策（如 Analyzer 产出后交 Validator 裁决，不达标则 RETRY/降级）。

### 3.2 `CompetitorAnalysisAPI` 改造

```python
def analyze(self, task, ..., mode="team", session_id=None) -> CompetitorReport:
    ...
    orchestrator = self._orchestrator_for(mode)   # single/team
    results = orchestrator.run(strategy, iteration_budget, sid, task,
                               event_sink=self._emit, memory=self._memory,
                               observability=self._observability)
    ...
    # checkpoint/取消/报告 逻辑统一在此（不再分叉）
```

- 取消检查、checkpoint 保存、取消后 `CancelledResult`、完成后 `delete_checkpoint` 统一到 `analyze` 收口（与现有 single 逻辑对齐，team 补齐这些能力）。

### 3.3 `TeamOrchestrator` 复用 `GapExecutor`

- `CollectorAgent.collect` → 调用 `GapExecutor` 的"采集段"（`fetch_candidate` 封装，见设计文档 12）。
- `AnalyzerAgent.analyze` → 调用 `GapExecutor` 的"分析段"。
- `ValidatorAgent` 对 `GapExecutor` 产出的 `DimensionResult` 做 `confidence` / `evidence_ratio` 裁决，不达标触发重试（复用 `GapExecutor` 而非另写逻辑）。

## 4. 接入方式

```
analyze(task, mode)
  ├─ mode="single" → SingleOrchestrator.run → _run_gaps → GapExecutor
  └─ mode="team"   → TeamOrchestrator.run  → [Collector→Analyzer→Validator→Reporter] 各角色委托 GapExecutor
  收口：取消检查 / save_checkpoint / 报告构建 / delete_checkpoint（两条路径共用）
```

## 5. 验证方式

- **行为一致性测试**：同一 `task` 在 `mode="single"` 与 `mode="team"` 下，断言：
  - 缺口关闭集合相同；
  - 记忆中 `skills` / `source_success_rates` 一致；
  - 取消后都保留 checkpoint，且都能被 `resume()` 续跑（依赖问题 16）。
- **重构安全测试**：现有 `tests/integration/test_analyze_flow.py` / `test_team_flow.py` 全绿；`facade/api.py` 行数下降（可用 `wc -l` 设软上限）。
- **回归**：并行（问题 10）、取消（问题 4）、checkpoint 原子性（问题 9）用例不受影响。

## 6. 实现优先级与工作量

- 优先级：**低**（P2，架构整洁 + 行为一致性；非阻塞核心功能）。
- 工作量：约 2-3 天（重构 team 复用 GapExecutor + 统一收口 + 一致性测试）。
- 必须在问题 12（GapExecutor 已存在）、16（resume 统一）、17（streaming 复用实例）之后做，作为编排层收尾重构。建议放在最后，避免与功能修复冲突。
