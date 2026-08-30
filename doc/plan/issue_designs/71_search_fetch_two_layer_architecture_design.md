# 设计文档 71 —— 第二十一轮：搜索与抓取分离 + 免费主力/可选付费增强两层架构

> 第二十一轮。目标：把联网能力重构为「搜索层」与「抓取层」分离的两层架构，**免费优先、可选付费增强**：
>
> - **搜索层**：DuckDuckGo（免费）为主力，Tavily 为可选增强（配了 Key 才启用）；
> - **抓取层降级链**：trafilatura（本地解析）→ crawl4ai（本地浏览器渲染）→ Jina Reader（云端免费档兜底）；
> - **纯搜索模式**：`FETCH_ENABLED=false` 时完全禁用抓取层（只读搜索摘要，不抓正文）。
>
> 本文档为**设计**（不实现）。实现方向以 §7 已确认配置、§10 分阶段计划为准。
>
> **归档依据**：沿用 `doc/plan/issue_designs/` 系列既有归档方式（`咱编号_design.md` 命名、第 X 轮 header blockquote、分节含「问题现状 / 总体架构 / 接口设计 / 验证方式 / 实现优先级与工作量 / 核心技术点总结」、`README.md` 索引登记），格式模板参考最新的 **doc 70**（截至本文档为系列第 71 篇）。
>
> **已确认决策（2026-08-30 评审，6 项全按推荐）**：
> ① **搜索主力默认 DDG**——`search_provider` 默认 `"duckduckgo"`（无 Key 即开即用），Tavily 仍为可配增强；router 统一受 `enable_external_sources` 门控（§2.2 补强，含直达路径），同步更新「未配置提示」分支相关测试。
> ② **原地升级 `web_extract`**——不新增 `web_fetch` 工具名，保留原 `selector` 参数对齐 TOOL_SPECS schema；TOOL_SPECS/TOOLS/ReAct prompt 既有引用零改动，内部实现走三级降级链（§3.2）。
> ③ **顺带删除 `use_playwright` 死字段**——浏览器开关收敛到唯一 `crawler.browser_pool`（§1.3）。
> ④ **完整做 P3**——crawl4ai（extra + Chromium + Dockerfile target）本期落地，default `browser_pool=0` 仍默认关（§10）。
> ⑤ **web_search 文本块加 `via:{engine}·{time}` 标注**，同步更新 `test_tool_registry`/`test_search_assembly_66` 断言（§9）。
> ⑥ **`build_search_router` 唯一入口，`build_search_provider` 保留为向后兼容薄包装**（8 调用点/16 单测不破）。
>
> **实现说明（2026-08-30，P1-P6 全落地）**：
> ① **搜索层**：新 `collector/search_providers/ddg.py`（`DuckDuckGoSearchProvider`）+ `build_search_router`（enable_external_sources 主门控 + DDG 主力 + TAVILY_API_KEY 追加 Tavily 降级池）+ `SearchRouter`（主力命中即返、降级池接管、逐条 `source_engine`/`fetched_at` 标注）；`SearchHit` 加带默认值字段；`SearchError.kind`（network/rate_limited/http/parse）。**deviation（文档 §3.3 依赖 `ddgs>=8.0` → 改为直连 httpx 打 `html.duckduckgo.com/html/`）**：保持 MockTransport 可注入、零新依赖、与 §9「respx/MockTransport 拦截」验收一致；`[search]` extra 仅含 trafilatura。
> ② **抓取层**：`collector/fetch.py`（`FetchResult`/`FetchProvider`/`FetchRouter`/`build_fetch_router`/`_guarded_get` 逐跳重校验）+ `fetch_providers/`（trafilatura 本地 / crawl4ai 浏览器单例 + 后台事件循环 / jina_reader 云端，Key 可选提额）+ `fetch_policy.py`（`_is_shell` 隐性失败 + `FetchPolicy` per-run 上限/去重）+ `fetch_cache.py`（搜索 24h/正文 7d + URL 规范化）；`web_extract` 原地升级走链（`via:` 标注 + 上限/去重 + 磁盘缓存；`FETCH_ENABLED=false` → 固定禁用提示）。
> ③ **接线**：api.py DISCOVERY 注入改走 `build_search_router`；`_react_loop`/LangGraph 各建 per-run `FetchPolicy` 注入 Lead/子 Agent web_extract 闭包（`_web_extract_checked`，`_react_web_extract` 签名不变 → monkeypatch 测试不破）；**WebExtractor 保留**（§1.3 范畴外，ReAct 底层采集器不变）。
> ④ **配置/部署**：`CollectorConfig` 增 fetch_*/crawler_*/jina_reader_*/cache_ttl_*，**删 `use_playwright` 死字段**；`review_config.yaml` 嵌套 crawler/jina_reader 段（loader `_build_collector` 合并）+ env 优先级；`.env.example` 补 JINA_API_KEY/FETCH_*/CRAWL4AI_*；pyproject 增 `[search]`/`[crawl4ai]` extra + mypy ignore；Dockerfile 增可选 `crawler4ai` target。
> ⑤ **提示词/测试**：`react_system.py` 双版联网工具段（§8.1/§8.2，按 `fetch_enabled` 选版，Lead/子 Agent 共用）；新测试 47 条（`test_search_router_71`/`test_fetch_chain_71`/`test_fetch_policy_cache_71`/`test_web_tools_71`/`test_prompt_71` + test_url_guard 改写 + test_tool_registry/test_search_assembly_66 断言同步）；全量 unit 1034 passed / integration+e2e 66 passed / ruff+mypy 干净。
> **遗留（记录不实现）**：搜索缓存（FetchCache.get_search/set_search 已实现并单测）未接入 web_search——为保持 mock/benchmark 确定性，web_search 默认不查缓存；后续如需可接线（key 含 engine|query|max_results）。
>
> **子 agent 检视修复（2026-08-30，1 P0 + 9 P1 已修）**：① **crawl4ai SSRF**（P0）——浏览器导航自行跟随重定向，重定向目标不逐跳重校验；已加 fetch 前置 `guard_http_url` 兜底 + 文档化限制（默认 `browser_pool=0` 关闭）；② `canonical_url` 畸形端口（`:abc`）崩溃 → try/except 容错（保「不抛」契约）；③ `FetchPolicy` 并发竞态（并行子 Agent/并行 tool_calls 共享）→ 加 `threading.Lock`，get/record 原子化；④ **纯搜索模式 ReAct 路径未禁抓** → `_web_extract_checked` 按 `fetch_enabled` 短路返回固定禁用提示（§2.3/§5.4 对齐 MCP）；⑤ 超限占位文本被摄入知识库 → `_ingest_fetched` 排除「抓取次数已达上限」前缀；⑥ LangGraph 子 Agent 未共享 per-run policy → `_subagent_run` 传 `lg_fetch_policy`；⑦ CI 只装 `[dev]` 无 trafilatura 致默认链测试红 → trafilatura 入 `[dev]` extra（保默认链确定性）；⑧ `build_fetch_router` 空链文案与 FETCH_ENABLED 混淆 → 区分「已禁用」/「无可用 provider」；⑨ 磁盘缓存命中先于单跑上限判定（§6.1 语义）；⑩ crawl4ai `_ensure_loop`/arun 并发锁。全量 unit 1040 passed / integration+e2e 61 passed / ruff+mypy 干净。

