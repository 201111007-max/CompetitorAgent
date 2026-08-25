# API 参考（api.md）

> `CompetitorAnalysisAPI` 及核心对外接口的方法签名与示例。
> 外部调用方只能通过 Facade，禁止直连内部编排器。

---

## 1. CompetitorAnalysisAPI

```python
class CompetitorAnalysisAPI:
    """竞品分析 Agent 的外部唯一入口（门面）"""

    def __init__(
        self,
        llm: LLMClient | None = None,
        use_llm: bool = True,
        max_iterations: int = 10,
        cost_limit: float = 1.0,
        event_sink: Callable[[ProgressEvent], None] | None = None,
        extractor: WebExtractor | None = None,
        memory: IFourLayerMemory | None = None,
    ): ...
```

### 参数说明

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `llm` | `LLMClient \| None` | `None` | LLM 客户端（设计文档 47：主路径仅 LLM，缺失时抛 `LLMUnavailableError`） |
| `use_llm` | `bool` | `True` | 是否启用 LLM（设计文档 46：默认开启，与 CLI 对齐；`False` 时抛 `LLMUnavailableError`） |
| `max_iterations` | `int` | `10` | 最大迭代次数 |
| `cost_limit` | `float` | `1.0` | 成本上限（美元） |
| `event_sink` | `Callable` | `None` | 进度事件回调 |
| `extractor` | `WebExtractor` | `None` | 自定义采集器 |
| `memory` | `IFourLayerMemory` | `None` | 四层记忆（可选） |

> **`LLMUnavailableError` 语义（设计文档 47）**：主路径（`parse_task` / `plan` / 竞品识别 / 维度分析）
> 只走 LLM，不再有规则降级。未配置 API Key 或 LLM 调用失败时：
> - `parse_task` / `plan` 抛 `LLMUnavailableError`（由调用方决定处理；CLI 打印"需要配置 LLM API Key"退出码 2，
>   Web 返回 SSE `error` 事件）；
> - 单维度产出失败**不炸报告**，该维度以 `DimensionResult(status=PARTIAL)` 低置信落入报告（报告如实标注）；
> - `competitor_registry.resolve_competitor` 未命中抛 `ValueError`（竞品识别已归 LLM）。

### 方法

#### `run(task: str, *, session_id: str | None = None) -> CompetitorReport | ComparisonReport`

**统一入口（设计文档 62 §3.5）**：registry（单竞品）/ compare（对比）/ discovery（普查）
全 resolution 同走一条单 Lead loop，无代码分派 if-else；组装按 `plan.resolution` 统一分型
（registry → `CompetitorReport`，compare/discovery → `ComparisonReport` 矩阵 + 市场格局核心结论段）。
Lead 回合内自调通用工具编排（`make_plan` → `delegate` 委派维度/候选子 Agent → 可选
`web_search_candidates` 枚举候选 / `aggregate_report` 聚合）。

```python
api = CompetitorAnalysisAPI(llm=LLMClient(...), use_llm=True)  # 需配置 API Key
r1 = api.run("分析 Cursor")                          # → CompetitorReport
r2 = api.run("对比 Cursor 和 Windsurf")              # → ComparisonReport
r3 = api.run("帮我找市场上所有 coding agent")        # → ComparisonReport
```

#### `analyze(task: str, conversation_history: list[ChatMessage] | None = None) -> CompetitorReport`

执行一次竞品分析（同步）。返回含 Markdown 报告的 `CompetitorReport`。
任务文本入站先做浅清洗（粘贴包装/终端泄漏/代理字符/@file: 引用展开）。
传入 `conversation_history` 支持多轮追问：相对指代（如"那定价呢"）可从历史承接上一轮竞品。

```python
api = CompetitorAnalysisAPI(llm=LLMClient(...), use_llm=True)  # 需配置 API Key
report = api.analyze("Cursor")
print(report.markdown_report)

# 多轮追问：第二轮无竞品时从历史承接 Cursor
history = [ChatMessage(role="user", content="分析 Cursor"), ChatMessage(role="assistant", content=report.markdown_report)]
report2 = api.analyze("那定价呢", conversation_history=history)
```

#### `analyze_react(task: str) -> str`

ReAct 模式：LLM 驱动工具调用（需 LLM Key）。

#### `analyze_team(task: str) -> CompetitorReport`

