# 设计文档 05 — 配置 YAML 从未被加载

> 对应 `implementation_plan.md` 第 11 节问题 5（P1）

## 1. 问题现状

- `config/review_config.yaml` 定义了预算/终止/维度/限速/可观测性等全部配置，但**生产代码从不读取**，全是硬编码默认值（如 `api.py:64-66` 的 `max_iterations=10, cost_limit=1.0`）。
- `test_config.py` 只验证"YAML 能被 safe_load 解析"，**未验证"注入运行时"**。
- `review_config.yaml:40` 声明的 `rate_limit_per_second`、`max_parallel_subagents` 等**全是死配置**。

## 2. 目标设计

让配置 YAML **真正注入运行时**，实现"一处配置、全局生效"：

1. 启动时加载 `review_config.yaml`，构建类型安全的配置对象。
2. 配置值注入 `CompetitorAnalysisAPI` 及各组件（预算/限速/并行/tracing）。
3. 支持环境变量覆盖（如 `COMPETITOR_CONFIG` 指定路径）。

## 3. 模块/接口设计

### 3.1 配置加载器（新增 `config/loader.py`）

```python
@dataclass
class AppConfig:
    budget: BudgetConfig
    termination: TerminationConfig
    dimensions: DimensionsConfig
    collector: CollectorConfig
    llm: LLMConfig
    memory: MemoryConfig
    report: ReportConfig
    execution: ExecutionConfig   # mode: single|team, max_parallel
    security: SecurityConfig     # cors_origins, auth_token
    observability: ObservabilityConfig  # tracing, metrics

def load_config(path: str | None = None) -> AppConfig:
    # 默认读 config/review_config.yaml，支持环境变量覆盖
```

### 3.2 注入运行时（`facade/api.py`）

`CompetitorAnalysisAPI.__init__` 接受 `config: AppConfig`，用配置值替换硬编码默认：

```python
def __init__(self, config: AppConfig | None = None, ...):
    cfg = config or load_config()
    self._budget = BudgetController(
        max_iterations=cfg.budget.max_iterations,
        cost_limit=cfg.budget.cost_limit,
        ...
    )
```

### 3.3 限流接入（`collector/web_extractor.py`）

- 用 `cfg.collector.rate_limit_per_second` 实现节流（如 token bucket）。
- 用 `cfg.collector.use_playwright` 控制 SPA 采集开关。

### 3.4 并行接入（`core/parallel_runner.py`）

- 用 `cfg.execution.max_parallel_subagents` 控制并行度。

### 3.5 可观测性接入（`observability/`）

- 用 `cfg.observability.tracing/metrics` 开关启用对应能力。

## 4. 接入方式

```
启动（cli/web/mcp）
  → load_config() 加载 review_config.yaml
  → CompetitorAnalysisAPI(config=cfg)
  → 各组件用 cfg 值初始化
```

## 5. 验证方式

- **单元测试**：`load_config()` 正确解析 YAML 为 `AppConfig`。
- **集成测试**：修改 YAML 中 `max_iterations`，确认运行时生效。
- **端到端**：配置 `execution.mode=team` 后走多 Agent 路径。

## 6. 实现优先级与工作量

- 优先级：**中高**（P1，工程化基础）。
- 工作量：约 1-2 天。
- 建议先做 `load_config` + 注入预算/终止，再扩展限流/并行/tracing。
