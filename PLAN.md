# 项目重构计划：多领域 Agent 框架

> 目标：验证"领域可插拔"声明，新增 GitHub Issue Analysis Agent 作为第二领域，同时解决其他 P0 问题。

---

## 一、现状分析

### 当前结构（简化）

```
dota_helper/
├── agent/              # 核心框架（领域无关 ✓）
├── interfaces/         # 协议接口（领域无关 ✓）
├── memory/             # 四层记忆（领域无关 ✓）
├── mcp_client/         # MCP 客户端（领域无关 ✓）
├── engines/            # 引擎组件（领域无关 ✓）
├── parallel/           # 并行执行（领域无关 ✓）
├── observability/      # 可观测性（领域无关 ✓）
├── secret_vault.py     # 凭据管理（领域无关 ✓）
├── data_path_manager.py
│
├── mcp_server/         # Dota 工具（领域相关）
├── domain_types/       # Dota 数据模型（领域相关）
├── data_source/        # Dota 数据源（领域相关）
├── analyzers/          # Dota 分析器（领域相关）
├── orchestrator/       # Dota 编排器（领域相关）
├── report/             # Dota 报告（领域相关）
├── persistence/        # Dota 持久化（领域相关）
├── facade/             # Dota API 门面（领域相关）
├── llm/                # LLM 客户端（领域无关，但配置耦合）
├── prompts/            # Dota YAML 提示词（领域相关）
├── web_app.py          # Dota Web 服务（领域相关）
└── api.py              # Dota API 入口（领域相关）
```

### 关键发现

1. **`agent/` 目录确实是领域无关的** — 使用 Protocol 接口，没有硬编码 Dota 引用
2. **`ReactSystemPrompt` 的 `_SYSTEM_ROLE_TEMPLATE` 硬编码了 "Dota 2 赛后复盘分析助手"** — 需要参数化
3. **`DotaHelperReActAgent` 类名带 Dota 前缀** — 需要重命名
4. **`IMatchDataSource` / `IReviewAnalyzer` 接口名带 Match/Review 前缀** — 需要泛化
5. **`BudgetDecision` 枚举在 `domain_types/enums.py` 中** — 是通用概念，应移到框架层
6. **`web_app.py` 硬编码了 Dota 特定的全局变量和路由** — 需要工厂化
7. **`api.py` 和 `facade/api.py` 重复** — `api.py` 是旧版，`facade/api.py` 是新版

---

## 二、目标结构

