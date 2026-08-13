# 设计文档 23 — SourceSelector 多源路由（缺口 → 外部源）

> 对应 `implementation_plan.md` §12.1 #1（P0）「数据源只认官网」；与 §13 发现器、设计文档 24（Ecosystem/Sentiment 分析器）协同。

## 1. 问题现状

- `collector/source_selector.py::SourceSelector.candidates()` 仅用 `competitor.official_links`（pricing/home/docs/changelog）+ 同一 URL 的 `spa_extractor` 兜底。对所有维度最终只抓官网页面。
- AI coding 工具最有价值的信号在官网之外：**GitHub Releases / Commits / Stars**、**VS Code / JetBrains 插件市场**（评分与下载）、**SWE-bench / Aider polyglot / Terminal-Bench 榜单**、**社区（HN/Reddit/X/YouTube）**、底层模型定价。
- MCP 层已具备能力但从未被路由：`mcp_server/tools/` 有 `web_search` / `web_extract` / `github_stars` / `github_releases` / `github_commits` / `run_benchmark` / `analyze_pricing`，`SourceSelector` 从不把缺口路由过去。
- 结果：`ecosystem`（MCP server/扩展/IDE/agentic tool-use）与 `sentiment`（社区口碑）维度即使有专属分析器（设计文档 24）也无可用数据源，只能空转或回退。

## 2. 目标设计

1. **缺口 → 外部源路由**：为每个维度扩展候选源到官网之外——`ecosystem → GitHub + 插件市场`、`performance → 榜单源（设计文档 25）`、`sentiment → 社区源`、`roadmap → GitHub Releases`。
2. **统一候选模型**：`SourceCandidate` 增加 `kind`（web / spa / github / marketplace / benchmark / social），`GapExecutor.fetch_candidate` 按 `kind` 分发到对应采集实现；降级链、成功率提升、`sources_tried` 语义对全 kind 一致。
3. **可注入提供方**：外部源以 `ExternalSourceProvider` 接口注入（MCP 工具 / mock），测试不依赖真实网络。
4. **信任分级**：官方页 0.9 > 榜单/Release 0.85-0.9 > 市场 0.8 > 社区 0.6，按成功率进化调整（沿用 `set_success_rates`）。

## 3. 模块/接口设计

### 3.1 外部源提供方协议 `interfaces/data_source.py`（扩展）

```python
class ExternalSourceProvider(Protocol):
    kind: str            # "github" / "marketplace" / "benchmark" / "social"
    name: str            # 如 "github_releases"

    def supports(self, gap: InfoGap, competitor: Competitor) -> bool: ...

    def candidates(self, gap: InfoGap, competitor: Competitor) -> list[SourceCandidate]:
        """返回该提供方对缺口能产出的候选源（URL 或具名源）。"""
```

- `Competitor` 增可选结构信息 `external_refs: dict[str, str]`（如 `{"github_repo": "getcursor/cursor", "marketplace_id": "..."}`），注册表 / 发现器在补全 official_links 时一并填充（发现器可让 LLM 输出 `external_refs`）。

### 3.2 `SourceSelector` 扩展

- `__init__(self, providers: list[ExternalSourceProvider] | None = None)`。
- 路由表：

```python
_GAP_TO_KINDS: dict[str, list[str]] = {
    "pricing":    ["web"],                    # 官方定价页（现有）
    "feature":    ["web", "github"],          # 官方文档 + GitHub README/Releases
    "performance":["benchmark", "web"],       # 榜单优先（设计文档 25）
    "ecosystem":  ["github", "marketplace", "web"],   # 插件/扩展/集成
    "sentiment":  ["social", "web"],          # 社区口碑
    "roadmap":    ["github", "web"],          # Releases/Changelog
}
```

- `candidates()` 顺序：官方链接（现有逻辑）→ 遍历命中 kind 的 provider 追加候选（按 trust_level 降序）→ 成功率提升 → 去 `sources_tried` → `spa_extractor` 兜底仅针对官方 web 候选。

