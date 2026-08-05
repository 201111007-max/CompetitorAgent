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
        use_llm: bool = False,
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
| `llm` | `LLMClient \| None` | `None` | LLM 客户端（可选，缺失时走规则降级） |
| `use_llm` | `bool` | `False` | 是否启用 LLM 分析 |
| `max_iterations` | `int` | `10` | 最大迭代次数 |
| `cost_limit` | `float` | `1.0` | 成本上限（美元） |
| `event_sink` | `Callable` | `None` | 进度事件回调 |
| `extractor` | `WebExtractor` | `None` | 自定义采集器 |
| `memory` | `IFourLayerMemory` | `None` | 四层记忆（可选） |

### 方法

#### `analyze(task: str, conversation_history: list[ChatMessage] | None = None) -> CompetitorReport`

执行一次竞品分析（同步）。返回含 Markdown 报告的 `CompetitorReport`。
任务文本入站先做浅清洗（粘贴包装/终端泄漏/代理字符/@file: 引用展开）。
传入 `conversation_history` 支持多轮追问：相对指代（如"那定价呢"）可从历史承接上一轮竞品。

```python
api = CompetitorAnalysisAPI(use_llm=False)
report = api.analyze("Cursor")
print(report.markdown_report)

# 多轮追问：第二轮无竞品时从历史承接 Cursor
history = [ChatMessage(role="user", content="分析 Cursor"), ChatMessage(role="assistant", content=report.markdown_report)]
report2 = api.analyze("那定价呢", conversation_history=history)
```

#### `analyze_react(task: str) -> str`

ReAct 模式：LLM 驱动工具调用（需 LLM Key）。

#### `analyze_team(task: str) -> CompetitorReport`

多 Agent 流水线模式：Collector→Analyzer→Validator→Reporter 协作产出草稿报告。

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

#### `compare(a: str, b: str | None = None) -> ComparisonReport`

竞品对比：传入两个竞品名（或一个"对比 A 和 B"任务）→ 对比报告。
内部复用任务解析的对比拆分，逐个 `analyze` 后拼装 `ComparisonReport`（含 Markdown 对比表）。

```python
result = api.compare("Cursor", "Windsurf")
print(result.markdown_report)
```

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
