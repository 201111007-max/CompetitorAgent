# 设计文档 10 — ParallelRunner 未接入主流程

> 对应 `implementation_plan.md` 第 11 节问题 10（P2）

## 1. 问题现状

- `core/parallel_runner.py` 只在测试中被使用（grep 确认），`api.analyze()` 用的是**串行** `TacticalLoop`（`api.py:133-139`）。
- README 宣称的"并行子代理"（`review_config.yaml:13` `max_parallel_subagents`）在生产路径**从未启用**。

## 2. 目标设计

1. 将 `ParallelRunner` 接入主流程，并行执行**相互独立的缺口**分析。
2. 并行度可配置（结合设计文档 05 的 `execution.max_parallel_subagents`）。
3. 保持预算控制与取消机制在并行下正确工作。

## 3. 模块/接口设计

### 3.1 并行执行接入（`facade/api.py`）

在 `analyze()` 中，将独立的缺口（不同竞品/维度）分组并行：

```python
def _run_gaps_parallel(self, gaps, session_id):
    runner = ParallelRunner(max_workers=cfg.execution.max_parallel_subagents)
    results = runner.run(
        tasks=[(gap, self._run_single_gap) for gap in gaps],
        on_progress=self._emit_progress,
    )
    return results
```

### 3.2 预算控制并行安全（`core/budget.py`）

- `BudgetController` 的 `used_iterations`/`used_cost` 读写需**加锁**（当前属性无锁读取，见 `budget.py:77-87`）。
- 并行任务共享同一预算，需原子扣减。

### 3.3 取消机制并行（结合设计文档 04）

- 并行任务每轮检查 `is_cancelled(session_id)`，取消时提前终止所有任务。

### 3.4 配置开关

- `execution.mode: single | parallel`，默认 `single`（兼容），`parallel` 时启用 `ParallelRunner`。

## 4. 接入方式

```
analyze(task)
  → 规划出 gaps
  → execution.mode == parallel ?
      → ParallelRunner 并行执行独立 gaps（共享预算 + 取消检查）
      → 汇总结果
  → 否则串行 TacticalLoop
```

## 5. 验证方式

- **单元测试**：`ParallelRunner` 并行执行独立任务，结果正确。
- **集成测试**：并行模式下预算正确扣减、取消能提前终止。
- **端到端**：`mode=parallel` 与 `mode=single` 输出一致，耗时更短。

## 6. 实现优先级与工作量

- 优先级：**中**（P2，性能卖点）。
- 工作量：约 1-2 天。
- 建议先做预算加锁 + 取消检查，再接入并行执行。