```
agent_framework/                    # 共享核心框架（完全领域无关）
├── __init__.py
├── agent/
│   ├── __init__.py
│   ├── react_agent.py              # 重命名：DotaHelperReActAgent → ReActAgent
│   ├── react_loop.py
│   ├── tool_dispatcher.py
│   ├── tool_guard.py
│   ├── tool_registry.py
│   ├── session_manager.py
│   ├── response_parser.py
│   ├── rag_engine.py
│   ├── rag_plugin.py
│   ├── injection_guard.py
│   ├── error_classifier.py
│   ├── circuit_breaker.py
│   ├── message_bus.py
│   ├── plugin.py
│   └── prompts/
│       └── react_system.py         # 修改：role_name 参数化
├── interfaces/
│   ├── __init__.py
│   ├── llm.py                      # ILLMClient — 不变
│   ├── memory.py                   # IFourLayerMemory — 不变
│   ├── data_source.py              # 重命名：IMatchDataSource → IDataSource
│   ├── analyzer.py                 # 重命名：IReviewAnalyzer → IAnalyzer
│   ├── report.py                   # IReportBuilder — 不变
│   ├── strategy.py                 # IStrategicLoop — 不变
│   ├── verifier.py                 # IStopVerifier — 不变
│   ├── compressor.py               # IContextCompressor — 不变
│   ├── budget.py                   # IIterationBudget — 不变
│   ├── tracer.py                   # ITracer — 不变
│   └── skill.py                    # ISkillStore — 不变
├── mcp_client/
│   ├── __init__.py
│   ├── client.py                   # MCPClient — 不变
│   └── types.py                    # ToolInfo — 不变
├── memory/
│   ├── __init__.py
│   ├── four_layer_memory.py        # FourLayerMemory — 不变
│   ├── session_archive.py          # 不变
│   ├── persistent_notes.py         # 不变
│   ├── skill_store.py              # 不变
│   └── dream_recap.py              # 不变
├── engines/
│   ├── __init__.py
│   ├── budget.py                   # 新增：BudgetDecision 枚举移入
│   ├── compressor.py               # ContextCompressor — 不变
│   ├── stop_verifier.py            # StopVerifier — 不变
│   ├── prompt_builder.py           # PromptBuilder — 不变
│   └── data_formatter.py           # 不变
├── parallel/
│   ├── __init__.py
│   ├── parallel_runner.py          # 不变
│   ├── subagent.py                 # 不变
│   └── task_queue.py               # 不变
├── observability/
│   ├── __init__.py
│   ├── logger.py                   # 不变
│   ├── tracer.py                   # 不变
│   ├── noop_tracer.py              # 不变
│   ├── metrics.py                  # 不变
│   └── langfuse_adapter.py         # 不变
├── secret_vault.py                 # SecretVault — 不变
└── data_path_manager.py            # DataPathManager — 不变

domains/
├── __init__.py                     # 领域注册表
│
├── dota/                           # 现有 Dota 领域（迁移）
│   ├── __init__.py
│   ├── facade/
│   │   ├── __init__.py
│   │   ├── api.py                  # PostMatchReviewAPI
│   │   └── entrypoint.py           # create_default_api
│   ├── mcp_server/
│   │   ├── __init__.py
│   │   ├── server.py
│   │   ├── tools/                  # 8 模块，53 工具
│   │   └── helpers/
│   ├── domain_types/
│   │   ├── __init__.py
│   │   ├── match_data.py
│   │   ├── report.py
│   │   ├── analysis.py
│   │   ├── state.py
│   │   ├── enums.py                # 移除 BudgetDecision（已移到框架层）
│   │   ├── strategy.py
│   │   ├── events.py
│   │   └── exceptions.py
│   ├── data_source/
│   │   ├── __init__.py
│   │   ├── opendota_client.py
│   │   ├── match_fetcher.py
│   │   ├── cache.py
│   │   ├── data_validator.py
│   │   └── exceptions.py
│   ├── analyzers/
│   │   ├── __init__.py
│   │   ├── base.py
│   │   ├── laning_analyzer.py
│   │   ├── teamfight_analyzer.py
│   │   ├── economy_analyzer.py
│   │   ├── decision_analyzer.py
│   │   ├── vision_analyzer.py
│   │   ├── skill_driven.py
│   │   └── fallback_analyzer.py
│   ├── orchestrator/
│   │   ├── __init__.py
│   │   ├── review_orchestrator.py
│   │   ├── strategic_loop.py
│   │   ├── tactical_loop.py
│   │   ├── runtime.py
│   │   ├── review_config.py
│   │   └── background_reviewer.py
│   ├── report/
│   │   ├── __init__.py
│   │   ├── report_builder.py
│   │   ├── markdown_renderer.py
│   │   └── progress_emitter.py
│   ├── persistence/
│   │   ├── __init__.py
│   │   ├── review_repository.py
│   │   └── progress_store.py
│   ├── llm/
│   │   ├── __init__.py
│   │   ├── client.py
│   │   └── token_counter.py
│   ├── prompts/                    # Dota YAML 提示词
│   ├── knowledge_base/
│   ├── resources/
│   ├── review_config.yaml
│   └── tests/
│
├── github_issue/                   # 新增：GitHub Issue 分析领域
│   ├── __init__.py
│   ├── facade/
│   │   ├── __init__.py
│   │   ├── api.py                  # GitHubIssueAnalysisAPI
│   │   └── entrypoint.py           # create_default_github_api
│   ├── mcp_server/
│   │   ├── __init__.py
│   │   ├── server.py               # FastMCP "GitHub Issue Analyzer"
│   │   ├── tools/
│   │   │   ├── __init__.py
│   │   │   ├── issue_tools.py      # 6 工具
│   │   │   ├── repo_tools.py       # 3 工具
│   │   │   ├── search_tools.py     # 2 工具
│   │   │   ├── label_tools.py      # 2 工具
│   │   │   ├── comment_tools.py    # 2 工具
│   │   │   └── stats_tools.py      # 2 工具
│   │   └── helpers/
│   │       ├── __init__.py
│   │       ├── github_client.py    # GitHub REST API 客户端
│   │       └── text_processing.py
│   ├── domain_types/
│   │   ├── __init__.py
│   │   ├── issue.py                # GitHubIssue, IssueComment
│   │   ├── report.py               # IssueAnalysisReport
│   │   ├── analysis.py             # AnalysisResult, AnalysisContext
│   │   ├── state.py                # IssueAnalysisState
│   │   ├── enums.py                # IssueStatus, Priority, IssueCategory
│   │   └── exceptions.py           # IssueAnalysisError
│   ├── data_source/
│   │   ├── __init__.py
│   │   ├── github_client.py        # GitHub API 封装
│   │   └── issue_fetcher.py        # 实现 IDataSource
│   ├── analyzers/
│   │   ├── __init__.py
│   │   ├── classification_analyzer.py   # Bug/Feature/Question 分类
│   │   ├── priority_analyzer.py         # 优先级评估
│   │   ├── sentiment_analyzer.py        # 评论情感分析
│   │   ├── similarity_analyzer.py       # 重复 Issue 检测
│   │   └── resolution_analyzer.py       # 解决方案建议
│   ├── orchestrator/
│   │   ├── __init__.py
│   │   ├── issue_orchestrator.py   # 主编排器
│   │   ├── analysis_loop.py        # 分析循环
│   │   └── issue_config.py         # 配置
│   ├── report/
│   │   ├── __init__.py
│   │   ├── report_builder.py
│   │   └── markdown_renderer.py
│   ├── prompts/                    # GitHub YAML 提示词
│   │   ├── classification.yaml
│   │   ├── priority.yaml
│   │   └── resolution.yaml
│   └── tests/
│       ├── __init__.py
│       ├── conftest.py
│       ├── unit/
│       │   ├── test_classification_analyzer.py
│       │   ├── test_priority_analyzer.py
│       │   ├── test_similarity_analyzer.py
│       │   └── test_github_client.py
│       └── integration/
│           └── test_github_api.py

web_app/                            # 重构：领域无关的 Web 服务
├── __init__.py
├── app.py                          # FastAPI 工厂函数
├── middleware.py                    # CORS / 日志 / 认证
└── frontend/                       # 共享前端

run_server.py                       # 更新：支持 --domain 参数
run_web_app.py                      # 新增：Web 入口
```

