# 设计文档 61 — DISCOVERY 联网搜索能力接入（真实搜索 API + web_tool）

> 第十一轮后新增项。对应设计文档 20（自主发现竞品）的增强：`CompetitorDiscoverer` 的候选枚举链此前**无真实联网搜索**，普查任务"市面上常用的 coding agent"必落空。

## 1. 问题现状

- **现象**：Web 输入「帮我分析下市面上常用的coding agent」，前端已能出请求（LLM 解析为 `DISCOVERY`），但后端报 `分析异常: 未能发现任何竞品`。
- **根因链**（`core/competitor_discoverer.py::_search`）：
  1. **注册表命中**：任务文本不含任何注册表竞品名/别名 → 不命中（`_registry_hits` 返回空）。
  2. **联网搜索**：`self._web_tool` 为 `None` → 直接返回空（`_SEARCH` 分支被跳过）。
  3. 两条路都空 → `discover()` 返回空 → `facade/api.py` 抛 `ValueError("未能发现任何竞品")`。
- **断点**：各入口构造 `CompetitorAnalysisAPI` 时未注入 `web_tool`（默认 `None`）；且项目现有 `mcp_server/tools/web_tools.py::web_search` 仅是返回提示文案的**模拟实现**，未接真实搜索引擎。
- **影响**：任何"市场普查/发现"意图任务在当前代码下**必然 0 候选**，DISCOVERY 分支不可用。

## 2. 目标设计

1. **补齐真实联网搜索**：接入真实搜索 API（本周期先实现 **Tavily**，按策略模式留接口便于替换 SerpAPI/Bing 等），为普查任务提供候选竞品枚举来源。
2. **LLM 归纳候选**：把搜索返回的原始结果（title/url/snippet）用 LLM 归纳为`竞品清单（规范名 + official_links）`，作为 `CompetitorDiscoverer` 的 `web_tool` 注入——延续"发现器只管怎么找、LLM 负责提纯"的职责边界。
3. **零入口改动接入**：在 `CompetitorAnalysisAPI.__init__` 装配层自动构造 `web_tool`，Web/CLI/MCP 三入口自然受益。
4. **降级与安全**：未配 Key / 主开关关 / 搜索失败 → 维持现状报"未能发现任何竞品"（不编造，守设计文档 47）；Key 只从环境变量读取不落盘；候选 URL 抓用户时仍需 URL 守卫。

## 3. 模块/接口设计

### 3.1 搜索抽象（策略模式，先实现 Tavily）

**新文件：`competitor_agent/collector/search.py`**

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass

@dataclass
class SearchHit:
    title: str
    url: str
    snippet: str

class SearchProvider(ABC):
    """真实搜索引擎抽象：返回结构化原始结果，供上层 LLM 归纳为竞品候选。"""
    @abstractmethod
    def search(self, query: str, max_results: int = 8) -> list[SearchHit]: ...

class TavilySearchProvider(SearchProvider):
    """Tavily 实现：
    端点为 https://api.tavily.com/search（POST JSON，search_depth="basic"）；
    Key 从构造参数传入（由 build_search_provider 从环境变量 TAVILY_API_KEY 读取）；
    响应 results[] 的 title/url/content 映射为 SearchHit；
    请求失败抛可重试异常，交由上层降级（返回空）。"""

def build_search_provider(cfg: CollectorConfig) -> SearchProvider | None:
    """按 cfg.search_provider 名 + 环境变量 Key 构造 provider。
    - search_provider == "tavily" 且 TAVILY_API_KEY 存在 → TavilySearchProvider；
    - 其他/缺 Key/未知名 → None（不启用，保持现状）。"""
```

### 3.2 候选归纳（web_tool 本体）

```python
def web_search_candidates(task: str, provider: SearchProvider,
                          llm: LLMClient, max_results: int = 8) -> list[dict]:
    """搜索 task → hits → LLM 归纳为 [{"name","home","pricing","docs"}]。

    - provider.search 返回空 / 请求失败 → 返回 []（不编造）；
    - llm 归纳：复用 JsonLoadsArray 解析，容忍最外层对象包裹/前后噪声；
    - 返回签名匹配 CompetitorDiscoverer 的 web_tool: Callable[[str], list[dict]]。
    """
```

> **取消费换**：`web_search_candidates` 内部已完成"hits→候选"的 LLM 归纳；注入后 `CompetitorDiscoverer._dedupe_with_llm` 会对候选再做一次 LLM 去重/补全。该二次归纳无害（保持发现器契约零改动），仅多一次 LLM 调用，记为后续可优化点。

### 3.3 配置

`config/loader.py` 的 `CollectorConfig` 增两个字段（`_build_section` 自动按 YAML 填充）：
```python
@dataclass
class CollectorConfig:
    ...
    search_provider: str = ""     # "tavily" / ""；空 = 不启用联网搜索
    search_max_results: int = 8