多 Agent 编排入口（设计文档 49）：与 `analyze()` 同一条 Lead ReAct 路径的薄包装
（Lead LLM 经 `delegate` 委派独立维度子 Agent 并发执行），保留仅为调用方兼容。

#### `async analyze_stream(task: str, session_id: str | None = None) -> AsyncIterator[ProgressEvent]`

流式分析：逐条 yield ProgressEvent（供 Web SSE 消费）。

```python
async for event in api.analyze_stream("Cursor"):
    print(f"[{event.event}] {event.message}")
```

#### `cancel(session_id: str) -> None`

请求取消运行中的分析会话。

#### `resume(session_id: str) -> CompetitorReport`

从 checkpoint 恢复未完成的分析会话。

```python
api.cancel("sess_abc123")
report = api.resume("sess_abc123")
```

#### `get_history(competitor: str | None = None) -> list[CompetitorReport]`

查询历史分析报告。`competitor` 可选，留空返回全部。

#### `compare(*competitors: str) -> ComparisonReport`

竞品对比（**deprecated，历史兼容**，设计文档 62 §3.5）：`= run(task)` 的 COMPARE 语义路径，
发出废弃告警。请改用统一入口 `run("对比 A 和 B")`。单个参数支持"对比 A 和 B"/"A vs B"
任务文本解析；多参数逐个作为竞品名处理。

```python
result = api.run("对比 Cursor 和 Windsurf")          # 推荐
result = api.compare("Cursor", "Windsurf")            # deprecated → 内部转 run()
print(result.markdown_report)
```

#### `discover(task: str) -> ComparisonReport`

市场普查（**deprecated，历史兼容**，设计文档 62 §3.5）：`= run(task)` 的 DISCOVERY 语义路径，
发出废弃告警。请改用统一入口 `run("帮我找市场上所有 …")`。

#### `continue_analysis(session_id: str) -> CompetitorReport`

恢复未完成的会话（对齐 CLI `-c/--continue` 语义；复用 `resume`）。

```python
report = api.continue_analysis("sess_abc123")
```

#### `_disambiguate_with_history(task, conversation_history)`（辅助）

结合会话历史消歧：当前任务解析出的竞品为 unknown（相对指代）时，
从历史消息提取最近竞品拼入任务文本。

---

## 2. 事件契约（ProgressEvent，SSE 流）

```python
@dataclass
class ProgressEvent:
    event: str       # phase_start / phase_complete / progress / report / error / cancelled / session_started
    phase: str | None
    progress: float  # 0.0-1.0
    message: str
    payload: dict
```

| event | 触发点 | message 示例 |
|-------|--------|-------------|
| `session_started` | 会话启动 | "会话 sess_abc 已启动" |
| `phase_start` | 阶段开始 | "规划: 分析 Cursor" |
| `phase_complete` | 阶段完成 | "识别竞品 cursor，3 个缺口" |
| `report` | 报告生成 | "报告生成完成，终态=success" |
| `error` | 异常 | "分析异常: ..." |
| `cancelled` | 用户取消 | "分析已被用户取消" |

SSE 格式：`data: {"event": "phase_start", ...}\n\n`

---

## 3. 数据模型

### CompetitorReport

```python
@dataclass
class CompetitorReport:
    competitor: Competitor
    dimension_results: list[DimensionResult]
    overall_score: float
    overall_confidence: float
    gaps_pending: list[InfoGap]
    markdown_report: str
    terminal_state: str
    created_at: str
```

### DimensionResult

```python
@dataclass
class DimensionResult:
    dimension: str          # pricing / feature / performance / ecosystem / sentiment / roadmap
    summary: str
    details: dict
    confidence: float       # 0.0-1.0
    evidence: list[SourceEvidence]
    timestamp: str
    status: ResultStatus    # complete / partial / unavailable
```

---

## 4. 错误与异常

| 异常 | 场景 | 建议处理 |
|------|------|---------|
| `CredentialError` | 缺必需凭据 | 提示 config set-key |
| `LLMUnavailableError` | LLM 不可用 | 自动降级，不影响接口返回 |
| `ValueError` | resume 不存在的会话 | 校验 session_id |

---

## 5. 版本与兼容

- API 1.0 冻结于 M4 验收通过后。
- 破坏性变更需在 CHANGELOG 记录并 bump 主版本。
- 所有公共方法带类型注解与 docstring，mypy 严格模式通过。
