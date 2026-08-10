# 设计文档 12 — 代码质量：重复代码 / 死代码 / 过度设计

> 对应 `implementation_plan.md` 第 11 节问题 12-14（P3）

## 1. 问题现状

### 12.1 大量重复代码（问题 12）
- 同一"选源→采集→降级→分析"循环被复制三份：
  - `team/collector_agent.py:36-59`（`CollectorAgent.collect()`）
  - `core/tactical_loop.py:54-78`（`TacticalLoop.execute()`）
  - `core/subagent.py:51-70`（`SubAgent.run()`）

### 12.2 死代码（问题 13）
- `web_app.py:57-62` 创建 `CompetitorAnalysisAPI` 实例后**立即丢弃**（无变量接收）。
- `facade/api.py:185-194` 的 `analyze_react()` dispatcher 只注册一个返回硬编码字符串的玩具工具。

### 12.3 过度设计（问题 14）
- `team/message_bus.py` 的 topic/Envelope/history 回放为"多 Agent"叙事搭建完整基础设施，实际只当日志记录器用。

## 2. 目标设计

1. **消除重复**：抽取统一的"缺口执行"核心逻辑，三处复用。
2. **清理死代码**：删除无调用方的玩具代码，或接入真实功能。
3. **简化过度设计**：MessageBus 按真实需求简化，避免为演示而过度设计。

## 3. 模块/接口设计

### 3.1 抽取统一执行核心（新增 `core/gap_executor.py`）

```python
class GapExecutor:
    """统一的"选源→采集→降级→分析"缺口执行逻辑。"""
    def __init__(self, selector, extractor, analyzers, budget, memory):
        ...

    def execute(self, gap, session_id) -> GapResult:
        for candidate in self._selector.select(gap):
            obs = self._extractor.fetch(candidate)
            result = self._analyzers.get(gap.dimension).analyze(obs)
            if result.confidence >= threshold:
                return result
        return self._fallback(gap)  # 降级
```

- `TacticalLoop`、`CollectorAgent`、`SubAgent` 均改为调用 `GapExecutor`。

### 3.2 清理死代码

- `web_app.py:57-62`：删除立即丢弃的实例创建。
- `facade/api.py:185-194`：`analyze_react()` 要么接入真实工具，要么删除（若 ReAct 不作为交付能力）。

### 3.3 简化 MessageBus（`team/message_bus.py`）

- 若多 Agent 采用设计文档 01 的事件驱动，则 MessageBus 按真实订阅/发布需求重构。
- 若多 Agent 不采用，则删除未使用的 topic/Envelope/history 回放，保留最小 pub/sub。

## 4. 接入方式

```
TacticalLoop.execute()  → GapExecutor.execute()
CollectorAgent.collect() → GapExecutor.execute()（多 Agent 场景）
SubAgent.run()           → GapExecutor.execute()（并行场景）
```

## 5. 验证方式

- **单元测试**：`GapExecutor` 覆盖选源/降级/分析分支。
- **回归测试**：重构后 `TacticalLoop` 行为不变（原有测试全绿）。
- **静态检查**：`ruff` / `mypy` 通过，无未使用代码告警。

## 6. 实现优先级与工作量

- 优先级：**低**（P3，代码质量）。
- 工作量：约 1-2 天。
- 建议在 P0/P1 修复后做，避免重构与功能改动冲突。
- 注意：`GapExecutor` 抽取需与设计文档 01（多 Agent）、10（并行）协调，避免重复重构。