---

## 三、实施步骤

### Phase 1：提取核心框架（`agent_framework/`）

#### 1.1 创建目录结构

```bash
mkdir agent_framework
mkdir agent_framework/agent/prompts
mkdir agent_framework/interfaces
mkdir agent_framework/mcp_client
mkdir agent_framework/memory
mkdir agent_framework/engines
mkdir agent_framework/parallel
mkdir agent_framework/observability
```

#### 1.2 移动并修改文件

| 源文件 | 目标文件 | 改动 |
|--------|---------|------|
| `dota_helper/agent/__init__.py` | `agent_framework/agent/__init__.py` | 重命名 `DotaHelperReActAgent` → `ReActAgent` |
| `dota_helper/agent/react_agent.py` | `agent_framework/agent/react_agent.py` | 类名重命名，更新所有 import |
| `dota_helper/agent/react_loop.py` | `agent_framework/agent/react_loop.py` | 更新 import，`BudgetDecision` 从 `domain_types` → `engines.budget` |
| `dota_helper/agent/tool_dispatcher.py` | `agent_framework/agent/tool_dispatcher.py` | 更新 import |
| `dota_helper/agent/tool_guard.py` | `agent_framework/agent/tool_guard.py` | 更新 import |
| `dota_helper/agent/tool_registry.py` | `agent_framework/agent/tool_registry.py` | 更新 import |
| `dota_helper/agent/session_manager.py` | `agent_framework/agent/session_manager.py` | 更新 import |
| `dota_helper/agent/response_parser.py` | `agent_framework/agent/response_parser.py` | 更新 import |
| `dota_helper/agent/rag_engine.py` | `agent_framework/agent/rag_engine.py` | 更新 import，KB 路径改为可配置 |
| `dota_helper/agent/rag_plugin.py` | `agent_framework/agent/rag_plugin.py` | 更新 import |
| `dota_helper/agent/injection_guard.py` | `agent_framework/agent/injection_guard.py` | 更新 import |
| `dota_helper/agent/error_classifier.py` | `agent_framework/agent/error_classifier.py` | 更新 import |
| `dota_helper/agent/circuit_breaker.py` | `agent_framework/agent/circuit_breaker.py` | 更新 import |
| `dota_helper/agent/message_bus.py` | `agent_framework/agent/message_bus.py` | 更新 import |
| `dota_helper/agent/plugin.py` | `agent_framework/agent/plugin.py` | 更新 import |
| `dota_helper/agent/prompts/react_system.py` | `agent_framework/agent/prompts/react_system.py` | **关键改动**：`role_name` 参数化 |
| `dota_helper/interfaces/__init__.py` | `agent_framework/interfaces/__init__.py` | 重命名接口 |
| `dota_helper/interfaces/analyzer.py` | `agent_framework/interfaces/analyzer.py` | `IReviewAnalyzer` → `IAnalyzer` |
| `dota_helper/interfaces/data_source.py` | `agent_framework/interfaces/data_source.py` | `IMatchDataSource` → `IDataSource` |
| `dota_helper/interfaces/*.py` | `agent_framework/interfaces/*.py` | 更新 import，移除 Dota 类型引用 |
| `dota_helper/mcp_client/*` | `agent_framework/mcp_client/*` | 更新 import |
| `dota_helper/memory/*` | `agent_framework/memory/*` | 更新 import |
| `dota_helper/engines/*` | `agent_framework/engines/*` | 更新 import，`BudgetDecision` 移入 `budget.py` |
| `dota_helper/parallel/*` | `agent_framework/parallel/*` | 更新 import |
| `dota_helper/observability/*` | `agent_framework/observability/*` | 更新 import |
| `dota_helper/secret_vault.py` | `agent_framework/secret_vault.py` | 不变 |
| `dota_helper/data_path_manager.py` | `agent_framework/data_path_manager.py` | 默认路径改为 `~/.agent_framework/` |

