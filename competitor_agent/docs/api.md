# API 参考（api.md）

> `CompetitorAnalysisAPI` 及核心对外接口的方法签名与示例。M4 定稿，当前为契约草案。
> 外部调用方只能通过 Facade，禁止直连内部编排器。

---

## 1. CompetitorAnalysisAPI

```python
class CompetitorAnalysisAPI:
    """竞品分析 Agent 的外部唯一入口（门面）"""

    def __init__(
        self,
        planner: IStrategicPlanner,
        executor: ITacticalExecutor,
        reporter: IReportBuilder,
        memory: IFourLayerMemory,
        controller: BudgetController,
        tracer: Optional[Tracer] = None,
    ): ...

    @classmethod
    def from_defaults(cls, config: Optional[Config] = None) -> "CompetitorAnalysisAPI":
        """装配默认实现（对标 create_default_api）"""

    def analyze(
        self,
        task: str,
        dimensions: Optional[List[DimensionType]] = None,
        session_id: Optional[str] = None,
    ) -> CompetitorReport:
        """执行一次竞品分析（同步）。
        参数：
            task: 自然语言任务，如 "分析 Claude Code" / "对比 Cursor 和 Windsurf"
            dimensions: 限定维度子集（默认按 config.dimensions.enabled）
            session_id: 复用已有会话（断点续跑）
        返回：CompetitorReport（含 markdown_report）
        """

    async def analyze_stream(
        self,
        task: str,
        dimensions: Optional[List[DimensionType]] = None,
    ) -> AsyncIterator[ProgressEvent]:
        """流式分析：逐条产出 SSE ProgressEvent（供 Web 前端）"""

    def cancel(self, session_id: str) -> None:
        """请求取消运行中的会话"""

    def resume(self, session_id: str) -> CompetitorReport:
        """从 checkpoint 恢复未完成会话"""

    def get_history(self, competitor: Optional[str] = None) -> List[CompetitorReport]:
        """查询历史分析报告（记忆 L1）"""

    def status(self, session_id: str) -> SessionStatus:
        """查询会话状态：running/complete/cancelled/failed"""
```

---

## 2. 事件契约（ProgressEvent，SSE 流）

```python
class ProgressEvent:
    event_type: EventType   # plan / collect / analyze / validate / report / done / error
    session_id: str
    data: Dict[str, Any]    # 如 {"gap": "pricing", "status": "ok"}
    ts: str
```

| event_type | 触发点 | data 关键字段 |
|------------|--------|--------------|
| `plan` | 战略循环完成 | gaps 数量、预算 |
| `collect` | 每次采集 | source、status、obs 摘要 |
| `analyze` | 每次分析 | dimension、confidence |
| `validate` | 校验 | pass/fail、issues |
| `report` | 报告生成 | markdown 摘要 |
| `done` | 完成 | terminal_state、耗时 |
| `error` | 异常 | error_type、message |

---

## 3. CLI 接口

```python
# competitor_agent/cli.py
analyze   <task> [--out PATH] [--dimensions ...] [--session ID]
history   [--competitor NAME]
cancel    <session_id>
resume    <session_id>
config    set-key <name> / list / rotate <name>
```

---

## 4. 错误与异常

| 异常 | 场景 | 建议处理 |
|------|------|---------|
| `TaskNotSupportedError` | 无法识别目标竞品 | 提示用户澄清 |
| `SessionNotFoundError` | resume 不存在的会话 | 校验 session_id |
| `CredentialError` | 缺必需凭据 | 提示 config set-key |
| `BudgetExhaustedError` | 成本/迭代超限 | 报告含 reason，可 resume |
| `LLMUnavailableError` | LLM 不可用 | 自动降级，不影响接口返回 |

---

## 5. 版本与兼容

- API 1.0 冻结于 M4 验收通过后。
- 破坏性变更需在 CHANGELOG 记录并 bump 主版本。
- 所有公共方法带类型注解与 docstring，mypy 严格模式通过。
