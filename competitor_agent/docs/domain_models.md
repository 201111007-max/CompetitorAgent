# 领域模型文档（domain_models.md）

> 定义 `competitor_agent/domain_types/` 核心数据模型、字段含义与状态机。
> 状态机尤其重要——`InfoGap.status` 是全系统"信息缺口驱动"的中枢。

---

## 1. Competitor（竞品）

```python
@dataclass(frozen=True)
class Competitor:
    name: str                    # 规范名（小写+连字符，如 "claude-code"）
    aliases: List[str]           # 别名（anysphere/cursor）
    category: str                # 默认 "ai_coding_agent"
    official_links: Dict[str, str]  # docs/home/changelog/pricing
```

**规范**：
- `name` 是唯一键，全局一致（记忆/知识库/报告都用它）。
- `aliases` 用于规划阶段消歧（R10）。
- 通过 `COMPETITOR_REGISTRY` 预注册常用竞品，未知竞品走通用 web 采集。

---

## 2. InfoGap（信息缺口）— 中枢状态机

```python
@dataclass
class InfoGap:
    field: str                 # pricing / features / performance / ecosystem / sentiment / roadmap
    priority: int              # 1-10，越高越关键
    confidence: float          # 0-1 当前置信度
    sources_tried: List[str]   # 已尝试数据源（去重）
    status: GapStatus
    evidence: List[SourceEvidence]
```

### 2.1 GapStatus 状态机

```
┌────────┐  plan    ┌─────────┐  collect   ┌─────────┐  valid   ┌────────┐
│  OPEN   │────────►│ PARTIAL │──────────►│ CONFIRM │─────────►│ CLOSED │
└────────┘          └────┬────┘           └────┬────┘          └────────┘
                         │ fail/conflict       │ 交叉验证仍错
                         └────────► OPEN (reset) └─────────► PARTIAL (retry)
```

| 状态 | 含义 | 进入条件 | 离开条件 |
|------|------|---------|---------|
| `OPEN` | 未采集或无数据 | 规划阶段 | 采集到 Observation |
| `PARTIAL` | 部分/低置信 | 单源采集、证据不足 | 交叉验证通过→CONFIRMED；失败重试→OPEN |
| `CONFIRMED` | 多源一致/高度置信 | 验证通过（confidence ≥ 0.8 或 ≥2 源一致） | 直接视为 CLOSED |
| `CLOSED` | 缺口关闭 | CONFIRMED 或被判定无需更精确 | 终态（除非 re-analyze） |
| `BLOCKED` | 无法关闭 | 源全失败/预算耗尽 | 进入报告 pending，不编造 |

**关键规则**：核心缺口（priority ≥ 8）CLOSED 且 confidence ≥ 0.8，即满足 BudgetController 终止条件之一。

---

## 3. SourceEvidence（证据链，防幻觉核心）

```python
@dataclass
class SourceEvidence:
    source_name: str      # 数据源标识（official_docs / pricing_page / github_api）
    url: str
    access_time: str      # 采集时间（用于新鲜度）
    content_hash: str     # 内容去重/变更检测
    trust_level: float    # 0-1 源可信度（官方>评测>社区）
```

**约束**：任何写入报告的事实必须能回溯到 ≥1 条 SourceEvidence。无证据的声明标记为 `confidence < 0.3` 或排除。

---

## 4. Observation（采集观察）

```python
@dataclass
class Observation:
    gap_field: str
    source: str
    raw_text: str
    extracted: Dict[str, Any]     # 结构化提取结果（如 {"price": "$20/mo"}
    evidence: SourceEvidence
    status: str                   # ok / blocked / degraded
```

**状态语义**：
- `ok`：正常采集，进入分析。
- `degraded`：降级源产出（标低可信度）。
- `blocked`：反爬/失效，触发降级链 + 记录失败教训（L4）。

---

## 5. DimensionResult（维度结论）

```python
@dataclass
class DimensionResult:
    dimension: DimensionType      # FEATURE/PRICING/PERFORMANCE/ECOSYSTEM/SENTIMENT/ROADMAP
    summary: str                  # 该维度结论摘要
    details: Dict[str, Any]       # 结构化明细（如 pricing plan 列表）
    confidence: float             # 0-1
    evidence: List[SourceEvidence]
    timestamp: str
    status: ResultStatus          # COMPLETE / PARTIAL / UNAVAILABLE
```

---

## 6. CompetitorStrategy / CompetitorReport

```python
@dataclass
class CompetitorStrategy:
    competitor: Competitor
    gaps: List[InfoGap]                    # 信息缺口清单
    budget_allocation: Dict[DimensionType, int]  # 维度→迭代预算
    terminal_thresholds: Dict[str, float]      # 终止阈值（confidence 等）

@dataclass
class CompetitorReport:
    competitor: Competitor
    dimension_results: List[DimensionResult]
    overall_score: float
    overall_confidence: float
    gaps_pending: List[InfoGap]          # 未关闭缺口及原因（不编造）
    markdown_report: str
    terminal_state: str
    created_at: str
```

---

## 7. 枚举（enums）

```python
class DimensionType(Enum): FEATURE, PRICING, PERFORMANCE, ECOSYSTEM, SENTIMENT, ROADMAP
class GapStatus(Enum): OPEN, PARTIAL, CONFIRMED, CLOSED, BLOCKED
class ResultStatus(Enum): COMPLETE, PARTIAL, UNAVAILABLE
class TerminalState(Enum): SUCCESS, PARTIAL, DEGRADED, TERMINAL_ERROR
class NetworkState(Enum): OK, RETRYABLE, BLOCKED, UNAVAILABLE
```

---

## 8. 判定规则（后端约束）

| 规则 | 实现位置 | 说明 |
|------|---------|------|
| 缺口关闭判据 | budget_controller | 优先级≥8 且 confidence≥0.8，或目标源确认 |
| 核心满足度 | budget_controller | 全部核心缺口 confidence≥0.8 |
| 证据强制 | validator_agent | 无 SourceEvidence 的结论打回 |
| 三级终止 | budget_controller.should_stop | 全关/迭代超限/成本超限/核心满足 |