---

## 0. 设计依据：免费优先的动机与本项目现状差距

联网能力当前是「付费单点（Tavily 搜索 + `web_extract` 直抓），无降级、无分离」：

| 目标 | 本项目现状 | 差距 |
|---|---|---|
| 搜索层主力免费（DDG） | 仅 Tavily（付费，需 Key；无 Key 时 `web_search` 走可读提示、DISCOVERY 空候选） | 无免费主力；付费单点无降级 |
| 抓取层三级降级 | 仅 httpx+bs4 直抓（`web_extract`/`web_extractor`），JS 重页必失败 | 无降级链、无浏览器渲染、无云端兜底 |
| 纯搜索模式开关 | 无「只看摘要不抓正文」的能力边界 | 缺 `FETCH_ENABLED` 主开关与对应 Agent 行为契约 |
| 缓存与成本控制 | 已有 `cache_ttl_seconds: 86400`（collector）但仅覆盖部分源 | 搜索/正文分 TTL、URL 去重、层级/降级可观测均缺 |

**已核实的事实（约束：不臆测，均实际读文件）**：
- 仓库**不存在**博查/Bocha（`grep -rniE "bocha|博查"` 零命中）；现有**付费搜索 provider 是 Tavily**（doc 61/66/69 落地，`collector/search.py`）。
- `trafilatura` / `crawl4ai` / `ddgs`（DDG）/ `jina_reader` 均**未引入**（`pyproject.toml` 无；代码无 import）——三层抓取与免费搜索全部**新增**。
- 抓取层现状 = httpx + BeautifulSoup：`mcp_server/tools/web_tools.py::web_extract`（str→str 契约）与 `collector/web_extractor.py::WebExtractor`（`ICompetitorDataSource` 契约）。前者将被「抓取抽象 + trafilatura 默认实现」替代；后者保留（作为独立 DataSource 走非 web_extract 的数据源采集路径，不在本期降级链范围）。

---

## 1. 问题现状

### 1.1 现有联网调用链（读完文件后的真实形态）

```
搜索调用链（付费单点）：
api.py::CompetitorAnalysisAPI.__init__（api.py:265-273）
  → build_search_provider(cfg.collector)            # collector/search.py:121
  → cfg.search_provider=="tavily" 且 TAVILY_API_KEY → TavilySearchProvider
  → 注入 web_tool=lambda task: web_search_candidates(...)   # DISCOVERY 候选枚举专用
同时，Lead/子 Agent 的 ReAct 工具面与 MCP 同一份：
  mcp TOOL_SPECS["web_search"] / ReAct web_search
  → web_tools.py::web_search(query, max_results)   # str→str：标题\nURL\n摘要 文本块
  → build_search_provider(...) → TavilySearchProvider.search → SearchHit[]

抓取调用链（httpx+bs4 直抓）：
mcp TOOL_SPECS["web_extract"] / ReAct web_extract
  → web_tools.py::web_extract(url, selector="")    # str→str：清洗后正文文本
  → guard_http_url(url)（doc 41 SSRF 守卫，重定向逐跳重校验）
  → httpx.get → BeautifulSoup 去 script/style → 截断 max_content_chars
另有独立数据源：collector/web_extractor.py::WebExtractor（ICompetitorDataSource）
```

### 1.2 现有搜索 provider 接口形态（改造后如何兼容）

`collector/search.py` 的策略抽象**保持不变**即是兼容基座：

```python
@dataclass
class SearchHit:          # 现：title/url/snippet
    title: str
    url: str
    snippet: str

class SearchProvider(ABC):
    @abstractmethod
    def search(self, query: str, max_results: int = 8) -> list[SearchHit]: ...

def build_search_provider(cfg: CollectorConfig) -> SearchProvider | None: ...
```

- `TavilySearchProvider` **保留**（既付费增强，接口零改动）。
- **Bocha 不存在**：若未来要加，只需新增一个 `BochaSearchProvider(SearchProvider)` 并在注册表加一个分支，无任何接口变更——本文档把它列为「预留适配器」，不当作现有物。
- 新增 `DuckDuckGoSearchProvider(SearchProvider)` 作免费主力。
- `web_search`（MCP/ReAct）与 `web_search_candidates`（DISCOVERY）**契约不变**，仅内部改走「多 provider 路由器」。

### 1.3 复用 / 废弃 / 新增清单

| 类别 | 文件 / 符号 | 处置 |
|---|---|---|
| 复用 | `collector/search.py`：`SearchHit`/`SearchProvider`(ABC)/`TavilySearchProvider`/`SearchError`/`web_search_candidates` | 全保留；`SearchHit` 加可选字段（见 §3.1） |
| 复用 | `web_tools.py::web_search`（str→str 契约） | 保留签名；内部改走搜索路由器 |
| 复用 | `web_tools.py::web_extract`（str→str 契约） | 保留签名；内部实现改走抓取链（§3.4/§4） |
| 复用 | `guard_http_url` / `resolve_redirect` 安全守卫（doc 41） | 抓取链每级沿用（防 SSRF） |
| 复用 | `config/loader.py::CollectorConfig` + `review_config.yaml` collector 段 | 增字段（§7），旧字段保留 |
| 新增 | `collector/search_providers/ddg.py`（`DuckDuckGoSearchProvider`） | 免费主力 |
| 新增 | `collector/search.py::build_search_router(cfg)` | 路由：DDG 主力 + 可选 Tavily 降级 |
| 新增 | `collector/fetch.py`（`FetchResult` 数据类 + `fetch_router` + 三级 chain） | 抓取层抽象与降级 |
| 新增 | `collector/fetch_providers/trafilatura_fetch.py` | 第 1 级（默认） |
| 新增 | `collector/fetch_providers/crawl4ai_fetch.py` | 第 2 级（浏览器渲染） |
| 新增 | `collector/fetch_providers/jina_fetch.py` | 第 3 级（云端兜底） |
| 新增 | `collector/fetch_cache.py` | 搜索/正文分级缓存 + URL 去重 |
| 新增 | `collector/fetch_policy.py` | 懒触发判定 + 单跑抓取上限（§5） |
| 新增 | `config/loader.py` 字段 + `review_config.yaml` + `.env.example` 项 | 全部配置（§7） |
| 废弃 | 无硬删；`web_extract` 的 bs4 直抓实现被 trafilatura 取代（函数名/契约保留） | 降级为 trafilatura 之前的「无依赖回退」备胎（可选） |
| 废弃 | `config/loader.py` 的 `use_playwright` 死字段（全库零消费方；2026-08-30 评审确认删除） | 浏览器渲染开关收敛到唯一 `crawler.browser_pool`（对齐 doc 46 工程一致性） |

