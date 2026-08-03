# 接口契约文档（interfaces.md）

> 定义 `competitor_agent/interfaces/` 各 Protocol 的签名、语义、异常约定与数据流方向。
> 使用 `typing.Protocol`，与实现解耦；领域类型见 `domain_models.md`。

---

## 1. 契约总览

```
                    ┌────────────────────────────┐
                    │      IStrategicPlanner      │
                    └─────────────┬──────────────┘
                                  │ CompetitorStrategy
┌──────────────┐      ┌──────────▼───────────┐
│IDataSource   │◄─────│    ITacticalExecutor  │  ──►  调用
│(采集数据源)    │      └──────────┬───────────┘        │
└──────────────┘                 │ Observation        ▼
                    ┌────────────▼───────────┐  ┌──────────────┐
                    │    ICompetitorAnalyzer │──►│ IReportBuilder│
                    └────────────────────────┘  └──────┬───────┘
                                                       ▼ CompetitorReport
                    ┌──────────────┐   ┌──────────────┐
                    │ IStopVerifier │◄──│  BudgetController│
                    └──────────────┘   └──────────────┘
                    ┌──────────────┐
                    │IFourLayerMemory│
                    └──────────────┘
```

---

## 2. Protocol 定义

### 2.1 ICompetitorDataSource（采集数据源）

```python
class ICompetitorDataSource(Protocol):
    """任一竞品信息数据源（官网/GitHub/定价页/评测/口碑）"""

    def fetch(self, gap: InfoGap, context: SourceContext) -> Observation:
        """按信息缺口抓取并返回观察结果。
        异常：DataSourceUnavailableError（源不可用，触发降级链）
               SourceBlockedError（反爬/403，记录失败教训）
        """
    @property
    def source_name(self) -> str: ...
    def is_available(self) -> bool: ...
```

**降级语义**：`SourceSelector` 维护候选列表，`fetch` 抛 `DataSourceUnavailableError` 时按序换下一个候选。

### 2.2 IStrategicPlanner（战略规划器）

```python
class IStrategicPlanner(Protocol):
    """把用户任务解析为信息缺口清单与预算分配"""

    def plan(self, task: str, memory: IFourLayerMemory) -> CompetitorStrategy:
        """产出：竞品识别 + InfoGap 清单（优先级/初始置信度）+ 维度预算 + 终止阈值。
        异常：TaskNotSupportedError（无法识别目标竞品，要求澄清）
        """
```

### 2.3 ICompetitorAnalyzer（维度分析器）

```python
class ICompetitorAnalyzer(Protocol):
    """单个维度（功能/定价/性能/生态/口碑）的分析器"""

    @property
    def dimension(self) -> DimensionType: ...

    def analyze(self, observation: Observation, gap: InfoGap,
                context: AnalysisContext) -> DimensionResult:
        """把原始 Observation 提炼为维度结论（含置信度与证据）。
        可被 ReAct 调用，也可被 tactical_loop 直接调用。
        异常：AnalysisNotApplicableError（Observation 与维度不匹配，返回空结论）
        """
    def confidence(self, result: DimensionResult) -> float:
        """结论置信度 0-1，供 BudgetController 评估核心满足度"""
```

### 2.4 IFourLayerMemory（四层记忆）

```python
class IFourLayerMemory(Protocol):
    """L1 会话归档 / L2 持久笔记 / L3 技能 / L4 进化记录"""

    def archive_session(self, session: AnalysisSession) -> None: ...
    def save_note(self, competitor: str, note: str) -> None: ...
    def retrieve_notes(self, competitor: str) -> List[str]: ...
    def record_skill(self, skill: Skill) -> None: ...
    def retrieve_skills(self, competitor: str) -> List[Skill]: ...
    def record_outcome(self, source: str, success: bool) -> None: ...
    def source_success_rates(self) -> Dict[str, float]: ...
```

### 2.5 IStopVerifier（停止验证器）

```python
class IStopVerifier(Protocol):
    """决定一次分析是否可终止（由 Hook 验证，而非预算单方面决定）"""

    def verify(self, gaps: List[InfoGap], budget_state: BudgetState) -> StopDecision:
        """返回：可停（含 reason）/ 不可停（含缺口原因）"""
```

### 2.6 IReportBuilder（报告构建器）

```python
class IReportBuilder(Protocol):
    """把维度结果与未关闭缺口汇总为报告"""

    def build(self, competitor: Competitor, results: List[DimensionResult],
              gaps_pending: List[InfoGap], terminal_state: str) -> CompetitorReport: ...
    def to_markdown(self, report: CompetitorReport) -> str: ...
```

### 2.7 IContextCompressor（可选，上下文压缩）

```python
class IContextCompressor(Protocol):
    """TacticalLoop 中压缩已消费上下文，防止溢出"""
    def compress(self, messages: List[ChatMessage]) -> List[ChatMessage]: ...
```

---

## 3. 数据流方向约定

| 方向 | 谁 → 谁 | 传递内容 |
|------|---------|---------|
| 规划 | IStrategicPlanner → ITacticalExecutor | CompetitorStrategy（缺口清单+预算） |
| 采集 | ITacticalExecutor → IDataSource | InfoGap + SourceContext |
| 产出 | IDataSource → ITacticalExecutor | Observation |
| 分析 | ITacticalExecutor → ICompetitorAnalyzer | Observation + InfoGap |
| 产出 | ICompetitorAnalyzer → ITacticalExecutor | DimensionResult |
| 终止 | BudgetController → IStopVerifier | gaps + budget_state |
| 记忆 | 各层 → IFourLayerMemory | 归档/笔记/技能/结果 |
| 汇总 | ITacticalExecutor → IReportBuilder | results + gaps_pending |

---

## 4. 异常约定

| 异常 | 抛出方 | 处理方 | 语义 |
|------|--------|--------|------|
| `DataSourceUnavailableError` | DataSource | TacticalLoop/SourceSelector | 换降级源 |
| `SourceBlockedError` | DataSource | EvolutionMemory | 记录失败，标记该源短期不可用 |
| `TaskNotSupportedError` | StrategicPlanner | Facade API | 要求用户澄清任务 |
| `AnalysisNotApplicableError` | Analyzer | TacticalLoop | 返回空结论，不阻断 |
| `LLMUnavailableError` | LLMClient | FallbackAnalyzer | 降级到规则/缓存 |
| `BudgetExhaustedError` | BudgetController | TacticalLoop | 进入终止流程 |
| `CredentialError` | SecretVault | 各调用方 | 缺凭据，按降级处理 |

---

## 5. 新增契约的约束

1. 接口一律 `Protocol` + 类型注解，不引入具体实现依赖。
2. 每新增一个 Protocol，必须在 `tests/unit/interfaces/` 加冒烟测试（fake 实现能通过类型检查）。
3. 契约变更需同步更新本文档与 `domain_models.md`。
