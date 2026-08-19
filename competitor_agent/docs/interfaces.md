# 接口契约文档（interfaces.md）

> 定义 `competitor_agent/interfaces/` 现存 Protocol 的签名、语义、异常约定与数据流方向。
> 使用 `typing.Protocol`，与实现解耦；领域类型见 `domain_models.md`。
>
> 设计文档 49（2026-08-19）后，编排/采集/分析不再以 Python Protocol 表达——
> 主路径为 Lead ReAct 编排（`agent/react_loop.py` + `agent/subagent_registry.py`），
> 规划/采集/分析决策全部由 LLM 经工具调用完成；本目录只保留跨层共享的
> 记忆与报告两个稳定契约，以及上下文数据类（`context.py`）与异常族（`exceptions.py`）。

---

## 1. 契约总览

```
┌────────────────────────────────────────────────────┐
│  Lead ReactLoop（LLM 编排：make_plan → delegate/工具  │
│  → Final Answer REPORT_SCHEMA）                     │
└───────┬───────────────────────────────┬────────────┘
        │ 读：recent_context/patterns    │ 产出
        ▼                               ▼
┌─────────────────┐           ┌──────────────────────┐
│ IFourLayerMemory │           │   IReportBuilder      │
│ (四层记忆)        │           │ (维度结果 → 报告)      │
└─────────────────┘           └──────────────────────┘
```

---

## 2. Protocol 定义

### 2.1 IFourLayerMemory（四层记忆）

```python
class IFourLayerMemory(Protocol):
    """L1 会话归档 / L2 持久笔记 / L3 技能 / L4 进化记录"""

    def archive_session(self, session: AnalysisSession) -> None: ...
    def list_sessions(self, competitor: str | None = None) -> list[AnalysisSession]: ...
    def recent_context(self, competitor: str, top_k: int = 5, query: str = "") -> list[str]:
        """L1: 按任务相关度召回可注入 Lead/子 Agent 系统提示的记忆上下文（设计文档 35）"""
    def save_note(self, competitor: str, note: str) -> None: ...
    def retrieve_notes(self, competitor: str) -> list[str]: ...
    def record_skill(self, skill: Skill) -> None: ...
    def retrieve_skills(self, competitor: str) -> list[Skill]: ...
    def record_success(self, competitor: str, gap_field: str, source_name: str, method: str = "") -> None: ...
    def record_outcome(self, source: str, success: bool) -> None: ...
    def source_success_rates(self) -> dict[str, float]: ...
    def note_pattern(self, competitor: str, dimension: str, pattern: str, outcome: str) -> None: ...
    def retrieve_patterns(self, competitor: str, dimension: str) -> list[str]: ...
    def retrieve_patterns_with_outcome(self, competitor: str, dimension: str) -> list[tuple[str, str]]: ...
    def failure_patterns_for(self, competitor: str) -> list[str]: ...
```

**读写方向**：读侧——`analyze()` 构建 Lead 时经 `_react_memory_context` 召回注入系统提示；
写侧——分析成功后由 `facade/api.py::_record_memory_success` 单点沉淀（技能/成功率/模式）。

### 2.2 IReportBuilder（报告构建器）

```python
class IReportBuilder(Protocol):
    """把维度结果与未关闭缺口汇总为报告"""

    def build(self, competitor: Competitor, results: list[DimensionResult],
              gaps_pending: list[InfoGap], terminal_state: str) -> CompetitorReport: ...
    def to_markdown(self, report: CompetitorReport) -> str: ...
```

由 `facade/react_report.py::assemble` 调用：Lead Final Answer（REPORT_SCHEMA JSON）解析为
多维度 `DimensionResult` 后交给 ReportBuilder 渲染（新鲜度/证据链/时间线段落在此附加）。

---

## 3. 上下文数据类（context.py）

| 类 | 用途 |
|----|------|
| `SourceContext` | 采集调用上下文（URL/kwargs） |
| `AnalysisContext` | 分析上下文（含 `memory_context` 注入位） |
| `BudgetState` / `StopDecision` | 预算快照与终止判定结果 |
| `AnalysisSession` | L1 归档会话记录 |
| `Skill` | L3 技能记录 |
| `ChatMessage` | LLM 消息 |

## 4. 异常约定（exceptions.py）

| 异常 | 抛出方 | 语义 |
|------|--------|------|
| `DataSourceUnavailableError` | 采集工具 | 源不可用，LLM 可换源重试 |
| `SourceBlockedError` | 采集工具 | 反爬/403，记录失败教训 |
| `TaskNotSupportedError` | 任务解析 | 无法识别目标竞品，要求澄清 |
| `AnalysisNotApplicableError` | 分析工具 | Observation 与维度不匹配，返回空结论 |
| `LLMUnavailableError` | LLMClient / 入口 | 无 API Key 显式失败（设计文档 47：无静默规则降级） |
| `BudgetExhaustedError` | BudgetController | 预算耗尽，进入终止流程 |
| `CredentialError` | SecretVault | 缺凭据 |

---

## 5. 新增契约的约束

1. 接口一律 `Protocol` + 类型注解，不引入具体实现依赖。
2. 每新增一个 Protocol，必须在 `tests/unit/interfaces/` 加冒烟测试（fake 实现能通过类型检查）。
3. 契约变更需同步更新本文档与 `domain_models.md`。
4. 编排决策不新增 Python 规则契约——先评估能否以 skill 注入或工具化表达（设计文档 49 §21.2 映射）。