### 3.3 采集分发 `core/gap_executor.py`

- `fetch_candidate(gap, context, extractor, providers)` 按 `SourceContext.kwargs["kind"]` 分发：
  - `web` / `spa` → 现有 extractor 路径；
  - `github` / `marketplace` / `benchmark` / `social` → 查 provider 注册表，调用对应采集函数（封装 MCP 工具，如 `github_releases(repo)` / `web_search(query)`），失败抛 `DataSourceUnavailableError` 走降级。
- 采集结果统一包装为 `Observation`（`evidence.url` 填真实来源 URL，`trust_level` 用候选源值）。

### 3.4 内置 provider（`collector/providers/`）

| provider | kind | 数据源（MCP 工具） | 主要产出 |
|---|---|---|---|
| `GithubSourceProvider` | github | `github_stars` / `github_releases` / `github_commits` | 仓库活跃度、Release 版本时间线、commit 频率 |
| `MarketplaceSourceProvider` | marketplace | `web_extract`（VS Code/JetBrains 市场 URL） | 评分、下载量、插件数量 |
| `CommunitySourceProvider` | social | `web_search`（HN/Reddit/X 站点限定） | 社区提及、正负面信号、趋势 |
| `BenchmarkSourceProvider` | benchmark | `run_benchmark` / 榜单 URL 抓取 | SWE-bench / Aider / Terminal-Bench 分数（见设计文档 25） |

## 4. 接入方式

```
CompetitorAnalysisAPI.__init__
  └─ SourceSelector(providers=[GithubSourceProvider(), MarketplaceSourceProvider(),
                               CommunitySourceProvider(), BenchmarkSourceProvider()])
        ↑ 复用 §13 发现器注入的 web_tool / MCP 客户端；无 Key/无网络时 provider 返回空列表（正常降级到官网）
```

- 测试注入 mock provider（设计文档 11 的 `FakeExtractor` 模式）；`config.collector` 增加 provider 开关（`enable_github` / `enable_marketplace` 等，默认按维度开启）。
- 依赖顺序：设计文档 24（Ecosystem/Sentiment 分析器）与本项互相依赖——路由先落地，分析器再消费多源结果；建议先路由（本项）后分析器。

## 5. 验证方式

- **单测（路由）**：构造 `Competitor` 带 `github_repo` → `ecosystem` 缺口 candidates 含 `github_*` 与 `marketplace_*` 候选；`pricing` 缺口不含 github 候选；trust_level 排序官方 > 榜单 > 社区。
- **单测（分发）**：mock provider 返回候选 → `fetch_candidate` 按 kind 调到对应采集函数；provider 抛错 → 降级下一候选并记录 `sources_tried`。
- **单测（成功率进化）**：`set_success_rates` 提升某 kind 优先级；tried 源被跳过。
- **集成**：mock 全部 provider，`analyze("Cursor", dimensions=["ecosystem"])` 报告 ecosystem 维度证据来自 github/marketplace 候选而非空。
- **回归**：无 provider / provider 全空时行为与现状一致（仅官网）；全量测试不触发真实网络。

## 6. 实现优先级与工作量

- 优先级：**高**（P0，多源是 Ecosystem/Sentiment/榜单分析的底层依赖，§12.4 建议第 1 步）。
- 工作量：约 2-3 天。
  - 协议 + `Competitor.external_refs` + `SourceSelector` 路由：0.5-1 天；
  - 4 个内置 provider（封装 MCP 工具）：1-1.5 天；
  - `fetch_candidate` kind 分发 + 降级：0.5 天；
  - 测试：0.5 天。
- 前置：设计文档 11 测试基础设施（`FakeExtractor`）；复用 §13 的 `web_tool` 注入与 mock 模式。MCP 工具已存在，仅需薄封装。