#### 1.3 `react_system.py` 关键改动

```python
# 旧：硬编码 Dota 角色
_SYSTEM_ROLE_TEMPLATE = """你是 Dota 2 赛后复盘分析助手..."""

# 新：参数化角色
_SYSTEM_ROLE_TEMPLATE = """你是 {role_name}，具备专业的 {domain} 分析能力。

你可以通过调用工具来获取数据，并为用户提供深入的分析和建议。

## 可用工具

{tool_descriptions}

## 推理格式

...（通用格式，不变）...

## 角色边界（安全规则）

1. 你是一个 {domain} 领域分析 Agent。
...
"""

class ReactSystemPrompt:
    def build(
        self,
        tool_descriptions: str,
        skills: Optional[List[Dict[str, Any]]] = None,
        role_name: str = "通用分析助手",
        domain: str = "通用",
        extra_instructions: Optional[str] = None,
    ) -> str:
        prompt = self._role_template.format(
            role_name=role_name,
            domain=domain,
            tool_descriptions=tool_descriptions,
        )
        if extra_instructions:
            prompt += f"\n\n## 领域特定说明\n\n{extra_instructions}"
        if skills:
            prompt += _SKILL_INJECTION_TEMPLATE.format(...)
        return prompt
```

#### 1.4 `BudgetDecision` 枚举迁移

