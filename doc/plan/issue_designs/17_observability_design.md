# 设计文档 17 — 可观测性配置（tracing/metrics/langfuse）无实现

> 对应 `implementation_plan.md` 第 11 节问题 19（P1）

## 1. 问题现状

- `config/loader.py:86-92` 的 `ObservabilityConfig` 声明了完整能力：

  ```python
  @dataclass
  class ObservabilityConfig:
      log_level: str = "INFO"
      tracing: bool = True
      metrics: bool = True
      langfuse_enabled: bool = False
      langfuse_public_key_env: str = "LANGFUSE_PUBLIC_KEY"
      langfuse_secret_key_env: str = "LANGFUSE_SECRET_KEY"
  ```

- 全仓**没有任何消费方**：
  - grep `tracing` / `metrics` / `langfuse` 仅出现在 `loader.py` 定义与 `AppConfig` 装配处；
  - 唯一存在的 `observability/logger.py` 仅做普通日志封装，未读取 `ObservabilityConfig`、未导出 trace、未暴露 metrics、未接入 langfuse。
- 后果：配置项与文档（及 README 卖点）宣称的"链路追踪 / 指标 / Langfuse 评测可视化"**全部未落地**，属于**假亮点**。运维评审者按配置开启 `tracing: true` 后无任何可观测产出。

## 2. 目标设计

二选一，且必须二选一（不能留着"看起来支持"却无实现的配置）：

**方案 A（接入真实能力，推荐）**：让配置驱动实际行为。
1. `log_level` 真正作用于根 logger（`logging.getLogger("competitor_agent").setLevel(...)`）。
2. `tracing=True` 时把 `ProgressEvent` / 各阶段耗时/缺口结果写入结构化 trace（至少本地 JSONL，可选 OpenTelemetry span）。
3. `metrics=True` 时暴露计数器（分析次数、缺口关闭率、取消率、平均迭代），CLI/Web 提供 `--metrics` / `/api/metrics` 端点。
4. `langfuse_enabled=True` 时把报告与 trace 上报 Langfuse（评测可视化），用环境变量 key。

**方案 B（削除）**：若本期不做可观测性，直接从 `ObservabilityConfig` 与 `review_config.yaml` 删除 `tracing` / `metrics` / `langfuse_*` 字段，保留 `log_level`，避免虚假承诺。

## 3. 模块/接口设计（方案 A 示意）

### 3.1 配置消费入口（`observability/`）

```python
class Observability:
    def __init__(self, cfg: ObservabilityConfig):
        logging.getLogger("competitor_agent").setLevel(cfg.log_level)
        self._tracing = cfg.tracing
        self._metrics = MetricsRecorder() if cfg.metrics else None
        self._langfuse = LangfuseSink(cfg) if cfg.langfuse_enabled else None

    def emit_event(self, event: ProgressEvent, session_id: str) -> None:
        if self._tracing:
            self._trace_log.append(...)          # 结构化 trace
        if self._metrics:
            self._metrics.incr("events", tags={"phase": event.phase})
        if self._langfuse:
            self._langfuse.trace(event, session_id)
```

### 3.2 在 `CompetitorAnalysisAPI.__init__` 装配

```python
self._observability = Observability(self._config.observability)
```

并把 `self._emit`（现有 `ProgressEvent` 派发）接到 `self._observability.emit_event`，使所有阶段（strategic / tactical / report / cancelled）自动进入 trace 与 metrics。

### 3.3 Metrics 暴露

- 新增 `CompetitorAnalysisAPI.metrics_snapshot() -> dict`；
- Web 增加 `GET /api/metrics`（受问题 8 的 `require_auth` 保护）；
- CLI 增加 `--metrics` 打印汇总。

## 4. 接入方式

```
AppConfig.observability → Observability(...)
                            ↑ CompetitorAnalysisAPI.__init__
self._emit(event) → observability.emit_event(event, sid)
                      → trace (JSONL/OTel) + metrics counter + langfuse(可选)
```

## 5. 验证方式

- **配置生效测试**：
  - `ObservabilityConfig(log_level="DEBUG")` 后断言根 logger 级别变化；
  - `tracing=True` 时一次 `analyze()` 后在 trace 记录中能找到 `phase_start/phase_complete/report` 事件；
  - `metrics=True` 后 `metrics_snapshot()` 含 `events` / `analyses` 计数且 >0。
- **Langfuse 集成测试**：用假 key / mock client 验证 `langfuse_enabled=True` 不抛错且调用了上报接口（`langfuse_enabled=False` 时完全不触碰）。
- **mock 单测**：无网络、`LANGFUSE_*` 缺省下，整个可观测性路径不应触发真实 HTTP（避免问题 15 式的挂起）。
- **回归**：`logging` 行为不被破坏，现有测试日志输出无变化。

## 6. 实现优先级与工作量

- 优先级：**中**（P1，可信度/卖点真实性；若选方案 B 则极低工作量）。
- 工作量：
  - 方案 A：约 2-3 天（tracing + metrics + langfuse 接入 + 端点 + 测试）。
  - 方案 B：约 0.5 天（删字段 + 文档同步）。
- 建议：若本期重点是核心能力交付，直接走**方案 B 削除**最稳，避免新增易挂起的外部依赖；可观测性作为后续独立任务。
