# 设计文档 01 — 多 Agent 名不副实，主流程不走它

> 对应 `implementation_plan.md` 第 11 节问题 1（P0）

## 1. 问题现状

- `team/` 下 4 个 Agent（`CollectorAgent` / `AnalyzerAgent` / `ValidatorAgent` / `ReporterAgent`）只是**普通方法包装**，无独立决策、无自主循环、无记忆。
- `MessageBus`（`team/message_bus.py:38-57`）是**同步进程内 pub/sub**，`publish()` 直接同步调用 handler；topic 常量（`T_STRATEGY`/`T_COLLECTED`/...）定义了但**从未被 subscribe 消费**。
- `TeamOrchestrator.run()`（`team/orchestrator.py:49-62`）是 5 行硬编码顺序调用，无编排逻辑。
- **致命点**：CLI/Web/MCP 全部调用 `api.analyze()`（单 Agent 串行 TacticalLoop），`analyze_team()`（`facade/api.py:196`）**无任何调用方，是死代码**。

## 2. 目标设计

让"多 Agent"成为**真实、可运行、接入主流程**的能力，而非演示旁路。目标：

1. 每个 Agent 具备**独立决策能力**（自主判断是否继续/重试/降级）。
2. `MessageBus` 成为**真正驱动行为**的消息通道（Agent 订阅 topic 并据此行动），而非日志记录器。
3. `analyze_team()` 接入生产入口，作为可选的多 Agent 执行路径。

## 3. 模块/接口设计

### 3.1 Agent 基类（新增 `team/base_agent.py`）

```python
class BaseAgent(ABC):
    def __init__(self, name: str, bus: MessageBus, memory: IFourLayerMemory):
        self.name = name
        self.bus = bus
        self.memory = memory

    @abstractmethod
    def run(self, ctx: AgentContext) -> AgentResult: ...
```

- `AgentContext`：任务、竞品、缺口清单、预算、会话 id。
- `AgentResult`：产出物 + 状态（SUCCESS / RETRY / DEGRADED / FAILED）+ 决策理由。

### 3.2 MessageBus 增强（`team/message_bus.py`）

- 增加**异步队列 + 订阅者注册**，`publish()` 将消息入队，订阅者异步消费。
- 增加 `subscribe(topic, handler)` 真正被 Agent 使用。
- 保留 Envelope 序号审计，但消息必须**驱动行为**。

### 3.3 TeamOrchestrator 增强（`team/orchestrator.py`）

- 从硬编码顺序改为**基于消息的事件驱动**：Collector 产出 → 发布 `T_COLLECTED` → Analyzer 订阅消费 → 发布 `T_ANALYZED` → Validator → Reporter。
- 增加**失败重试与降级决策**：Agent 返回 RETRY 时按策略重试，FAILED 时降级。

### 3.4 接入主流程（`facade/api.py`）

- `analyze_team()` 改为真实可用，并作为 `CompetitorAnalysisAPI` 的可选执行路径。
- 新增配置开关 `execution.mode: single | team`，默认 `single`（保持兼容），`team` 时走多 Agent。

## 4. 接入方式

```
CompetitorAnalysisAPI.analyze(task, mode="team")
  → TeamOrchestrator.run(ctx)
      → CollectorAgent 订阅/发布 T_COLLECTED
      → AnalyzerAgent 订阅/发布 T_ANALYZED
      → ValidatorAgent 订阅/发布 T_VALIDATED
      → ReporterAgent 订阅/发布 T_REPORTED
  → 返回报告
```

## 5. 验证方式

- **单元测试**：每个 Agent 的决策逻辑（重试/降级分支）。
- **集成测试**：`analyze_team()` 走完整消息链路产出报告。
- **端到端**：CLI `--mode team` 与 `--mode single` 输出一致。

## 6. 实现优先级与工作量

- 优先级：**高**（P0，核心卖点）。
- 工作量：约 2-3 天。
- 建议先做 MessageBus 事件驱动 + BaseAgent 基类，再接入 `analyze_team`。