从 `dota_helper/domain_types/enums.py` 移到 `agent_framework/engines/budget.py`：

```python
# agent_framework/engines/budget.py
from enum import Enum

class BudgetDecision(Enum):
    CONTINUE = "continue"
    STOP = "stop"
    ESCALATE = "escalate"
```

---

### Phase 2：迁移 Dota 领域（`domains/dota/`）

#### 2.1 创建目录并移动文件

```bash
mkdir -p domains/dota/{facade,mcp_server/{tools,helpers},domain_types,data_source,analyzers,orchestrator,report,persistence,llm,prompts,knowledge_base,resources,tests/{unit,integration,performance}}
```

#### 2.2 文件迁移清单

| 源路径 | 目标路径 | 改动 |
|--------|---------|------|
| `dota_helper/facade/*` | `domains/dota/facade/*` | import: `dota_helper.*` → `agent_framework.*` + `domains.dota.*` |
| `dota_helper/mcp_server/*` | `domains/dota/mcp_server/*` | import 更新 |
| `dota_helper/domain_types/*` | `domains/dota/domain_types/*` | 移除 `BudgetDecision`（已移到框架层） |
| `dota_helper/data_source/*` | `domains/dota/data_source/*` | import 更新 |
| `dota_helper/analyzers/*` | `domains/dota/analyzers/*` | import 更新 |
| `dota_helper/orchestrator/*` | `domains/dota/orchestrator/*` | import 更新 |
| `dota_helper/report/*` | `domains/dota/report/*` | import 更新 |
| `dota_helper/persistence/*` | `domains/dota/persistence/*` | import 更新 |
| `dota_helper/llm/*` | `domains/dota/llm/*` | import 更新 |
| `dota_helper/prompts/*` | `domains/dota/prompts/*` | 不变（YAML 文件） |
| `dota_helper/knowledge_base/*` | `domains/dota/knowledge_base/*` | 不变 |
| `dota_helper/resources/*` | `domains/dota/resources/*` | 不变 |
| `dota_helper/review_config.yaml` | `domains/dota/review_config.yaml` | 不变 |
| `dota_helper/tests/*` | `domains/dota/tests/*` | import 更新 |
| `dota_helper/api.py` | 删除（已被 `facade/api.py` 替代） | — |
| `dota_helper/web_app.py` | 删除（由 `web_app/app.py` 替代） | — |

#### 2.3 `domains/dota/__init__.py`

```python
"""Dota 2 赛后复盘领域"""
from domains.dota.facade.api import PostMatchReviewAPI
from domains.dota.facade.entrypoint import create_default_api

__all__ = ["PostMatchReviewAPI", "create_default_api"]
```

---

### Phase 3：新增 GitHub Issue 分析领域（`domains/github_issue/`）

#### 3.1 领域能力

| 能力 | 说明 |
|------|------|
| Issue 分类 | Bug / Feature / Question / Documentation |
| 优先级评估 | Critical / High / Medium / Low |
| 情感分析 | 评论中的用户情绪（frustration, urgency） |
| 重复检测 | 基于文本相似度检测重复 Issue |
| 解决方案建议 | 基于已关闭的相似 Issue 推荐解决方案 |
| 统计报告 | 仓库 Issue 健康度、响应时间、分类分布 |

#### 3.2 工具清单（17 个）

