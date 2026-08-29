# 设计文档 69 —— 第十九轮：真实搜索启用（问题 1）

> 第十九轮。能力**在代码里已就绪**（doc 66 §3.1），缺最后一公里——运行时配置：
> `TAVILY_API_KEY` 环境变量 + `enable_external_sources` 主开关。本文档为**启用与验证设计**。
>
> **范围调整**：问题 2（主 Agent 驱动报告格式）与问题 3（报告目录）已并入 **doc 70**《报告子系统统一设计》，
> 本文档只覆盖问题 1（真实搜索启用）。

## 1. 问题现状

用户实测：市场普查类任务里产品侧输出「搜索引擎 API 未接入，改用 web_extract 直接采集」。

**代码层早已就绪（doc 66 §3.1，2026-08-29 实现）**：

- `collector/search.py`：`SearchProvider`（ABC）→ `TavilySearchProvider`（httpx POST `https://api.tavily.com/search`，Bearer 鉴权）；
  `build_search_provider(cfg)`——`cfg.search_provider=="tavily"` **且** 环境变量 `TAVILY_API_KEY` 非空才返回 provider，否则 None；
  `web_search_candidates`（hits → LLM 归纳候选 `[{"name","home","pricing","docs"}]`）。
- `mcp_server/tools/web_tools.py::web_search`：真实 Tavily 调用；provider 为 None → 返回可读提示
  「搜索功能未启用：需要配置 TAVILY_API_KEY 且 collector.search_provider=tavily」——**用户看到的就是这条**。
- `facade/api.py::__init__`（装配零入口）：`use_llm && llm && enable_external_sources` 时 `build_search_provider` 非空 → 自动注入候选枚举 lambda（DISCOVERY 用）。

**缺的两样（已核实）**：

1. **`TAVILY_API_KEY` 环境变量不存在**（Process / User 两个作用域实测为空；仓库只有 `.env.example`，没有 `.env`；
   代码里**没有任何 `load_dotenv()`**——python-dotenv 仅声明在 pyproject.toml 未被调用，key 必须以真实系统环境变量形式在启动前存在）。
2. **`collector.enable_external_sources: false`**（`review_config.yaml:51`）——这是 DISCOVERY 候选枚举自动注入的**主门控**
   （`api.py` 装配 lambda 的 `and cfg.collector.enable_external_sources`）。即使有 key，false 时也不会自动枚举候选。

> 分层澄清：`web_search` **工具**（Lead/子 Agent 的 ReAct 工具）只依赖 env key（`search_provider: "tavily"` 已配好）；
> `enable_external_sources` 只门控 **DISCOVERY 候选自动注入**。二者都要开。

## 2. 启用设计

1. **设置 `TAVILY_API_KEY`**：仅作为**系统环境变量（User 作用域）**存在，`setx TAVILY_API_KEY <key>`。
   - ⚠️ **key 绝不写进任何仓库文件**（config/yaml/.env 都不落盘——`.env.example` 只留 `TAVILY_API_KEY=` 占位）。
   - ⚠️ `setx` 只对**新启动的进程**生效：现有 web_app 进程不会看到，必须重启。
2. **开启主开关**：`review_config.yaml` `collector.enable_external_sources: false → true`。
   - 附带效应（需知悉）：该开关同时门控 GitHub/插件市场/社区/榜单/舆情等外部源；但 `benchmark_provider`/`sentiment_provider` 当前为空
     （`review_config.yaml:62,65`），对应 provider 不启用，仅 web_extract/web_search/GitHub 类可用，行为安全。
3. **重启服务**：`python -m competitor_agent.web_app --port 8000`（顺带解决运行中进程跑旧 web_app.py 的引擎文案泄漏问题——doc 66 §3.5 过滤逻辑已提交，重启即生效）。

## 3. 验证方式

| 层 | 验证 | 判定 |
|---|---|---|
| Key 有效性 | `httpx` POST `https://api.tavily.com/search`（Bearer key，query="coding agent"） | 200 + `results[]` 非空 |
| 装配注入 | 起服后跑一次 DISCOVERY 任务，观察 Lead 是否调用 `web_search`/候选枚举出现 `discovery.candidate` 事件 | 出现候选而非「搜索功能未启用」 |
| 工具直连 | `web_search(query)` 返回真实 hits（标题/URL/摘要），而非可读提示 | 非「搜索功能未启用」文案 |
| 回归 | `pytest tests/unit/collector/test_search_provider.py`（16 条）+ `web` 相关单测 | 全绿 |

## 4. 回滚与安全

- 回滚：`setx TAVILY_API_KEY ""` + `enable_external_sources: false` + 重启即可回到纯 web_extract 降级。
- key 泄漏面：仅在进程内存与注册表（User env）；不写日志（`build_search_provider` 不打印 key；`web_search` 失败文案只带 status）。

## 5. 改动清单

| 项 | 改动 |
|---|---|
| 环境（不入 git） | `TAVILY_API_KEY` 系统环境变量 |
| `config/review_config.yaml` | `collector.enable_external_sources: true` |
| 运行 | 重启 web_app（新代码 + 新 env 生效） |

## 6. 实现优先级

- **M1（问题1）**：设 env key + 开开关 + 重启 + 验证——已授权，随本轮落地。