---

## 2. 总体架构

### 2.1 分层架构图

```
                         ┌─────────────────────────────────────────────┐
                         │              Agent（Lead/子 Agent）            │
                         │   决策：先读摘要 → 判断是否触发抓取（§5 懒触发）    │
                         └───────────────┬───────────────────────────────┘
                                         │  ReAct 工具 / MCP 工具（TOOL_SPECS，str→str）
                       ┌─────────────────┴─────────────────┐
                       │           工具层（契约不变）            │
                       │  web_search / web_extract            │
                       └─────────────────┬─────────────────┘
                 ┌───────────────────────┴────────────────────────┐
                 │                Provider 抽象层                    │
                 │   search.py:  SearchProvider(SwitchHit)          │
                 │   fetch.py:    FetchResult + FetchProvider(ABC)  │
                 └───────────────────────┬─────────────────────────┘
        ┌────────────────────────────────┴──────────────────────────────┐
        │                         搜索层（§3.3）                          │
        │   build_search_router:  DDG(免费主力) → Tavily(配Key才注册,可选) │
        └────────────────────────────────┬──────────────────────────────┘
        ┌────────────────────────────────┴──────────────────────────────┐
        │                         抓取层（§3.4，三级降级）                  │
        │   fetch_router:  trafilatura(本地) → crawl4ai(本地渲染)         │
        │                  → jina_reader(云端)，全程挂 URL 守卫           │
        └───────────────────────────────────────────────────────────────┘
  缓存层 fetch_cache（§6）：搜索 24h / 正文 7d，URL 去重，单跑同 URL 只抓一次
```

### 2.2 免费主力 + 可选付费增强的注册机制

「付费 provider 仅在其相应 Key 存在时才注册」，集中在一个**路由构造函数**：

```python
def build_search_router(cfg: CollectorConfig) -> SearchRouter:
    """返回路由对象：主力 + 可选降级池。

    - 主力：cfg.search_provider 决定。空/"duckduckgo" → DDG（免 Key，恒可用）；
             "tavily" → 需 TAVILY_API_KEY 否则不启用并用 DDG 顶替。
    - 付费增强（可选降级）：TAVILY_API_KEY 存在 → 把 TavilySearchProvider 追加为降级池。
    - 返回的 router 永不抛「无可用 provider」：DDG 是兜底，至少一个在。
    """
```

- Key 只读环境变量、不落盘（对齐 doc 61/66 纪律）；**Key 存在 → 多一个付费可用项；Key 缺失 → 自动只留免费主力**，注册表/路由天然防呆。
- `enable_external_sources`（主门控，已有）仍决定「是否启用联网」；下述分层是「启用后选谁」。
- **2026-08-30 评审确认：`enable_external_sources=false` 时 router/fetch 构造一律返回 None**——现有 `web_search`/`web_extract` 的直达路径（CLI/MCP 不经 `api.py` 装配）只查 `build_search_provider` 不查主开关，切 DDG 默认后若不加此门控，`test_web_search_no_network` 等无网络用例会真实联网；router 内部统一校验，与 `api.py` 装配层门控一致。

### 2.3 纯搜索模式（FETCH_ENABLED=false）下架构如何变化

```
FETCH_ENABLED=false
  → fetch_router 构造为 None；web_extract 返回固定提示（不抛、不抓）：
      「抓取层已禁用（FETCH_ENABLED=false）。仅可依赖搜索摘要。」
  → 抓取缓存/懒触发/URL 去重 全链短路（不创建 provider、不触网络）。
  → Agent 行为规范切到纯搜索版（§8 版本二：仅摘要 + 置信度声明，禁核验式抓取）。
  → 搜索层完全不受影响（摘要照常），架构从「两层」退化为「单搜索层」。
```

---

## 3. 接口设计

### 3.1 统一返回结构

**搜索命中**：扩展现有 `SearchHit`（加两个**带默认值**的字段，既有构造方不受影响）：

```python
@dataclass
class SearchHit:
    title: str
    url: str
    snippet: str
    source_engine: str = ""   # "duckduckgo" / "tavily" / "bocha"（预留）
    fetched_at: float = 0.0   # epoch 秒；0 表示未记录（旧 provider 兼容）
```

**抓取结果**（新 `FetchResult`）：

```python
@dataclass
class FetchResult:
    success: bool
    url: str
    title: str = ""
    content: str = ""            # 清洗后的正文（≤ fetch_max_chars）
    provider: str = ""           # 实际命中级："trafilatura"|"crawl4ai"|"jina"
    reason: str = ""             # 失败原因（success=False 时必填，人可读）
    fetched_at: float = 0.0
```

字段含义：`success`=是否取到可用正文；`url`=最终落盘校验后的 URL；`title`=页标题（尽力而为，可为空）；`provider`=命中级（**链路标注 `via:`** 由此而来）；`reason`=三级全失败时的失败描述（含哪级、什么原因），不抛异常。

### 3.2 web_search / web_extract 完整签名（对外工具契约，保持 str→str）

> 对齐既有 MCP/ReAct 契约（`TOOL_SPECS` schema 不变，实现替换）。结构化 `SearchHit[]`/`FetchResult` 是内部传输，工具出口统一字符串，供 Lead/子 Agent 直接读。

```python
def web_search(query: str, max_results: int = 5) -> str:
    """（改实现，签名不变）
    正常：经 build_search_router → router.search(query, max_results)
          → 逐条 `标题\nURL\n摘·via:{source_engine}·{time}` 文本块，\n\n 分隔。
    空结果：`未搜索到与 {query!r} 相关的结果。`
    DDG 失败且无 Tavily 降级：`搜索暂不可用: {可区分文案，见 §4.1}`（不编造）。
    无可用 provider（理论不会，DDG 恒可用）：可读提示。
    """

def web_extract(url: str, selector: str = "", max_chars: int = 0) -> str:
    """（原地升级 web_extract，契约 str→str；2026-08-30 评审确认：不新增 web_fetch 工具名，
    保留原 selector 参数对齐 TOOL_SPECS schema，TOOL_SPECS/TOOLS/ReAct prompt 既有引用零改动）
    - max_chars 缺省 0 → 用 cfg.fetch_max_chars（缺省 8000，对齐 max_content_chars）。
    - URL 先过 guard_http_url（doc 41），重定向逐跳重校验。
    - 经 fetch_router.fetch(url, max_chars)：
        成功 → 返回正文文本（顶部可带 `via: trafilatura` 一行元信息，供 Agent 判断核验强度）。
        失败（三级全败）→ 返回 `抓取失败: {FetchResult.reason}`（+ URL），不抛异常。
    - FETCH_ENABLED=false → 返回固定提示（见 §2.3）。
    """
```