| 模块 | 工具 | 说明 |
|------|------|------|
| `issue_tools.py` | `get_issue` | 获取 Issue 详情 |
| | `list_issues` | 按状态/标签/排序列出 Issues |
| | `search_issues` | 搜索 Issues |
| | `get_issue_timeline` | Issue 时间线事件 |
| | `get_issue_events` | Issue 事件日志 |
| | `get_issue_comments_count` | Issue 评论统计 |
| `repo_tools.py` | `get_repo` | 仓库元数据 |
| | `list_labels` | 仓库标签列表 |
| | `get_contributors` | 贡献者统计 |
| `search_tools.py` | `search_code` | 代码搜索 |
| | `search_issues_global` | 全局 Issue 搜索 |
| `label_tools.py` | `add_labels` | 添加标签 |
| | `remove_label` | 移除标签 |
| `comment_tools.py` | `list_comments` | 列出评论 |
| | `add_comment` | 添加评论 |
| `stats_tools.py` | `issue_stats` | Issue 统计（按时间/标签/状态） |
| | `response_time_stats` | 响应时间统计 |

#### 3.3 核心文件

**`domains/github_issue/facade/api.py`** — 主入口

```python
class GitHubIssueAnalysisAPI:
    """GitHub Issue 分析统一入口"""

    async def analyze_issue(self, repo: str, issue_number: int) -> IssueAnalysisReport:
        """分析单个 Issue"""
        ...

    async def analyze_repo_issues(
        self, repo: str, state: str = "open", limit: int = 10
    ) -> List[IssueAnalysisReport]:
        """批量分析仓库 Issues"""
        ...

    async def analyze_stream(
        self, repo: str, issue_number: int
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """流式分析（SSE）"""
        ...
```

**`domains/github_issue/domain_types/issue.py`** — 数据模型

```python
@dataclass
class GitHubIssue:
    repo: str
    number: int
    title: str
    body: str
    state: str          # open / closed
    labels: List[str]
    assignees: List[str]
    created_at: str
    updated_at: str
    closed_at: Optional[str]
    comments: int
    user: str

@dataclass
class IssueComment:
    id: int
    user: str
    body: str
    created_at: str
    updated_at: str
```

**`domains/github_issue/domain_types/report.py`** — 分析报告

```python
@dataclass
class IssueAnalysisReport:
    repo: str
    issue_number: int
    title: str
    classification: IssueCategory     # BUG / FEATURE / QUESTION / DOCS
    priority: Priority                # CRITICAL / HIGH / MEDIUM / LOW
    sentiment: str                    # 情感分析结果
    similar_issues: List[Dict]        # 相似 Issue
    resolution_suggestions: List[str] # 解决方案建议
    analysis_text: str                # 完整分析文本
    confidence: float
    token_cost: int
    analysis_time: float
```

**`domains/github_issue/data_source/github_client.py`** — GitHub API 封装

```python
class GitHubClient:
    """GitHub REST API 异步客户端"""

    def __init__(self, token: Optional[str] = None):
        self._token = token or os.getenv("GITHUB_TOKEN")
        self._client: Optional[httpx.AsyncClient] = None

    async def get_issue(self, repo: str, number: int) -> Dict[str, Any]: ...
    async def list_issues(self, repo: str, state: str = "open", **kwargs) -> List[Dict]: ...
    async def get_comments(self, repo: str, issue_number: int) -> List[Dict]: ...
    async def search_issues(self, query: str, **kwargs) -> List[Dict]: ...
    async def get_repo(self, repo: str) -> Dict[str, Any]: ...
    async def list_labels(self, repo: str) -> List[Dict]: ...
```

**`domains/github_issue/data_source/issue_fetcher.py`** — 实现 `IDataSource`