```

`review_config.yaml` `collector` section 追加：
```yaml
collector:
  enable_external_sources: true   # 主开关：开联网搜索才接（保 CI/无网络测试时关闭不触发真实网络）
  search_provider: "tavily"
  search_max_results: 8
```
- **Key 不落 yaml**，仅环境变量 `TAVILY_API_KEY`（对齐 `security.auth_token` 从 env 读的模式）。
- `.env.example` 追加占位 `TAVILY_API_KEY=`（.env 已 gitignore）。

## 4. 接入方式

改 `facade/api.py::CompetitorAnalysisAPI.__init__` 发现器构造处（当前 [api.py:213-214](file:///d:/trae_projects/first-agent/competitor_agent/facade/api.py#L213-L214)）：

```python
search_web_tool = web_tool
if search_web_tool is None and use_llm and llm is not None \
        and cfg.collector.enable_external_sources:
    provider = build_search_provider(cfg.collector)
    if provider is not None:
        search_web_tool = lambda task: web_search_candidates(
            task, provider, llm, max_results=cfg.collector.search_max_results)
self._discoverer = CompetitorDiscoverer(
    llm=llm, use_llm=use_llm, web_tool=search_web_tool)
```

- Web/CLI/MCP 均经 `CompetitorAnalysisAPI` 装配，零改动自动受益。
- 显式传入 `web_tool`（测试/评测 mock）时仍优先，不覆盖。

**数据流**：
```
discover(task)
  → _search: 注册表命中？返回｜否则注入的 web_tool(task)
  → web_search_candidates: TavilySearchProvider.search → hits(title/url/snippet)
        → LLM 归纳 → [ {"name","home","pricing","docs"} ]
  → _dedupe_with_llm 二次去重/补全 → _to_competitors → 逐个 analyze → 品类报告
```

## 5. 验证方式

- **单测（provider）**：`test_search_provider.py` —— mock `httpx.post`：200 正常映射 title/url/snippet、空 results、非 2xx 抛异常、超时抛异常；`build_search_provider` 各组合（tavily+Key → 实例 / 缺 Key → None / 未知名 → None / search_provider="" → None）。
- **单测（候选归纳）**：mock `SearchProvider` 返回固定 hits + mock LLM 返回 JSON → `web_search_candidates` 输出规范候选；hits 为空 → []；LLM 返回畸形 → 抛 `ValueError`/空由上层降级。
- **单测（配置）**：`CollectorConfig` 新字段默认值与 YAML 解析；`enable_external_sources=false` 时不注入 web_tool。
- **集成**：构造 `CompetitorAnalysisAPI` 注入假 provider（返回固定候选）→ `discover(task)` 产出 list[Competitor] 而非抛"未能发现任何竞品"；未配 Key / 主开关关 → 行为与现状一致（报"未能发现任何竞品"）。
- **回归**：`tests/unit/core/test_competitor_discoverer.py` 全绿；`use_llm=False` 全链路不触发真实网络；单竞品 `analyze` 行为不变。

## 6. 实现优先级与工作量

- 优先级：**高**（DISCOVERY 分支当前完全不可用，普查任务是产品诉求）。
- 工作量：约 0.5-1 天。
  - `collector/search.py`（SearchHit/SearchProvider/TavilySearchProvider/build_search_provider/web_search_candidates）：0.3 天；
  - 配置字段 + review_config.yaml + .env.example：0.2 天；
  - `api.py` 装配注入：0.1 天；
  - 测试（provider/归纳/配置/集成）：0.2 天。
- 前置依赖：无（仅需 LLM 已可用 + 用户提供 TAVILY_API_KEY）。复用设计文档 20 的发现器与 `json_loads_array` 解析。

## 核心技术点总结

- 真实搜索抽象为可替换策略（`SearchProvider`），本周期仅 Tavily，预留 SerpAPI/Bing 扩展点。
- 候选枚举 = "搜索原始结果 → LLM 归纳为竞品清单"，沿发现器"只负责怎么找、LLM 负责提纯"的职责边界，不改发现器契约。
- 装配层零入口改动注入，主开关 `enable_external_sources` + 环境变量 `TAVILY_API_KEY` 门控，Key 不落盘。
- 无 Key / 主开关关 / 搜索失败均降级为"返回空"（不编造候选），保住设计文档 47 约束与 CI 无网络确定性。