正常/错误返回结构（决策可见）：

| 场景 | 返回 | 是否抛异常 |
|---|---|---|
| 搜索命中 | 文本块（含 source_engine/时间） | 否 |
| 搜索空 | 明确「未搜索到」 | 否 |
| DDG 失败→Tavily 命中 | 文本块 + `via: tavily` | 否 |
| 全部搜索失败 | 「搜索暂不可用: …」（限流/网络可区分，§4.1） | 否 |
| 抓取成功（任一级） | 正文 + `via: {级}` | 否 |
| 抓取三级全败 | 「抓取失败: {reason}」 | 否（不冒泡） |
| 抓取被禁用 | 固定禁用提示 | 否 |

### 3.3 搜索层 provider

| provider | 类别 | 启用条件 | 依赖库 | 说明 |
|---|---|---|---|---|
| `DuckDuckGoSearchProvider` | 主力·免费 | 恒启用（免 Key） | `ddgs>=8.0`（纯 httpx，无 Key 无浏览器） | 非官方接口；§11 列限流风险 |
| `TavilySearchProvider` | 增强·付费 | 现有 `TAVILY_API_KEY`（已有可复用） | `httpx`（已硬依赖） | 接口零改动保留 |
| `BochaSearchProvider` | 预留·付费 | 未来加 Key 项 | —（现无该库） | 当前**不存在**，仅留注册桩与文档 |

搜索路由器：

```python
class SearchRouter(SearchProvider):
    """主力 + 降级池。主调用成功命中即返回；主力抛 SearchError → 依次降级池。"""
    def search(self, query: str, max_results: int = 8) -> list[SearchHit]: ...
    source_engine 逐条标注实际命中引擎。
```

### 3.4 抓取层 provider（按降级顺序）

| 级 | provider | 定位 | 启用条件 | 依赖库 | 速度量级 |
|---|---|---|---|---|---|
| 1 | `trafilatura` | 本地解析（默认路径） | 恒启用（本地库，**无 Key**） | `trafilatura>=1.8`（可选 extra `search`） | 毫秒级 |
| 2 | `crawl4ai` | 本地浏览器渲染（JS 重页） | **默认禁用（可选启用）**：本地库无 Key；需装额外 extra `crawl4ai` + `crawl4ai-setup` 下载 Chromium；装好且 `crawler.browser_pool>0` 才注册到链。默认 `fetch_fallback_chain=["trafilatura","jina_reader"]`，crawl4ai 按需插入第 2 级 | `crawl4ai>=0.6`（可选 extra `crawl4ai`，重，+~200MB） | 秒级 |
| 3 | `jina_reader` | 云端兜底 | 恒注册（GET `https://r.jina.ai/{url}`）；无 Key 限 20 次/分，有 `JINA_API_KEY` 带 Bearer 提额 | 无额外库（httpx） | 秒级 |

> **Key 纪律**：trafilatura 与 crawl4ai 为**本地库，不需要也不设计任何 API Key** 类配置；Jina 的 Key 可选（仅提额）。

```python
class FetchProvider(ABC):
    @abstractmethod
    def fetch(self, url: str, max_chars: int) -> FetchResult: ...

def build_fetch_router(cfg) -> FetchRouter | None:
    """FETCH_ENABLED=false → None（纯搜索模式）。
    启用 → 按 cfg.fetch_fallback_chain 组链；crawl4ai 默认不在链中（可选启用，
    须 extra+浏览器就绪且 browser_pool>0 才插入），默认两级 trafilatura → jina_reader。
    全程挂 URL 守卫 + 缓存 + 懒触发（§5）。"""
```

---

## 4. 降级与路由策略

### 4.1 搜索层：DDG 失败时

- **优先**：有 `TAVILY_API_KEY`（已注册增强）→ 降级 Tavily，命中结果标 `via: tavily`。
- **否则**：返回结构化错误（工具层 str），**不编造**。
- **限流与普通网络错误在日志中可区分**：统一错误类型带 `kind` 字段枚举——`SearchError(kind="rate_limited")`（HTTP 429 / DDG 的 202-anomaly-response）与 `SearchError(kind="network")`（连接/超时/5xx）。`logger` 分别记 `search.rate_limited` / `search.network_error` 两组字段，供 §6 统计降级率。

```python
class SearchError(RuntimeError):
    def __init__(self, message, *, kind: str = "network", **kw):
        super().__init__(message); self.kind = kind  # "network"|"rate_limited"|"http"|"parse"
```

判定：DDG `ddgs` 库对限流返回特殊响应（HTTP 202 + anomaly 提示）或 429 → 判 rate_limited；连接差错/超时/≥500 → network。

### 4.2 抓取层三级降级判定

逐级尝试，命中即停；成功级写入 `FetchResult.provider`（`via:`）。

> 缺省链为**两级** `trafilatura → jina_reader`（零 Key 零重依赖）；crawl4ai 作为可选中间级，装有 extra+浏览器且 `browser_pool>0` 才插入第 2 位，成为三级链。下文"三级降级"以启用 crawl4ai 为准。

| 级失败判定 | 明细 |
|---|---|
| 硬失败（立即降级） | HTTP ≥400 / 连接超时 / 异常抛错 → 记该级失败原因 |
| **隐性失败（HTTP 200 但内容空壳）** | ① 清洗后正文 `len < 80` 字符；② 命中反爬提示词正则（`enable javascript` / `please enable js` / `access denied` / `captcha` / `verify you are human` / `just a moment`）；③ 标题/正文含明显占位。任一如触发 → 判该级失败，**降级到下一级** |

```python
# fetch_policy.py
_ANTI_BOT_PATTERNS = re.compile(
    r"enable\s+javascript|please\s+enable\s+js|verify\s+you\s+are\s+human|"
    r"just\s+a\s+moment|access\s+denied|captcha|cf\.link|challenge", re.I)

def _is_shell(text: str) -> bool:
    """判隐性失败：过短或含反爬提示 → True，触发降级。"""
    t = (text or "").strip()
    if not t:
        return True
    if len(t) < 80:                       # 正文过短（空壳）
        return True
    if _ANTI_BOT_PATTERNS.search(t[:2000]):  # 反爬提示词集中在首 2K
        return True
    return False
```

### 4.3 三级全失败

- 返回 `FetchResult(success=False, url=url, reason="trafilatura: 空壳/HTTP 403; crawl4ai: 未安装; jina: 20次/分限流")`——**封装为可读 reason，不抛异常**（工具层 str 出口天然安全）。
- 成功响应在正文首行标注实际层级 → `via: trafilatura` / `via: crawl4ai` / `via: jina`，Agent 依据层级判断核验强度（本地解析 > 浏览器渲染 > 云端转译）。