```python
class IssueFetcher:
    """实现 IDataSource 协议，为框架提供 Issue 数据"""

    def __init__(self, github_client: GitHubClient):
        self._client = github_client

    async def fetch(self, repo: str, issue_number: int) -> GitHubIssue:
        """获取并结构化 Issue 数据"""
        raw = await self._client.get_issue(repo, issue_number)
        comments = await self._client.get_comments(repo, issue_number)
        return GitHubIssue(
            repo=repo,
            number=raw["number"],
            title=raw["title"],
            body=raw.get("body", ""),
            state=raw["state"],
            labels=[l["name"] for l in raw.get("labels", [])],
            assignees=[a["login"] for a in raw.get("assignees", [])],
            created_at=raw["created_at"],
            updated_at=raw["updated_at"],
            closed_at=raw.get("closed_at"),
            comments=raw.get("comments", 0),
            user=raw["user"]["login"],
        )
```

**`domains/github_issue/analyzers/classification_analyzer.py`** — 分类分析器

```python
class ClassificationAnalyzer:
    """Issue 分类分析器：Bug / Feature / Question / Documentation"""

    async def analyze(self, issue: GitHubIssue, comments: List[IssueComment]) -> Dict:
        """基于 LLM 对 Issue 进行分类"""
        prompt = self._build_prompt(issue, comments)
        response = await self._llm_client.chat(prompt)
        return self._parse_response(response)
```

**`domains/github_issue/analyzers/similarity_analyzer.py`** — 重复检测

```python
class SimilarityAnalyzer:
    """基于 TF-IDF + 余弦相似度的重复 Issue 检测"""

    def __init__(self, threshold: float = 0.7):
        self._threshold = threshold
        self._vectorizer = TfidfVectorizer(analyzer="char", ngram_range=(2, 4))

    async def find_similar(
        self, issue: GitHubIssue, candidates: List[GitHubIssue]
    ) -> List[Dict]:
        """在候选列表中查找相似 Issue"""
        ...
```

**`domains/github_issue/orchestrator/issue_orchestrator.py`** — 主编排器

```python
class IssueOrchestrator:
    """GitHub Issue 分析编排器"""

    def __init__(
        self,
        data_source: IssueFetcher,
        classification_analyzer: ClassificationAnalyzer,
        priority_analyzer: PriorityAnalyzer,
        sentiment_analyzer: SentimentAnalyzer,
        similarity_analyzer: SimilarityAnalyzer,
        resolution_analyzer: ResolutionAnalyzer,
        report_builder: IssueReportBuilder,
    ):
        ...

    async def analyze(self, repo: str, issue_number: int) -> IssueAnalysisReport:
        """执行完整 Issue 分析流水线"""
        # 1. 获取数据
        issue = await self._data_source.fetch(repo, issue_number)
        comments = await self._data_source.fetch_comments(repo, issue_number)

        # 2. 并行分析（各分析器独立运行）
        classification, priority, sentiment, similar = await asyncio.gather(
            self._classification_analyzer.analyze(issue, comments),
            self._priority_analyzer.analyze(issue, comments),
            self._sentiment_analyzer.analyze(comments),
            self._similarity_analyzer.find_similar(issue, ...),
        )

        # 3. 生成解决方案建议
        resolutions = await self._resolution_analyzer.analyze(
            issue, classification, similar
        )

        # 4. 构建报告
        return self._report_builder.build(
            issue=issue,
            classification=classification,
            priority=priority,
            sentiment=sentiment,
            similar_issues=similar,
            resolutions=resolutions,
        )
```

---

### Phase 4：重构 Web 服务（`web_app/`）

#### 4.1 `web_app/app.py` — 工厂函数

```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

def create_app(domain: str = "dota") -> FastAPI:
    """创建 FastAPI 应用，注册指定领域的路由"""
    app = FastAPI(title=f"{domain.capitalize()} Agent")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    if domain == "dota":
        from domains.dota.web.routes import router as dota_router
        app.include_router(dota_router, prefix="/api")
    elif domain == "github_issue":
        from domains.github_issue.web.routes import router as github_router
        app.include_router(github_router, prefix="/api")

    app.mount("/", StaticFiles(directory="web_app/frontend", html=True), name="frontend")
    return app
```

#### 4.2 领域路由

每个领域提供自己的 `routes.py`：

