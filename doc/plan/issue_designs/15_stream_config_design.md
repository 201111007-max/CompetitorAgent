# 设计文档 15 — `analyze_stream` 静默丢弃 config

> 对应 `implementation_plan.md` 第 11 节问题 17（P1）

## 1. 问题现状

- `facade/api.py:412-465` 的 `analyze_stream` 内部**重新 new 了一个 `CompetitorAnalysisAPI`**，仅透传 `max_iterations` / `cost_limit`：

  ```python
  api = CompetitorAnalysisAPI(
      llm=self._llm,
      use_llm=self._use_llm,
      max_iterations=self._budget.max_iterations,
      cost_limit=self._budget.cost_limit,
      event_sink=_sink,
      extractor=self._extractor,
      memory=self._memory,
  )
  ...
  report = await loop.run_in_executor(None, api.analyze, task, None, "team", sid)
  ```

- **丢弃了调用方当前实例的 `config`**（`self._config`）。`CompetitorAnalysisAPI.__init__` 中 `cfg = config or load_config()`，因此子实例退回：
  - `execution.mode` 默认 `single`（而非当前实例可能的 `parallel`）；
  - `collector.*`（timeout/retries/use_playwright）、`stop_verifier.*`、`memory.*`、`security.*`、`dimensions.*` 全部走 YAML 默认值，而非当前实例注入的配置。
- 后果：同一 `CompetitorAnalysisAPI` 实例，**流式路径（`/api/stream`）与直接路径（`analyze()`）行为不一致**——流式永远跑 `single` 串行、不读自定义采集/安全配置。Web SSE 与 CLI/API 拿到的结果可能在并行度、降级策略上不同。

## 2. 目标设计

1. 流式路径与直接路径**共享同一份配置与组件**：`execution.mode`、`collector`、`security` 等从当前实例透传。
2. 不重复构造重量级组件（`extractor` / `memory` / `store` / `ingester` / `retriever` 已在同一实例存在，应复用而非重建）。
3. 消除"在方法里 new 一个对等 API"的反模式——流式只是 `analyze` 的事件包装。

## 3. 模块/接口设计

### 3.1 让 `analyze` 支持 `event_sink` 透传（首选）

最小改动：把流式能力下沉为 `analyze` 的一个开关，而非另起实例。

```python
def analyze(
    self,
    task: str,
    conversation_history=None,
    mode: str = "team",
    session_id: str | None = None,
    event_sink: Callable[[ProgressEvent], None] | None = None,   # 新增
) -> CompetitorReport:
    ...
    if event_sink is not None:
        self._event_sink = event_sink   # 临时绑定（或构造子作用域）
    ...
```

`analyze_stream` 改为直接调用自身、复用 `self._config` 与全部组件：

```python
async def analyze_stream(self, task, session_id=None):
    sid = session_id or f"sess_{uuid.uuid4().hex[:8]}"
    def _sink(event): self._emit(event)
    yield ProgressEvent(event="session_started", ...)
    report = await loop.run_in_executor(
        None, self.analyze, task, None, "team", sid, _sink
    )
    yield ProgressEvent(event="report", ...)
    # 归档会话（raw schema 见设计文档 16）
    ...
```

### 3.2 若保留子实例，则透传完整 config

若不想改 `analyze` 签名，则子实例必须 `config=self._config` 且复用组件：

```python
api = CompetitorAnalysisAPI(
    llm=self._llm, use_llm=self._use_llm,
    config=self._config,                       # 关键：透传
    event_sink=_sink,
    extractor=self._extractor,
    memory=self._memory,
    # 进一步复用知识库组件，避免双实例化
)
```

## 4. 接入方式

```
Web /api/stream → api.analyze_stream(task, sid)
                     → self.analyze(task, mode="team", session_id=sid, event_sink=_sink)
                           → 复用 self._config / self._extractor / self._memory ...
                           → 每个阶段 self._emit(event) 直接经 event_sink 推 SSE
```

## 5. 验证方式

- **单元测试**：
  - 构造 `api = CompetitorAnalysisAPI(config=cfg_with_parallel)`，调用 `analyze_stream`，断言实际执行路径读取了 `cfg.execution.mode == "parallel"`（可用 spy 验证 `ThreadPoolExecutor` 被使用，而非永远串行）。
  - 断言子实例未重建 `extractor` / `memory`（同一对象 id）。
- **一致性测试**：
  - 同一 `task` 下，`analyze()` 与 `analyze_stream()` 产出的 `markdown_report` 关键维度一致（非因配置差异而分支）。
- **回归**：现有 `tests/integration` / `tests/e2e` 中 SSE 相关用例（Web 流式产出报告）继续通过。

## 6. 实现优先级与工作量

- 优先级：**中**（P1，配置一致性，影响 Web/CLI 结果分歧）。
- 工作量：约 0.5-1 天（透传 config + 调整流式包装，加 2-3 个测试）。
- 与问题 16/20 同处 `facade/api.py`，建议合并重构该文件（见设计文档 18 的统一编排）。