### 4.4 crawl4ai 资源管理（避免每次降级冷启动浏览器）

- **进程内单例复用**：模块级懒构造一个 `AsyncWebCrawler`，请求之间复用同一浏览器实例（`crawler_pool` 默认 1，可配 0=禁用该级）。
- **回收策略**：空闲超时（`CRAWL4AI_TIMEOUT`，默认 30s）+ 7 天 LRU 强制重建；异常（浏览器崩溃）时捕获并重建一次性实例，记 `crawl4ai.reset` 日志（不计入正文，仅计数）。
- **弃用率护栏**：若构建期 `crawl4ai-setup` 未装浏览器 → 该级注册为"不可用"（`fetch` 返回 reason "crawl4ai 浏览器未安装"直接降级，**不试图运行中拉浏览器**），避免运行时静默冷启动。

---

## 5. 抓取层的懒触发设计（重点）

### 5.1 默认行为

两步法：**Agent 先只看搜索摘要**（`web_search` 命中），能回答则**不触发** `web_extract`；只有判定确实需要才抓。这是省成本的默认路径。

### 5.2 具体可执行判定规则（写入系统提示词 + 代码护栏）

下列任一条件满足 → 触发抓取正文：
1. 摘要不含所需**数字/明细**（如定价数字、榜单分数、发布时间），且该事实将写入报告；
2. 需要**核验来源**（摘要来自二手转载，需落到官网页/原文）；
3. 结论将写入报告、且属**事实性断言**（定价/版本/榜单/发布），必须核验到一手/接近一手来源；
4. 摘要含糊/冲突（多条命中互相矛盾或都过短），需正文裁决。

不触发：摘要已含全部所需事实；纯观点性/口碑性内容；CHAT 闲聊分支（Doc 64 意图门控已拦截，天然不抓）。

### 5.3 单跑抓取上限（防失控）

- 每次任务运行（一次 `run()` / 一次 analysis）内 `web_extract` **有效调用上限 = `FETCH_MAX_PER_RUN`（缺省 6）**。
- 超出 → 工具返回 `抓取次数已达上限（本任务 6 次），请基于现有摘要作答，剩余疑点记为待核验。`（不抛，Agent 换策略）。
- URL 去重（§6）：同一 URL 本任务只抓一次，重复调用直接命中缓存，**不重复计数**。

### 5.4 纯搜索模式（FETCH_ENABLED=false）下 Agent 行为调整

- 系统提示词切 §8 版本二：**明确告知「抓取层已禁用，无法核验细节」**。
- Agent 允许、且应当基于摘要作答，但**必须附带置信度声明**：凡结论依赖未核验细节 → 标注「未核验，置信度下调」，并把缺失事实列入 `gaps_pending` / 报告「待核验」段。
- `web_extract` 调用会被工具层直接禁（返回固定提示），Agent 不应反复尝试。

---

## 6. 缓存与成本控制

### 6.1 缓存设计

| 维度 | key 构成 | TTL | 存储 |
|---|---|---|---|
| 搜索 | `search:{engine}:{sha256(query|max_results)}` | **24h** | 磁盘 JSON 文件 `{data_dir}/cache/search/{key}.json` |
| 正文 | `fetch:{sha256(canonical_url)}` | **7d** | 磁盘 `{data_dir}/cache/fetch/{key}.json`（正文 + via + fetched_at） |

- 存储介质选型：**本地磁盘小 JSON 文件**（非 Redis/DB）——理由：无外部依赖、跨进程共享（web/CLI/MCP）、单文件幂等；项目已有 `data_dir` 卷挂载持久化（doc 55）天然承接；规模（单任务 <8 搜索/6 抓取）远未到需缓存服务的量级。备选：后续量大再上 Redis（接口预留 `CacheBackend(ABC)`）。
- **URL 去重**：规范化（去 fragment、统一 scheme/host 大小写）；同 URL 本任务只抓一次。
- **单跑去重表**：存于运行上下文（`FetchPolicy` per-run 实例），跨 `web_extract` 调用共享；命中同 run 去重 → 不重抓、不计上限。

### 6.2 日志字段

每条搜索/抓取记结构化 `logger.info`（含 `extra`）：

```
搜索: engine, query(截断), max_results, hits, latency_ms, rate_limited(bool), degraded_from(降级来源)
抓取: url, via(命中层级), latency_ms, chars, cached(bool), dedupe(bool), attempted[int级别的编码]
降级事件: fallback_event("search:ddg→tavily" / "fetch:1→2" / "fetch:shell(200空壳)"), trigger
缓存: cache_hit(bool), cache_key, ttl_seconds
```

### 6.3 统计口径

在 report/batch 落盘点聚合出（不必实际落库，可延展到 doc 54 trace）：

- 各层级命中率：`trafilatura` 命中数 / 总抓取数；
- 降级率：发生 `fallback_event` 的次数 / 总调用数（搜索、抓取分别）；
- 缓存命中率：`cached==True` / 总调用；
- 单次分析成本与耗时分布：累计 `latency_ms` 聚合（搜索 vs 抓取）、近似费用（Tavily/Jina 计量查询量；DDG/trafilatura=0）。

---

## 7. 配置项清单

### 7.1 环境变量

> ⚠️ trafilatura 与 crawl4ai 为**本地库，不需要任何 API Key**，本文档不为其设计 Key 类配置；Jina Key 可选（仅提额）。

| 名称 | 用途 | 必填 | 缺省行为 |
|---|---|---|---|
| `TAVILY_API_KEY` | 搜索层付费增强（保留现有） | 否 | 缺 → 仅免费 DDG，降级池无 Tavily |
| `JINA_API_KEY` | Jina Reader 提额（`Authorization: Bearer`） | 否 | 缺 → 用免费档（限 20 次/分） |
| `FETCH_ENABLED` | 纯搜索模式总开关 | 否 | `1`（抓取层启用）；`0/false` → 完全禁用 |
| `FETCH_MAX_PER_RUN` | 单次分析最大抓取次数（防失控） | 否 | `6` |
| `FETCH_MAX_CHARS` | 抓取正文长度上限 | 否 | `8000`（对齐 `max_content_chars`） |
| `CRAWL4AI_HEADLESS` | crawl4ai 浏览器无头模式 | 否 | `true`（服务端无显示器） |
| `CRAWL4AI_TIMEOUT` | crawl4ai 单次抓取超时 + 空闲回收秒数 | 否 | `30` |

### 7.2 review_config.yaml `collector` 段新增

