# 设计文档 14 — `resume()` 不续跑，只回读快照即删

> 对应 `implementation_plan.md` 第 11 节问题 16（P0）

## 1. 问题现状

- `facade/api.py:474-482` 的 `resume()` 实现为：

  ```python
  def resume(self, session_id: str) -> CompetitorReport:
      cp = load_checkpoint(session_id)
      if cp is None:
          raise ValueError(f"会话 {session_id} 无 checkpoint，无法恢复")
      report = checkpoint_to_report(cp)
      delete_checkpoint(session_id)
      return report
  ```

- 它只做三件事：**读** checkpoint → 转成报告 → **删** checkpoint。`pending gaps` 没有任何重新执行逻辑。
- 在 `analyze()` 中，checkpoint 仅在 **取消**（`is_cancelled(sid)`）分支下被保留（`api.py:164-184` 返回 `CancelledResult`），正常路径会 `delete_checkpoint`。换言之，能 `resume` 的前提本应是"被取消的会话"，但 `resume()` 并不去跑那些未关闭缺口。
- 与对外承诺矛盾：
  - `cli.py:37-38` 打印 `[提示] n 个缺口未关闭，可用 /resume 继续。`；
  - README / 文档将 `/resume` 描述为"断点续跑"。
  - 实际是"取回已保存的部分结果"，属于**过度承诺**。

## 2. 目标设计

让 `resume()` 成为真正的**断点续跑**：

1. 从 checkpoint 恢复 `gaps`（含已关闭/未关闭状态）、`dimension_results`（已完成维度）与**剩余预算**（`iterations_used` / `max_iterations` / `cost_used` / `cost_limit`）。
2. 仅对 **未关闭的缺口** 真正重跑（复用 `_run_gap` / `_run_gaps`，与 `analyze()` 串行/并行路径一致）。
3. 续跑过程中持续更新 checkpoint；**全部缺口关闭后**才 `delete_checkpoint`，返回完整报告。
4. 若 checkpoint 不存在，保持现有 `ValueError`。

## 3. 模块/接口设计

### 3.1 新增 `resume()` 续跑实现

```python
def resume(self, session_id: str) -> CompetitorReport:
    cp = load_checkpoint(session_id)
    if cp is None:
        raise ValueError(f"会话 {session_id} 无 checkpoint，无法恢复")

    # 1. 重建策略与缺口状态
    strategy = self._strategy_from_checkpoint(cp)   # gaps(含 status) + competitor
    # 2. 重建剩余预算
    iteration_budget = IterationBudget(
        max_iterations=cp.max_iterations,
        cost_limit=cp.cost_limit,
    )
    iteration_budget.used_iterations = cp.iterations_used
    iteration_budget.used_cost = cp.cost_used
    # 3. 预置已完成维度，避免重跑已关闭缺口
    completed = [self._result_from_dict(r) for r in cp.dimension_results]

    # 4. 仅重跑未关闭缺口（串行/并行复用现有路径）
    new_results = self._run_gaps(strategy, iteration_budget, session_id, cp.task)
    ...
    # 5. 合并结果，全部关闭则删除 checkpoint
    pending = [g for g in strategy.gaps if not g.is_closed]
    if not pending:
        delete_checkpoint(session_id)
    return report
```

### 3.2 需要的辅助方法

- `_strategy_from_checkpoint(cp: Checkpoint) -> CompetitorStrategy`：将 `cp.gaps`（dict）还原为 `InfoGap` 列表（保留 `status` / `confidence` / `sources_tried` / `evidence`），组装 `CompetitorStrategy`。
- `_result_from_dict(r: dict) -> DimensionResult`：与 `checkpoint_to_report` 现有的结果重建逻辑复用（建议抽出共享助手）。
- 让 `_run_gaps` 接受"预置已完成结果"，仅对 `not g.is_closed` 的缺口调用 `_run_gap`，并把已关闭维度直接并入 `completed`。

### 3.3 Checkpoint 需要保留缺口状态语义

`Checkpoint.gaps` 已存 `status`（见 `checkpoint.py:329` `GapStatus(g.get("status","open"))`），续跑靠 `g.is_closed` 判断，无需改 schema。

## 4. 接入方式

```
resume(sid)
  → load_checkpoint(sid)
  → 重建 strategy(未关闭缺口) + 剩余预算 + 已完成维度
  → _run_gaps(只跑未关闭缺口, 复用 _run_gap/TacticalLoop)
       → 每缺口 save_checkpoint（增量更新，pending 归零）
  → 全部关闭 → delete_checkpoint(sid) → 返回完整报告
  → 仍被取消 → 保留 checkpoint，返回 CancelledResult（可被再次 resume）
```

## 5. 验证方式

- **单元测试**：
  - 构造含 3 个缺口、1 个已关闭的 checkpoint，`resume()` 后断言只对 2 个未关闭缺口调用了 analyzer，已关闭缺口未重跑。
  - 续跑后 `load_checkpoint` 返回 `None`（已删除）。
- **集成测试**（复用 `tests/integration/test_checkpoint_resume.py` 现有取消→resume 用例并升级）：
  - 慢速分析中取消 → 返回 `CancelledResult` 且 **checkpoint 仍在**；
  - 调用 `resume(sid)` → 完成剩余缺口、返回完整 `CompetitorReport`、checkpoint 被消费（二次 `resume` 抛 `ValueError`，与现状一致）。
- **回归**：`analyze()` 正常完成路径的 `delete_checkpoint` 行为不变。

## 6. 实现优先级与工作量

- 优先级：**高**（P0，承诺能力的真实落地）。
- 工作量：约 1-1.5 天（重建策略/预算 + 续跑调度 + 测试）。
- 依赖问题 15 的注入式测试隔离，使 `resume` 单测可用 mock LLM 离线验证。