```python
# domains/dota/web/routes.py
from fastapi import APIRouter
router = APIRouter()

@router.post("/review")
async def start_review(match_id: str): ...

@router.get("/review/{id}/status")
async def get_review_status(id: str): ...

# domains/github_issue/web/routes.py
from fastapi import APIRouter
router = APIRouter()

@router.post("/analyze")
async def analyze_issue(repo: str, issue_number: int): ...

@router.get("/analyze/{id}/status")
async def get_analysis_status(id: str): ...
```

---

### Phase 5：解决其他 P0 问题

#### 5.1 端到端评测（`domains/github_issue/tests/evaluation/`）

```
domains/github_issue/tests/evaluation/
├── test_queries.json           # 20-30 条评测查询
├── evaluate_classification.py  # 分类准确率评测
├── evaluate_priority.py        # 优先级准确率评测
└── evaluate_end_to_end.py      # 端到端成功率评测
```

#### 5.2 对比实验（`experiments/`）

```
experiments/
├── baseline_langgraph/         # LangGraph 实现的简化版
│   ├── dota_review_graph.py
│   └── github_issue_graph.py
├── results/
│   ├── dota_comparison.md
│   └── github_comparison.md
└── README.md
```

#### 5.3 部署方案

```
Dockerfile
docker-compose.yml
deploy/
├── nginx.conf
├── .env.example
└── README.md
```

---

### Phase 6：向后兼容

在 `dota_helper/__init__.py` 中保留重导出：

```python
"""向后兼容层 — 所有符号从新位置重导出"""
from agent_framework.agent import ReActAgent as DotaHelperReActAgent
from agent_framework.interfaces import *
from agent_framework.memory import *
from agent_framework.engines import *
from agent_framework.parallel import *
from agent_framework.observability import *
from agent_framework.secret_vault import SecretVault, CredentialError, vault
from domains.dota.facade import PostMatchReviewAPI, create_default_api

__version__ = "0.2.0"
```

---

## 四、工作量估算

| 阶段 | 文件数 | 预计工时 | 说明 |
|------|--------|---------|------|
| Phase 1: 提取框架 | ~40 个文件 | 4-6 小时 | 主要是 import 替换和少量重命名 |
| Phase 2: 迁移 Dota | ~60 个文件 | 4-6 小时 | 大量 import 替换，需验证不破坏功能 |
| Phase 3: GitHub 领域 | ~30 个新文件 | 8-12 小时 | 全新开发，含测试 |
| Phase 4: Web 重构 | ~5 个文件 | 2-3 小时 | 工厂模式改造 |
| Phase 5: 评测/对比/部署 | ~10 个文件 | 4-6 小时 | 评测集构建 + LangGraph baseline |
| Phase 6: 向后兼容 | ~2 个文件 | 1 小时 | 重导出 |
| **总计** | **~150 个文件** | **23-34 小时** | |

---

## 五、验证清单

- [ ] `python -c "from agent_framework.agent import ReActAgent"` — 框架导入成功
- [ ] `python -c "from domains.dota.facade import PostMatchReviewAPI"` — Dota 领域导入成功
- [ ] `python -c "from domains.github_issue.facade import GitHubIssueAnalysisAPI"` — GitHub 领域导入成功
- [ ] `python -c "from dota_helper import PostMatchReviewAPI"` — 向后兼容导入成功
- [ ] `pytest domains/dota/tests/unit -v` — Dota 单元测试通过
- [ ] `pytest domains/dota/tests/integration -v -m integration` — Dota 集成测试通过
- [ ] `pytest domains/github_issue/tests/unit -v` — GitHub 单元测试通过
- [ ] `python run_web_app.py --domain dota` — Dota Web 服务正常
- [ ] `python run_web_app.py --domain github_issue` — GitHub Web 服务正常
- [ ] `python run_server.py --domain dota` — Dota MCP Server 正常
- [ ] `python run_server.py --domain github_issue` — GitHub MCP Server 正常