```yaml
collector:
  # ...已有字段保留（enable_external_sources 主门控、search_provider、search_max_results 等）
  search_provider: "duckduckgo"     # 主力："duckduckgo"(免Key) | "tavily"(需Key)；Bocha 预留
  fetch_enabled: true               # == FETCH_ENABLED 的 yaml 侧（env 优先）
  fetch_max_per_run: 6              # 懒触发上限，== FETCH_MAX_PER_RUN
  fetch_max_chars: 8000             # 正文上限
  fetch_fallback_chain: ["trafilatura", "jina_reader"]  # 降级顺序；crawl4ai 默认关，启用后插入第 2 级
  crawler:
    headless: true                  # == CRAWL4AI_HEADLESS（仅启用时生效）
    timeout: 30                     # == CRAWL4AI_TIMEOUT（仅启用时生效）
    browser_pool: 0                 # 默认 0=禁用该级；>0 且 extra+浏览器就绪才注册（1=单例）
  jina_reader:
    enabled: true                   # 云端兜底开关
  cache_ttl_search_hours: 24        # 搜索缓存 TTL（缺省沿用现有 cache_ttl_seconds=86400）
  cache_ttl_fetch_days: 7           # 正文缓存 TTL
```

`CollectorConfig` 加对应 dataclass 字段（`_build_section` 自动按 YAML 填充，同现有模式）。env 优先级 > yaml：`FETCH_ENABLED=0` 时忽略 yaml `fetch_enabled`。

### 7.3 启动校验逻辑

启动时（`load_config` + 首次构造 router）校验并 `logger.warning/error` 输出「实际启用的 provider 及其运行条件」：

- 未启用联网（`enable_external_sources=false`）→ 明确提示搜索/抓取均不可用，但**放行**（无网络测试需此分支）。
- `search_provider="tavily"` 但缺 `TAVILY_API_KEY` → **降级为 DDG**（不再静默不可用，日志提示「tavily 缺 Key，回落 duckduckgo」）。
- `crawl4ai` extra 未装 / 浏览器未 `crawl4ai-setup` → 该级标「不可用」，日志提示运行 `pip install -e .[crawl4ai] && crawl4ai-setup`，链路降为 2 级。
- **无可用搜索 provider**（理论上不应发生，DDG 恒可用）→ 抛 `RuntimeError` 明确报错（而非静默返回空）。
- `FETCH_ENABLED=false` → 打印「纯搜索模式：抓取层禁用」。

---

## 8. Agent 行为规范

> 写入 `agent/prompts/react_system.py`（Lead/子 Agent 共用段），按 `fetch_enabled` 选版。
> §8.1/8.2 是"工具纪律层"的两个版本；§8.3–8.5 定义这套提示词如何分层、如何按 plan 做两阶段任务适配（进度状态：§8.3/8.4/8.5 为设计草案，尚未落地 react_system.py）。

### 8.1 版本一：正常模式（懒触发两步法）

```
## 联网工具用法（两次调用原则）
你拥有两个联网工具：
- web_search(query)：只看**搜索摘要**。命中摘要已含所需事实 → 直接采用，停止这一步。
- web_extract(url)：抓取**正文**。仅当满足任一条件才调用：
    1) 摘要缺你写报告所需的数字/明细（定价、榜单分、版本、时间）；
    2) 需核验来源（摘要来自转载，要落到官网/原文）；
    3) 结论是事实性断言并将写入报告（定价/版本/榜单/发布），必须核验一手来源；
    4) 多来源摘要含糊或冲突，需正文裁决。
  否则默认用摘要，不 fetch（省成本）。
纪律：
- 单次任务 fetch 调用上限 6 次；同一 URL 只抓一次。超限后基于已有摘要作答。
- 先搜索、后按需抓取；不要为了凑证据乱抓。
- web_extract 返回的 via: 层级用于判断可核验强度：trafilatura/crawl4ai(本地) > jina(云端转译)。
- 抓取失败（返回"抓取失败/未搜索到"）→ 如实标注「该事实待核验」，不要编造替代证据。
```

### 8.2 版本二：纯搜索模式（仅摘要 + 置信度声明）

```
## 联网工具用法（纯搜索模式）
本环境**已禁用抓取层**（FETCH_ENABLED=false），你只有 web_search，没有 web_extract。
- 依据搜索摘要作答；摘要的时效与准确度有限。
- **置信度声明纪律**：凡结论依赖未核验的细节（数字、版本、榜单、精确定价），
  必须在报告/回答中明确标注「未核验，置信度下调」，并把该缺失事实记入待核验段，不装作已知。
- 摘要冲突时，列出双方并说明无法核验，不武断选一方。
- 调用 web_extract 会被工具层拒绝（返回固定提示）；若误调，忽略该提示，继续用摘要作答。
```

### 8.3 系统提示词分层结构（§8.1/8.2 只是其中一层，如何融入完整提示词骨架）

§8.1/8.2 的联网纪律段不是孤立存在的，而是整套系统提示词的**工具纪律层**。参考主流 open-source agent 的分层骨架（Claude Code "constitution" 主提示 + 逐工具细则 + 子 Agent；MetaGPT 角色提示 + 标准化输出 schema；AutoGPT 任务声明），把本项目已有雏形梳理为五层：

| 层 | 内容 | 注入点 | 是否随任务变 |
|---|---|---|---|
| ① 身份·宪章 | Lead/子 Agent "你是…" 职责声明，恒定不变 | `react_system.build_lead_system_prompt` / `build_subagent_system_prompt` | 恒有 |
| ② 工具纪律层 | §8.1/8.2 联网两条纪律（fetch 上限、`via:` 层级、纯搜置信度声明） | `_web_tool_section(_fetch_enabled_from_config())` | by `fetch_enabled` |
| ③ 任务适配层 | 报告结构 / 推理原则，按 plan 选版 | §8.4（两阶段） | by `plan.format_hint`/`resolution` |
| ④ 记忆·上下文层 | 历史技能 / 教训 / 知识库片段 | `enrich_prompt`（skills/notes/knowledge） | 每次动态注入 |
| ⑤ 输出 schema 层 | PLAN/REPORT/SUBAGENT JSON 契约 | `react_schemas.py` | by `plan_first`/角色 |

关键纪律（主流实现的首要结论，也对齐本项目 doc 70 的"正文优先/模板保底"）：**宪章层恒定、任务适配层后置（渐进披露）**——前置上下文保持精简，只把任务专属结构在需要时注入，避免一次塞满稀释模型注意力、也保可测性（prompt 是程序，需可单测，见 `test_prompt_71.py`）。

### 8.4 两阶段任务适配：plan 产生后才能定调报告结构（补齐 doc 70 M2 的结构落点）

**现状缺口（已核实）**：`build_lead_system_prompt()` 在循环启动前（facade/api.py:891/1050）即构造完毕，而 `plan` 是循环内**首次 make_plan 之后**才落到 `loop.plan`（react_loop.py `_on_plan`）。因此 doc 70 M2 的 `output_intent`/`format_hint`/`need_history` 目前只存在于**静态文案**里作"提示"，不是**结构级驱动**——"根据用户的问题灵活调整"受此天花板约束。

