# 设计文档 39 — 预算成本挂钩（真实 LLM 成本记账）

> 触发：2026-08-15 第二轮评审——`BudgetController.cost_limit` 与 `IterationBudget` 是 config 显式能力，
> 但 `GapExecutor` 每次候选源扣**固定常数** `0.01`（gap_executor.py:127），`record_iteration(cost=0.01)`（facade/api.py:517/546）
> 也是常数——**成本上限形同虚设**；`_check_diminishing` 依赖 `delta_tokens` 但全项目恒为 0，**边际递减从未生效**。
> 依赖：`llm/client.py`（`total_cost_usd` 已在设计文档 37 累计）、`core/budget.py`、`core/budget_controller.py`、`core/gap_executor.py`、`facade/api.py`。

## 1. 问题现状

- `GapExecutor.execute`（`core/gap_executor.py:127`）`self._budget.consume(delta_cost=0.01)`：固定 1 分/候选源，与 `LLMClient.total_cost_usd`（`llm/client.py:93`，设计文档 37 按真实 token 计价）**完全脱钩**——LLM 用得多也不多扣。
- `IterationBudget._check_diminishing`（`core/budget.py:61-68`）要求 `delta_tokens` 非 0 才可能触发，但全项目调用 `consume()` 时 `delta_tokens` 恒为 0（gap_executor.py:127 未传）→ **边际递减逻辑从未生效**（死逻辑）。
- `BudgetController.cost_limit`（`core/budget_controller.py:37`，config 默认 $1.0）靠 `total_cost` 判定，但 `record_iteration(cost=0.01)` 传常数 → **cost_limit 永不触顶**（除非迭代量极大）。
- 影响：config 的 `cost_limit_usd` 无实际约束力；长任务无法按真实成本提前止损；"成本控制"作为简历点无数据支撑。

## 2. 目标设计

1. **真实成本记账**：缺口闭环把分析/采集实际消耗的 LLM 成本（`llm.total_cost_usd` 前后差）计入 `IterationBudget.used_cost` 与 `BudgetController.total_cost`。
2. **边际递减生效**：`delta_tokens` 用真实 token 增量（`_log_call` 的 usage 累计），使 diminishing 判定真实生效。
3. **cost_limit 真正约束**：真实成本触顶时提前终止（报告 terminal=PARTIAL / `COST_LIMIT_REACHED`）。
4. **回归安全**：无 LLM / mock LLM（成本恒 0）路径下预算行为与现状完全一致。

## 3. 模块/接口设计

### 3.1 `llm/client.py` 增加成本/用量快照

```python
@property
def snapshot_cost(self) -> float:
    """当前累计成本（total_cost_usd 现值，供前后差记账）"""

@property
def snapshot_tokens(self) -> int:
    """当前累计总 token（prompt+completion，供 diminishing 判定）"""
```

- `_log_call` 已按 usage 累计 `total_cost_usd`；再累加一个 `total_tokens`（prompt+completion），无 usage 时沿用 `_estimate_tokens` 估算（口径与成本一致）。
- `call_func` 注入路径（mock）同样累计（mock 返回无 usage → 估算 token，成本约 0 量级，行为不变）。

### 3.2 `core/gap_executor.py` 闭环补记真实成本

```python
class GapExecutor:
    def __init__(self, ..., llm: LLMClient | None = None) -> None:  # 注入成本来源
        ...
    def execute(self, gap, competitor):
        # 候选源前仍 consume(delta_cost=0, delta_tokens=0) 预检（迭代配额语义不变）
        if not self._budget.consume(delta_cost=0, delta_tokens=0): ...
        ...
        before_cost, before_tok = self._snapshot()
        result = self._analyze(observation, gap, context)
        after_cost, after_tok = self._snapshot()
        self._budget.consume(delta_cost=after_cost - before_cost,
                             delta_tokens=after_tok - before_tok)   # 补记真实增量
```

- 语义对齐 `dota_helper` tactical_loop 的 P0-2 模式（先预检配额、分析后按实际 token 补记，tactical_loop.py:116-127 已有先例）。
- `llm=None` 时快照为 (0,0)，增量恒 0——mock/规则路径行为不变。

### 3.3 `facade/api.py` 真实成本入 BudgetController

```python
# analyze_team / analyze_team_async 的 record_iteration(cost=0.01)
# 改为真实成本增量（llm.snapshot_cost() 前后差；无 LLM 时为 0）
self._budget.record_iteration(cost=max(0.0, cost_now - cost_before))
```

- `BudgetController.cost_limit` 判定不变（现成四条件之一），真实成本入库后自动生效。

## 4. 接入方式

```
facade（self._llm 已持有）→ GapExecutor(llm=self._llm) / record_iteration(真实增量)
  → analyze 中 analyzer 每次 complete 的 usage 经 _log_call 累计
  → 缺口闭环/团队轮次把真实成本并入 IterationBudget 与 BudgetController
  → cost_limit 触顶 → should_stop → terminal=PARTIAL / report 标注原因
```

- 主流程调用方只需传 `llm`（single 路径 `_orchestrator_for` 已持有 `self._llm`；team 路径 `record_iteration` 处改传增量）。
- 无 LLM 环境（`use_llm=False` / mock）：增量恒 0，预算行为与现状逐字节一致（回归安全）。

## 5. 验证方式

- **单测（真实成本记账）**：mock `call_func` 每次 complete 递增 `total_cost_usd`（如 0.1/次）→ GapExecutor 闭环后 `budget.used_cost` ≈ 真实增量（非固定 0.01）；不注入 llm 时 `used_cost` 保持 0（回归）。
- **单测（边际递减）**：注入每次返回大 token 的 LLM → 达到 `diminishing_threshold` 后 `consume` 返回 False（触发递减）；小 token 不触发。
- **单测（cost_limit 约束）**：mock LLM 成本递增使 `BudgetController.total_cost` 触顶 → `should_stop` 返回 `COST_LIMIT_REACHED`，报告 `terminal=PARTIAL`。
- **回归**：既有 mock（成本恒 0）预算/终止测试全绿；`test_budget_termination.py` 语义不变。

## 6. 实现优先级与工作量

- 优先级：**中高**（"成本上限"是 config 显式能力，必须真实生效，否则是简历谎言）。
- 工作量：约 0.5 天。
  - `snapshot_cost/snapshot_tokens` + `_log_call` 累计：0.15 天；
  - GapExecutor 补记 + facade record_iteration 改真实增量：0.2 天；
  - 测试：0.15 天。
- 前置：设计文档 37（`total_cost_usd` 已有）；独立于 38/40/41/42，可插空实施。
