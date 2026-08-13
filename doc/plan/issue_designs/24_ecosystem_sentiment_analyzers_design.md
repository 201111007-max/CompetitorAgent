# 设计文档 24 — EcosystemAnalyzer 与 SentimentAnalyzer

> 对应 `implementation_plan.md` §12.1 #2（P0）「ecosystem / sentiment 无专属分析器」。
> 数据源依赖设计文档 23（多源路由）；评测覆盖见设计文档 29。

## 1. 问题现状

- `core/strategic_loop.py::DIMENSION_PRIORITY` 已声明 6 维度（pricing/feature/performance/**ecosystem**/**sentiment**/roadmap），`config/loader.py::DimensionsConfig.enabled` 默认含全部 6 维。
- 但 `analyzers/registry.py::AnalyzerRegistry._analyzers` 只注册 `pricing` / `feature` / `performance` 三个具体分析器；`ecosystem` / `sentiment` / `roadmap` 全部落到 `FallbackAnalyzer` 做通用 LLM 总结。
- 对 AI coding 工具，`ecosystem`（MCP server、插件、IDE 支持、agentic tool-use、集成生态）与 `sentiment`（社区口碑、真实用户评价）恰是关键差异化维度，却被最弱的处理覆盖。
- `SourceSelector._DIMENSION_LINK_KEY` 已为两维度映射了官方源（ecosystem→docs/home、sentiment→home），但仅抓官网口碑页信息量极低；多源路由（设计文档 23）落地后才真正有数据。

## 2. 目标设计

1. **`EcosystemAnalyzer`**：从 GitHub（仓库规模/Stars/Release 节奏）、插件市场（插件数/评分/下载）、官方文档集成章节，产出结构化的生态能力盘点：
   - MCP server 支持（数量、第一方/第三方、发现途径）；
   - 插件/扩展市场（数量、评分、关键插件）；
   - IDE 支持（VS Code / JetBrains / 终端）；
   - agentic tool-use / 外部工具集成；
   - 仓库活跃度（stars、release 频率、commit 近 30 天）。
2. **`SentimentAnalyzer`**：从社区源（HN/Reddit/X/YouTube，经设计文档 23 的 `CommunitySourceProvider`）与官方定价/文档之外的页面，产出：
   - 正/负/中信号计数与占比（来源可追溯）；
   - 高频好评点与高频吐槽点（各 ≤5，带证据 URL）；
   - 口碑总体结论 + 置信度（信号不足时明确 `[PARTIAL]` 不编造）。
3. **统一落到领域模型**：输出 `Observation` 经分析器转 `AnalysisResult`，`confidence` 按证据数/覆盖源数校准；`ecosystem`/`sentiment` 进入品类矩阵与报告正文（复用现有 `CompetitorReport` 结构，无需新数据模型）。

## 3. 模块/接口设计

### 3.1 `analyzers/ecosystem_analyzer.py`

```python
class EcosystemAnalyzer(BaseCompetitorAnalyzer):
    field = "ecosystem"

    def analyze(self, observation: Observation, gap: InfoGap, context: AnalysisContext) -> AnalysisResult:
        """多源聚合：github 信号（stars/releases/commits）+ 市场信号 + 文档集成清单。
        输出结论形如：
        - mcp_servers: list[dict]      # {name, vendor, discoverable_via}
        - plugins: dict                # {count, rating, top: [..]}
        - ide_support: list[str]       # ["vscode", "jetbrains", "terminal"]
        - integrations: list[str]      # agentic tool-use / 外部工具
        - repo_activity: dict          # {stars, last_release, commits_30d}
        """
```

- `_evidence_sources()` 声明所需 kind（`github` / `marketplace` / `web`），供规划器把缺口路由到多源（与设计文档 23 对齐）。

### 3.2 `analyzers/sentiment_analyzer.py`

```python
class SentimentAnalyzer(BaseCompetitorAnalyzer):
    field = "sentiment"

    def analyze(self, observation: Observation, gap: InfoGap, context: AnalysisContext) -> AnalysisResult:
        """社区信号聚合：
        - signals: list[dict]          # {polarity: pos/neg/neu, quote, source_url}
        - positives / negatives: list[str]   # 高频点（≤5 各），每项带 1 个证据 URL
        - polarity_ratio: dict         # {pos: 0.6, neg: 0.3, neu: 0.1}
        - verdict: str                 # 一句话口碑结论
        """
```

- 无网络 / 社区源为空时返回 `confidence≈0` 的 `[PARTIAL]` 结论并注明"信号不足"，**禁止编造**（沿用证据链 + `detect_injection` 防护）。

### 3.3 注册 `analyzers/registry.py`

```python
self._analyzers = {
    "pricing": PricingAnalyzer(...),
    "feature": FeatureAnalyzer(...),
    "performance": PerformanceAnalyzer(...),
    "ecosystem": EcosystemAnalyzer(...),   # ← 新增
    "sentiment": SentimentAnalyzer(...),   # ← 新增
}
```

- `roadmap` 暂保留 Fallback（数据源仅有 changelog，纳入设计文档 26 时间线后升级）。

### 3.4 领域模型（`domain_types/`）

- 复用 `AnalysisResult`（结论 + 证据 + 置信度），无需新 dataclass；如需要结构化字段，新增 `EcosystemResult` / `SentimentResult` 作为 `AnalysisResult.payload`（可选增强，不阻塞接入）。

## 4. 接入方式

```
AnalyzerRegistry（3.3 注册）
  └─ StrategicPlanner 已含 ecosystem/sentiment 维度（无需改）
  └─ SourceSelector 路由（设计文档 23）为两维度提供 github/marketplace/social 候选
  └─ GapExecutor 采集 → Observation → 对应分析器 analyze → AnalysisResult → 报告/矩阵
```

- 先落地设计文档 23 再启用：两分析器在无多源时也能工作（回退到官方页 + 明确的低置信度），不会比现状更差。

## 5. 验证方式

- **单测（Ecosystem）**：mock observation 含 github stars/release + 市场评分 → 分析器产出结构化生态结论；缺市场源 → `mcp_servers` 正常、`plugins` 置空且不编造。
- **单测（Sentiment）**：mock 信号 {pos:2, neg:1} → polarity_ratio 正确、top 正负点各 ≤5 且带证据 URL；**空信号 → `[PARTIAL]` 低置信，无幻觉内容**。
- **单测（注册）**：`AnalyzerRegistry.get("ecosystem")` / `get("sentiment")` 返回具体分析器而非 Fallback。
- **单测（注入防护）**：observation 含注入特征 → 跳过 LLM 降级（复用 `trust_boundary.detect_injection`）。
- **集成**：mock 多源 provider，`analyze("Cursor", dimensions=["ecosystem","sentiment"])` 报告两维度有结构化结论且证据可追溯；回归：全量 6 维度默认配置正常。
- **评测**：新增 ecosystem/sentiment accuracy 用例（设计文档 29）。

## 6. 实现优先级与工作量

- 优先级：**高**（P0；对 AI coding 工具是最强差异化，且消除"宣称维度却无专属实现"的落差）。
- 工作量：约 2-3 天。
  - EcosystemAnalyzer + 证据源声明：1 天；
  - SentimentAnalyzer + 低置信护栏：0.5-1 天；
  - 注册 + 单测：0.5 天；
  - 集成 + 评测用例（随设计文档 29）：0.5 天。
- 前置：设计文档 23（多源路由）先落地可最大化效果；无前置也可回退到官方源。