**设计：把系统提示拆成两阶段，让 plan 真正参与构建**
- **阶段一（规划）**：瘦 prompt = 身份 + 工具纪律层 + "首步必须 make_plan"，只够模型完成规划，不提前塞报告结构。
- **阶段二（执行/出报告）**：`ReactLoop._on_plan` 拿到 `loop.plan` 后，**原位 replace/追加一条系统消息**，按 `plan.format_hint` 选择报告结构、按 `plan.resolution` 选择推理原则，再继续后续 ReAct 轮次。这复用现有 `loop.plan` 输送管道，不改 make_plan/schema 契约。

**`format_hint` 枚举化**：现为自由字符串（`react_schemas.PLAN_SCHEMA` 仅 `{"type":"string"}`），建议收敛为 `compare|deep_single|trend_tracking|open` 四型，每型配一段"报告结构脚手架"注入阶段二：
- `compare` → 维度×竞品 横向矩阵结构 + §8.5 对比推理原则；
- `deep_single` → 分维度深挖 + 证据链 + 取舍；
- `trend_tracking` → 基线（as_of）→ 变化 → 归因，顺带 `need_history=true` 复用维度级历史（doc 70 M3）；
- `open` → 不注入结构，交回模型按两段式兜底（当前行为）。

建议在 `make_plan` 校验层做一次 enum 归一：非法/缺省一律回退 `open`，避免模型乱填导致变体错配（登记为 §11 风险 8）。

### 8.5 对比推理强化（resolution=compare/discovery 时注入）

现状对 COMPARE 的段落（`build_lead_system_prompt` 中 "若任务是市场普查/多竞品对比" 段）只讲**编排动作**（枚举候选 → delegate 批量委派 → aggregate_report），没有约束**对比怎么做**——对比质量天花板悬在聚合那一步的推理上。

设计：新增 `comparison_reasoning` skill（复用 `_with_skills` 注入机制，仿 `fact_verification`/`confidence_disclosure`），`resolution∈{compare,discovery}` 时注入明文原则：
- 同一维度**横向并列**对比，不逐家写小传；
- 给 **best-per-dimension**（对齐 `report_exporter._best_for_dim` 的状态+置信度排序）与"谁在何维度赢/输/空缺"；
- 暴露 **trade-off/取舍**，不交流水账；
- 指出**覆盖缺口**（缺失维度标"待核验/无数据"），不假装都有。

对比清单里各竞品的候选子 Agent 用整竞品 schema（doc 62 §3.4，逐维度正交），正好支撑阶段二的横向矩阵渲染，无需二次猜测维度归属。

---

## 9. 测试与验收方案

| 验证路径 | 模拟方法 | 预期结果 |
|---|---|---|
| DDG 正常搜索 | `respx`/`MockTransport` 拦截 ddgs 请求返回固定 hits | `web_search` 出文本块 + `via: duckduckgo`；`SearchHit.source_engine=="duckduckgo"` |
| DDG 限流降级 | mock DDG 抛 `SearchError(kind="rate_limited")`，且注入假 Tavily | 命中 Tavily 结果、`via: tavily`；日志 `search.rate_limited` 计数 +1 |
| DDG 失败（无 Tavily） | mock 抛 network 错误，`TAVILY_API_KEY` 空 | 返回「搜索暂不可用」结构化文案，**不编造**；`search.network_error` 计数 |
| 抓取三级逐级降级 | mock provider：trafilatura 返回 200 空壳（`_is_shell` 触发）→ 次用 crawl4ai 成功 | 结果 `via: crawl4ai`；`fetch:1→2` 事件；且 crawl4ai 未收到 trafilatura 也成功的重复调用 |
| 制造 trafilatura 提取失败 | mock `trafilatura.extract` 返回 None/过短 | 判定隐性失败，链路自动接管 crawl4ai（验证 `_is_shell`） |
| crawl4ai 不可用（浏览器未装） | 该级注册为不可用 | 链路变 2 级，直落 jina；日志提示安装 |
| Jina 兜底 | mock r.jina.ai 200 + 有/无 `JINA_API_KEY` | 有 Key → 请求带 `Authorization: Bearer`；无 Key → 不限 Key 头（且命中限流次数计费计数） |
| 三级全失败 | 三 provider 全 mock 失败 | 工具返回「抓取失败: reason」，**不抛异常**；reason 含各级原因 |
| 纯搜索模式开关 | `FETCH_ENABLED=false` | `build_fetch_router→None`；`web_extract` 返回固定禁用提示；Agent 提示词切版本二；搜索仍可用 |
| 缓存命中 | 同一 query/URL 调两次 | 第一次落盘、第二次 `cached==True` 不重发网络；TTL 内过期不重抓 |
| URL 去重 + 单跑上限 | 同 URL 调 3 次 + 累计超 FETCH_MAX_PER_RUN | 同 URL 只抓一次、不重复计上限；超上限返回「已达上限」提示 |
| 启动校验 | 缺 Key / 未装 crawl4ai / enable=false | 日志按 §7.3 明确提示；无可用搜索 provider → 抛明确 RuntimeError（构造形异常路径） |

（回归：现有 `test_search_provider.py` 16 条——`SearchHit` 加字段带默认值不影响现有构造；`web_search`/`web_extract` 契约不变；全量 unit + integration 不回归。）

---

## 10. 实施计划

| 阶段 | 内容 | 改动文件 | 工作量 | 依赖 | 可独立验证产出 |
|---|---|---|---|---|---|
| **P1 最小可用**（零成本跑通） | DDG 搜索 + trafilatura 抓取，两层打通；FETCH_ENABLED 开关 | 新增 `collector/search_providers/ddg.py`、`collector/fetch.py`、`collector/fetch_providers/trafilatura_fetch.py`；改 `search.py`(router)、`web_tools.py`、`loader.py`、`review_config.yaml`、`.env.example`、`pyproject`(extra `search`) | 1 天 | 无新 key | `web_search` 免费出摘要；`web_extract` trafilatura 命中 `via: trafilatura`；纯搜模式开关生效；P1 单测绿 |
| P2 免费搜索降级 | P1 路由抽象 + Tavily 增强注册（复用现有） | 改 `build_search_router` 降级池；`SearchError.kind` 区分 | 0.3 天 | P1 | DDG 失败→Tavily 命中；限流/网络日志可区分 |
| P3 抓取三级降级 | crawl4ai + jina_reader 两级；`_is_shell` 隐性失败检测 | 新增 `fetch_providers/crawl4ai_fetch.py`、`jina_fetch.py`；`fetch_policy.py`；`loader.py`；`pyproject`(extra `crawl4ai`)；Dockerfile 加 crawl4ai-setup 步骤（可选 target） | 1 天 | P1 | 三级逐级降级全链路；`via:` 标注；crawl4ai 资源复用 |
| P4 懒触发 + 上限 + 缓存 | `fetch_policy.py`（懒触发 5 条 + per-run 上限）+ `fetch_cache.py`（24h/7d + URL 去重） | 新增 `fetch_cache.py`；`fetch_policy.py`；`web_tools.py` 接上限 | 0.5 天 | P1–P3 | 摘要充足不抓；超上限拦截；缓存命中不重发；同 URL 只抓一次 |
| P5 Agent 行为规范 + 可观测 | 双版系统提示词 + 结构化日志/统计 | `agent/prompts/react_system.py`（双版）；日志 extra | 0.3 天 | P4 | 懒触发两句法进提示词；纯搜模式置信度声明；§6.3 统计可聚合 |
| P6 测试/验收收口 | §9 全路径 + 回归 | `tests/unit/collector/test_search_router*.py`、`test_fetch_chain*.py`、`test_fetch_policy.py`、`test_fetch_cache.py` | 0.5 天 | P1–P5 | §9 验收路径逐条绿 + 回归绿 |

**依赖表**：P1←无；P2←P1；P3←P1；P4←P3；P5←P4；P6←P5。总工作量约 **3.5–4 天**。

**Dockerfile 中新加 crawl4ai 部署写法**（P3，可选 extra target，不进 slim/full 默认以省体积）：

```dockerfile
# 可选：启用 crawl4ai 浏览器渲染抓取（体积 +~200MB，仅需渲染级抓取时启用）
FROM python:3.12-slim AS crawler4ai
COPY competitor_agent/ /app/competitor_agent/
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install "/app/competitor_agent[crawl4ai]" \
    && python -m crawl4ai.setup --quick     # 下载 Chromium 二进制（crawl4ai-setup）
# 或运行时首次装（浏览器写入可写 VOLUME /data，避免构建层体积）：CMD 前执行
#   python -m crawl4ai.setup --quick && uvicorn ...
```

---

## 11. 风险与权衡

| # | 风险 | 影响 | 监控 | 兜底预案 |
|---|---|---|---|---|
| 1 | **DDG 非官方接口**：无 SLA、反爬/限流/随时改版 | 主力搜索不稳 | `search.rate_limited` 计数、429 比率、连续降级告警 | Tavily 增强始终可注册；`SearchProvider` 抽象允许换免费主力（如 Bing/SerpAPI 免费档） |
| 2 | **crawl4ai 资源开销 + 首次部署成本**：Chromium ~200MB + 内存占用 | 部署体积/运行内存↑ | 实例池 `browser_pool`、空闲回收日志 `crawl4ai.reset` | **默认禁用**（`browser_pool=0`，默认链不含该级）；按需 extra + Docker target 启用；启用时浏览器单例 + 超时回收。**SSRF 限制（2026-08-30 子 agent 检视确认）**：浏览器导航自行跟随重定向，重定向目标不逐跳重校验（`_guarded_get` 的 httpx 路径无此问题）；已加 fetch 前置 `guard_http_url` 兜底，启用该级前须接受此限制或走代理/禁用重定向 |
| 3 | **Jina 免费档 20 次/分耗尽** | 第三级瞬时限死 | jina 429 / 限流计数 | 429 即降级为该 URL 失败（reason 标注限流）；有 `JINA_API_KEY` 提额；正文缓存 7d 缓解重复抓取 |
| 4 | **trafilatura 对非主流结构提取失败率高** | 默认路径噪声大 | `fetch:1→2` 降级率、`trafilatura` 命中内容过短率 | `_is_shell` 隐性判定 → 自动接管 crawl4ai/jina；`fetch_fallback_chain` 可配置级序 |
| 5 | **纯搜索模式准确率损失** | 未核验细节结论置信度↓ | 报告置信度/`gaps_pending` 统计 | 强制 §8.2 置信度声明纪律 + 缺失事实入待核验段；`gaps_pending` 已进报告数据模型（doc 66） |
| 6 | **缓存过期风险**（7d 正文 / 24h 搜索） | 用了陈旧数据 | 缓存 TTL、`fetched_at` 时间线 | `via`+`fetched_at` 暴露给 Agent 判断时效；`cache_ttl_*` 可下调；定时/周报任务（doc 67 scheduler）天然重拉 |
| 7 | **DDG/Tavily 返回竞品需求外的噪声 / 搜索解析漂移** | 候选枚举/摘要失真 | `SearchHit` 解析异常率、空结果率 | `web_search_candidates` LLM 二次归纳兜底（已有 doc 61）；解析失败判 `kind="parse"` 计入降级 |
| 8 | **§8.4 format_hint 枚举化后模型乱填 / 变体错配** | 按用户问题定调的结构注入错位 | 变体分布、非法 format_hint 回退率 | `make_plan` 校验层 enum 归一，非法/缺省一律回退 `open`（两段式兜底）；conv 分支（doc 64）不参与，天然无此风险 |

---

## 核心技术点总结

- **两层重构，免费优先**：搜索层 DDG 免费主力 + Tavily 可选付费增强（配 Key 才注册）；抓取层 `trafilatura→crawl4ai→jina_reader` 三级降级，默认路径零成本、毫秒级。
- **兼容既有**：`SearchProvider`/`SearchHit`/`web_search`（str→str）/`web_extract` 契约全保留（`SearchHit` 仅加带默认值字段）；Tavily 保留为增强；`guard_http_url`（doc 41）贯穿盲取每级防 SSRF。
- **纯搜索模式**：`FETCH_ENABLED=false` 短路抓取层 + 工具返回固定提示 + Agent 行为切双版提示词（仅摘要 + 置信度声明）。
- **懒触发收敛成本**：摘要充足不抓、事实/核验/冲突才抓、单跑上限 `FETCH_MAX_PER_RUN=6`、同 URL 只抓一次。
- **可观测可统计**：搜索/正文分级缓存（24h/7d）、限流与网络错误可区分（`SearchError.kind`）、`via:` 层标注、降级率/命中率/缓存命中率聚合。
- **构建纪律**：本地库无 Key；crawl4ai 的 Chromium 通过可选 extra + `crawl4ai-setup` 纳入部署（Docker target）。
- **提示词五层 + 两阶段任务适配（§8.3–8.5，设计草案）**：宪章/工具纪律/任务适配/记忆/输出 schema 五层分层（宪章恒定、适配后置）；make_plan 后按 `plan.format_hint` 选报告结构、按 `resolution` 注入 `comparison_reasoning` 对比推理原则——治好"按用户问题灵活定调"只停在静态文案的天花板（doc 70 M2 的 plan 字段真正接进构建器）。