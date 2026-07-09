# Skill 抽取详细设计文档

> **版本**: v1.0  
> **日期**: 2026-07-09  
> **状态**: 待审核  
> **优先级**: P2  
> **所属阶段**: Skill/SubAgent 架构升级 — 第一阶段（Skill 抽取）

---

## 一、概述

本设计文档基于 [ARCHITECTURE_ANALYSIS.md 第十七章](../ARCHITECTURE_ANALYSIS.md#十七skillsubagent-可替代功能分析) 的分析结论，将 DotaHelperAgent 中 **轻量、单次 LLM 调用** 的产品功能抽取为独立可复用的 **Skill** 单元。

**抽取的 5 个 Skill**：

| Skill 名称 | 对应现有功能/代码 | 适用原因 |
|-----------|------------------|---------|
| `lineup_analyzer` | `analyzers/hero_analyzer.py#analyze_team_composition` | 单次 LLM 推理，输入输出边界清晰 |
| `dialogue_understander` | `core/context_augmenter.py` + `core/conversation_manager.py` | 单次 LLM 调用完成语义理解 |
| `meta_analyzer` | `tools/hero_tools.py#GetMetaHeroesTool` | 数据查询 + 单次 LLM 总结 |
| `knowledge_query` | `tools/knowledge_tools.py#KnowledgeQueryTool` | 向量检索 + 单次 LLM 总结 |
| `web_search` | `tools/search_tools.py#DuckDuckGoSearchTool` | 搜索引擎调用 + 单次 LLM 摘要 |

**核心设计原则**：

1. **接口统一**：所有 Skill 继承 `BaseSkill`，实现 `execute` 和 `_fallback` 方法。
2. **注册可发现**：通过 `SkillRegistry` 单例注册，主 Agent 按名称调用。
3. **降级兜底**：每个 Skill 必须实现规则驱动的 `_fallback`，LLM 不可用时自动降级。
4. **Prompt 外置**：Skill 的 Prompt 模板存放在独立 YAML 文件中，复用 PromptManager 进行版本管理。
5. **Trace 集成**：Skill 执行接入现有 `trace_context.py` 和 Langfuse 追踪体系。
6. **渐进迁移**：新 Skill 与旧代码并行运行，通过配置开关控制启用，稳定后再移除旧实现。

---

## 二、问题陈述

### 2.1 当前痛点

当前这些功能以 **硬编码 LLM 调用** 或 **Tool 调用** 的方式嵌入在 Agent 流程中：

| 功能 | 当前实现位置 | 问题 |
|------|------------|------|
| 阵容分析 | `analyzers/hero_analyzer.py` 中由数据驱动，生成自然语言结论依赖 `agent_controller.py#_generate_hero_recommendation` | 分析与生成耦合，复用困难 |
| 多轮对话理解 | `core/context_augmenter.py` 规则驱动 + 可选 LLM | 规则覆盖有限，LLM 增强未独立封装 |
| 版本强势查询 | `tools/hero_tools.py#GetMetaHeroesTool` 返回原始数据 | 缺乏 LLM 总结，用户可读性差 |
| 知识查询 | `tools/knowledge_tools.py#KnowledgeQueryTool` 返回检索结果 | 未封装成可直接回答的 Skill |
| 智能搜索 | `tools/search_tools.py#DuckDuckGoSearchTool` 返回搜索结果 | 未做 LLM 摘要，需 Agent 二次处理 |

**核心问题**：

- ❌ **可测试性差**：LLM 调用与业务逻辑耦合，测试需要 mock 整个 Agent。
- ❌ **可复用性低**：同样能力无法在不同入口（Web API、SSE、桌面通知）复用。
- ❌ **主 Agent 复杂**：编排逻辑与具体实现混杂，新增能力需要修改 AgentController。
- ❌ **降级不一致**：各模块自行实现降级，缺乏统一框架。
- ❌ **Prompt 管理分散**：部分 Prompt 硬编码在代码中，无法版本化。

### 2.2 目标

1. 将 5 个轻量功能封装为独立 Skill，具备清晰的输入输出接口。
2. 建立统一的 Skill 基类、注册表、降级框架和配置体系。
3. 在 `AgentController` 中通过 `SkillRegistry` 调用 Skill，简化主 Agent 逻辑。
4. 保留现有规则驱动实现作为降级方案，确保 LLM 不可用时不影响核心功能。
5. 所有 Skill 接入 Trace 和 Langfuse 监控，满足项目可观测性要求。

---

## 三、技术决策

| 决策项 | 选择 | 理由 |
|--------|------|------|
| Skill 接口 | 抽象基类 `BaseSkill` + `SkillResult` | 符合项目工程规范（接口+策略模式），强制约束输入输出 |
| 注册发现 | 单例 `SkillRegistry` | 全局共享，避免重复注册，支持运行时动态查询 |
| 执行入口 | `BaseSkill.run()` 统一封装超时 + 降级 | 业务方无需关心主逻辑/降级切换细节 |
| Prompt 管理 | 复用 `utils/prompt_manager.py` | 避免重复建设，支持版本化、缓存、降级 |
| 追踪监控 | 复用 `utils/trace_context.py` + Langfuse | 与现有 Trace 体系保持一致 |
| 异步模型 | `async`/`await` | 与 `parallel_executor.py` 和 Web 层异步模型一致 |
| 降级策略 | 规则驱动 + 默认值 + 缓存链式降级 | 满足项目对可用性的要求 |
| 配置管理 | `config/skills_config.yaml` | 统一配置，支持按 Skill 单独开关和参数调整 |

---

## 四、系统架构

### 4.1 架构图

```
┌─────────────────────────────────────────────────────────────────┐
│                        调用入口层                                │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐  │
│  │ AgentController│ │ Web API      │  │ SSE / 主动推荐        │  │
│  │ (ReAct 循环)   │ │ /api/skills/*│  │ (event_trigger)      │  │
│  └──────┬───────┘  └──────┬───────┘  └──────────┬───────────┘  │
│         │                 │                     │              │
│         └─────────────────┼─────────────────────┘              │
└───────────────────────────┼─────────────────────────────────────┘
                            │ SkillRegistry.invoke(name, input, context)
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│                      Skill 调度层                                │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │                   SkillRegistry（单例）                    │   │
│  │  - register / unregister                                  │   │
│  │  - get / list_all                                          │   │
│  │  - invoke(name, input, context) → SkillResult             │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │                   BaseSkill（抽象基类）                    │   │
│  │  - execute(input, context) → SkillResult                  │   │
│  │  - _fallback(input, context, error) → SkillResult         │   │
│  │  - run(input, context) → 超时控制 + 自动降级              │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │                   FallbackHandler                          │   │
│  │  - 链式降级执行                                             │   │
│  │  - 规则/缓存/默认值策略                                     │   │
│  └──────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│                      具体 Skill 层                               │
│  ┌────────────────┐ ┌────────────────┐ ┌────────────────────┐   │
│  │ lineup_analyzer│ │dialogue_understander│ │ meta_analyzer │   │
│  │ 阵容分析        │ │ 多轮对话理解    │ │ 版本强势查询      │   │
│  └────────────────┘ └────────────────┘ └────────────────────┘   │
│  ┌────────────────┐ ┌────────────────┐                          │
│  │ knowledge_query│ │   web_search   │                          │
│  │ 知识查询        │ │ 智能搜索        │                          │
│  └────────────────┘ └────────────────┘                          │
└─────────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│                      基础设施层                                  │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐   │
│  │ LLM Client   │  │ PromptManager│  │ TraceContext/Langfuse│   │
│  └──────────────┘  └──────────────┘  └──────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

### 4.2 数据流

```
业务方调用 SkillRegistry.invoke("lineup_analyzer", input_data, context)
    │
    ▼
SkillRegistry 查找并校验 Skill 状态
    │
    ▼
BaseSkill.run(input_data, context)
    │
    ├── 启动超时计时器
    │
    ├── 调用 execute(input_data, context)
    │   │
    │   ├── 加载 Prompt（通过 PromptManager）
    │   ├── 准备输入（如向量检索、搜索、数据查询）
    │   ├── 调用 LLM Client
    │   └── 解析并封装 SkillResult
    │
    ├── 成功 → 返回 SkillResult
    │
    └── 失败/超时 → 调用 _fallback(input_data, context, error)
        │
        ├── 规则驱动降级
        ├── 缓存返回
        ├── 默认值返回
        └── 封装 fallback 结果（fallback_used=True）
```

---

## 五、目录结构

```
DotaHelperAgent/
├── skills/                                # 新增：Skill 抽象层与具体实现
│   ├── __init__.py                        # 导出公共接口
│   ├── base.py                            # BaseSkill, SkillResult, SkillContext
│   ├── registry.py                        # SkillRegistry 单例
│   ├── exceptions.py                      # Skill 异常体系
│   ├── fallback.py                        # FallbackHandler + FallbackStrategy
│   ├── lineup_analyzer/
│   │   ├── __init__.py
│   │   └── skill.py                       # LineupAnalyzerSkill
│   ├── dialogue_understander/
│   │   ├── __init__.py
│   │   └── skill.py                       # DialogueUnderstanderSkill
│   ├── meta_analyzer/
│   │   ├── __init__.py
│   │   └── skill.py                       # MetaAnalyzerSkill
│   ├── knowledge_query/
│   │   ├── __init__.py
│   │   └── skill.py                       # KnowledgeQuerySkill
│   └── web_search/
│       ├── __init__.py
│       └── skill.py                       # WebSearchSkill
├── config/
│   ├── prompts/
│   │   └── skills.yaml                    # Skill Prompt 模板（复用 PromptManager）
│   └── skills_config.yaml                 # Skill 全局配置
├── tests/skills/                          # 新增：Skill 测试
│   ├── __init__.py
│   ├── conftest.py                        # 共享 fixtures
│   ├── test_base.py
│   ├── test_registry.py
│   ├── test_lineup_analyzer.py
│   ├── test_dialogue_understander.py
│   ├── test_meta_analyzer.py
│   ├── test_knowledge_query.py
│   └── test_web_search.py
├── core/agent_controller.py               # 修改：集成 SkillRegistry
└── web/app.py                             # 修改：添加 Skill API 端点
```

---

## 六、核心模块详细设计

### 6.1 Skill 抽象基类

**文件**: `skills/base.py`

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, Optional
import time
import asyncio
import logging

from .exceptions import SkillExecutionError

logger = logging.getLogger(__name__)


@dataclass
class SkillContext:
    """Skill 执行上下文"""
    session_id: Optional[str] = None
    user_id: Optional[str] = None
    trace_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SkillResult:
    """Skill 执行结果"""
    success: bool
    data: Any
    error: Optional[str] = None
    confidence: float = 1.0
    execution_time: float = 0.0
    fallback_used: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            'success': self.success,
            'data': self.data,
            'error': self.error,
            'confidence': self.confidence,
            'execution_time': self.execution_time,
            'fallback_used': self.fallback_used,
            'metadata': self.metadata,
        }


class BaseSkill(ABC):
    """Skill 抽象基类"""

    def __init__(
        self,
        name: str,
        version: str = "1.0.0",
        description: str = "",
        timeout: float = 30.0,
    ):
        self.name = name
        self.version = version
        self.description = description
        self.timeout = timeout
        self._enabled = True

    @abstractmethod
    async def execute(
        self,
        input_data: Any,
        context: Optional[SkillContext] = None,
    ) -> SkillResult:
        """执行 Skill 主逻辑"""
        pass

    @abstractmethod
    async def _fallback(
        self,
        input_data: Any,
        context: Optional[SkillContext] = None,
        error: Optional[Exception] = None,
    ) -> SkillResult:
        """降级方案"""
        pass

    async def run(
        self,
        input_data: Any,
        context: Optional[SkillContext] = None,
    ) -> SkillResult:
        """执行入口（带降级和超时）"""
        context = context or SkillContext()
        start_time = time.time()

        try:
            result = await asyncio.wait_for(
                self.execute(input_data, context),
                timeout=self.timeout,
            )
            result.execution_time = time.time() - start_time
            return result
        except Exception as e:
            logger.warning(
                f"Skill '{self.name}' execution failed: {e}, "
                f"falling back to rule-based approach"
            )
            try:
                fallback_result = await self._fallback(input_data, context, e)
                fallback_result.execution_time = time.time() - start_time
                fallback_result.fallback_used = True
                return fallback_result
            except Exception as fallback_error:
                raise SkillExecutionError(
                    f"Both main and fallback failed for skill '{self.name}': {fallback_error}",
                    skill_name=self.name,
                ) from fallback_error

    def enable(self) -> None:
        self._enabled = True

    def disable(self) -> None:
        self._enabled = False

    @property
    def enabled(self) -> bool:
        return self._enabled
```

**设计要点**：

- `SkillResult` 必须包含 `confidence` 字段，与项目现有规范一致（`knowledge_config.yaml` 和 `fusion_engine.py` 中已有 confidence 字段）。
- `run()` 负责超时控制和降级切换，业务方只调用 `run()` 或 `SkillRegistry.invoke()`。
- 降级结果需要标记 `fallback_used=True`，便于上游评估质量。

### 6.2 Skill 注册表

**文件**: `skills/registry.py`

```python
import logging
from typing import Dict, List, Optional

from .base import BaseSkill, SkillResult, SkillContext
from .exceptions import SkillExecutionError

logger = logging.getLogger(__name__)


class SkillRegistry:
    """Skill 注册表（单例）"""

    _instance: Optional['SkillRegistry'] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._skills: Dict[str, BaseSkill] = {}
        self._initialized = True

    def register(self, skill: BaseSkill) -> None:
        if skill.name in self._skills:
            raise ValueError(f"Skill '{skill.name}' already registered")
        self._skills[skill.name] = skill
        logger.info(f"Registered skill: {skill.name} v{skill.version}")

    def unregister(self, name: str) -> None:
        if name in self._skills:
            del self._skills[name]
            logger.info(f"Unregistered skill: {name}")

    def get(self, name: str) -> Optional[BaseSkill]:
        return self._skills.get(name)

    def list_all(self) -> List[str]:
        return list(self._skills.keys())

    async def invoke(
        self,
        name: str,
        input_data: Any,
        context: Optional[SkillContext] = None,
    ) -> SkillResult:
        skill = self.get(name)
        if skill is None:
            raise SkillExecutionError(f"Skill '{name}' not found", skill_name=name)
        if not skill.enabled:
            raise SkillExecutionError(f"Skill '{name}' is disabled", skill_name=name)
        return await skill.run(input_data, context)


def get_registry() -> SkillRegistry:
    return SkillRegistry()
```

**设计要点**：

- 单例模式，与 `LangfuseClient.get_instance()` 和 `ToolRegistry` 的设计保持一致。
- 支持运行时动态注册/注销，便于测试和热更新。
- `invoke()` 是业务方唯一需要的调用入口。

### 6.3 降级框架

**文件**: `skills/fallback.py`

```python
import logging
from enum import Enum
from typing import Any, Callable, Awaitable, Optional, List, Tuple

from .base import SkillContext, SkillResult

logger = logging.getLogger(__name__)


class FallbackStrategy(Enum):
    RULE_BASED = "rule_based"
    CACHE = "cache"
    DEFAULT = "default"
    CHAIN = "chain"


class FallbackHandler:
    """统一降级处理器"""

    @staticmethod
    async def execute_with_fallback(
        primary: Callable[[Any, Optional[SkillContext]], Awaitable[SkillResult]],
        fallback_chain: List[Tuple[str, Callable[[Any, Optional[SkillContext]], Awaitable[SkillResult]]]],
        input_data: Any,
        context: Optional[SkillContext] = None,
    ) -> SkillResult:
        try:
            return await primary(input_data, context)
        except Exception as e:
            logger.warning(f"Primary execution failed: {e}, trying fallbacks")
            for name, fallback_fn in fallback_chain:
                try:
                    logger.info(f"Trying fallback: {name}")
                    result = await fallback_fn(input_data, context)
                    result.fallback_used = True
                    result.metadata['fallback_name'] = name
                    return result
                except Exception as fe:
                    logger.warning(f"Fallback '{name}' failed: {fe}")
                    continue
            raise RuntimeError("All fallbacks failed")
```

**设计要点**：

- `fallback_chain` 支持链式降级，按顺序尝试规则、缓存、默认值。
- 返回结果自动标记 `fallback_used` 和 `fallback_name`。

### 6.4 异常体系

**文件**: `skills/exceptions.py`

```python
from typing import Optional


class SkillException(Exception):
    """Skill 基础异常"""

    def __init__(self, message: str, skill_name: Optional[str] = None):
        self.skill_name = skill_name
        super().__init__(message)


class SkillExecutionError(SkillException):
    """Skill 执行错误"""
    pass


class SkillTimeoutError(SkillException):
    """Skill 执行超时"""
    pass


class SkillFallbackError(SkillException):
    """Skill 降级策略也失败"""
    pass
```

---

## 七、各 Skill 详细设计

### 7.1 阵容分析 Skill

**现有对应代码**: `analyzers/hero_analyzer.py#analyze_team_composition`

当前 `analyze_team_composition` 主要基于 matchup 数据计算双方优势分数，结论是结构化的（`our_advantages`, `enemy_advantages`, `overall_advantage`, `conclusion`）。Skill 在此基础上增加 LLM 驱动的自然语言分析。

**文件**: `skills/lineup_analyzer/skill.py`

```python
from typing import Any, Dict, List, Optional
from pathlib import Path

from ..base import BaseSkill, SkillContext, SkillResult


class LineupAnalyzerSkill(BaseSkill):
    """阵容分析 Skill

    输入: {"radiant_heroes": [...], "dire_heroes": [...]}
    输出: {"analysis": "自然语言分析", "structured": {...}, "confidence": 0.85}
    """

    def __init__(
        self,
        llm_client,
        hero_analyzer=None,
        prompt_manager=None,
        **kwargs,
    ):
        super().__init__(
            name="lineup_analyzer",
            version="1.0.0",
            description="分析敌我双方阵容的优劣势",
            **kwargs,
        )
        self.llm_client = llm_client
        self.hero_analyzer = hero_analyzer
        self.prompt_manager = prompt_manager

    async def execute(
        self,
        input_data: Dict[str, List[str]],
        context: Optional[SkillContext] = None,
    ) -> SkillResult:
        radiant = input_data.get("radiant_heroes", [])
        dire = input_data.get("dire_heroes", [])

        # 1. 获取结构化数据（复用现有 analyzer）
        structured = {}
        if self.hero_analyzer:
            try:
                structured = self.hero_analyzer.analyze_team_composition(radiant, dire)
            except Exception as e:
                logger.warning(f"HeroAnalyzer failed: {e}, using LLM only")

        # 2. 构造 Prompt
        prompt = self._build_prompt(radiant, dire, structured)

        # 3. LLM 生成自然语言分析
        response = await self.llm_client.generate(prompt)

        return SkillResult(
            success=True,
            data={
                "analysis": response,
                "structured": structured,
                "radiant_heroes": radiant,
                "dire_heroes": dire,
            },
            confidence=0.85 if structured else 0.7,
            metadata={"has_structured_data": bool(structured)},
        )

    async def _fallback(
        self,
        input_data: Dict[str, List[str]],
        context: Optional[SkillContext] = None,
        error: Optional[Exception] = None,
    ) -> SkillResult:
        radiant = input_data.get("radiant_heroes", [])
        dire = input_data.get("dire_heroes", [])

        if self.hero_analyzer:
            try:
                structured = self.hero_analyzer.analyze_team_composition(radiant, dire)
                return SkillResult(
                    success=True,
                    data={
                        "analysis": structured.get("conclusion", "阵容分析暂不可用"),
                        "structured": structured,
                        "radiant_heroes": radiant,
                        "dire_heroes": dire,
                    },
                    confidence=0.5,
                )
            except Exception:
                pass

        return SkillResult(
            success=True,
            data={
                "analysis": f"阵容分析暂不可用。己方英雄数：{len(radiant)}，敌方英雄数：{len(dire)}",
                "structured": {},
                "radiant_heroes": radiant,
                "dire_heroes": dire,
            },
            confidence=0.3,
        )

    def _build_prompt(
        self,
        radiant: List[str],
        dire: List[str],
        structured: Dict[str, Any],
    ) -> str:
        if self.prompt_manager:
            return self.prompt_manager.get_prompt(
                "lineup_analysis",
                variables={
                    "radiant_heroes": "、".join(radiant),
                    "dire_heroes": "、".join(dire),
                    "structured_analysis": str(structured),
                },
            )
        # 硬编码降级 Prompt
        return f"""你是一名专业的 Dota 2 阵容分析专家。

## 己方阵容
{"、".join(radiant)}

## 敌方阵容
{"、".join(dire)}

## 数据参考
{structured}

请分析双方阵容优劣势，控制在 300 字以内。"""
```

**Prompt 配置**: `config/prompts/skills.yaml`

```yaml
prompts:
  lineup_analysis:
    description: "阵容分析 Prompt"
    version: 1
    content: |
      你是一名专业的 Dota 2 阵容分析专家。

      ## 己方阵容
      {{radiant_heroes}}

      ## 敌方阵容
      {{dire_heroes}}

      ## 数据参考
      {{structured_analysis}}

      请分析双方阵容优劣势，包括：
      1. 己方阵容优势（控制、爆发、推进、分推等）
      2. 己方阵容劣势（被克制、缺少某些能力）
      3. 敌方阵容优势
      4. 敌方阵容劣势
      5. 关键对决点
      6. 整体胜率评估

      请用简洁清晰的语言输出，控制在 300 字以内。
    variables:
      - radiant_heroes
      - dire_heroes
      - structured_analysis
    metadata:
      author: "system"
      tags: ["skill", "lineup_analysis"]
```

**设计要点**：

- 复用现有 `hero_analyzer.analyze_team_composition` 提供结构化数据，LLM 负责自然语言生成。
- 降级时优先返回结构化数据，完全失败时返回简单统计。

### 7.2 多轮对话理解 Skill

**现有对应代码**: `core/context_augmenter.py`

当前 `ContextAugmenter` 是规则驱动的，支持指代消解、意图推断、实体提取。Skill 将其升级为 LLM 驱动主路径，规则驱动作为降级。

**文件**: `skills/dialogue_understander/skill.py`

```python
import json
from typing import Any, Dict, List, Optional

from ..base import BaseSkill, SkillContext, SkillResult


class DialogueUnderstanderSkill(BaseSkill):
    """多轮对话理解 Skill

    输入: {"history": [...], "current_input": "..."}
    输出: {"enhanced_query": "...", "intent": "...", "entities": {...}, "context_used": bool}
    """

    def __init__(
        self,
        llm_client,
        context_augmenter=None,
        prompt_manager=None,
        **kwargs,
    ):
        super().__init__(
            name="dialogue_understander",
            version="1.0.0",
            description="多轮对话上下文理解（指代消解、意图推断、实体提取）",
            **kwargs,
        )
        self.llm_client = llm_client
        self.context_augmenter = context_augmenter
        self.prompt_manager = prompt_manager

    async def execute(
        self,
        input_data: Dict[str, Any],
        context: Optional[SkillContext] = None,
    ) -> SkillResult:
        history = input_data.get("history", [])
        current_input = input_data.get("current_input", "")

        prompt = self._build_prompt(history, current_input)
        response = await self.llm_client.generate(prompt)

        try:
            parsed = json.loads(response)
        except json.JSONDecodeError:
            parsed = self._parse_fallback(response, current_input)

        return SkillResult(
            success=True,
            data=parsed,
            confidence=0.8,
        )

    async def _fallback(
        self,
        input_data: Dict[str, Any],
        context: Optional[SkillContext] = None,
        error: Optional[Exception] = None,
    ) -> SkillResult:
        history = input_data.get("history", [])
        current_input = input_data.get("current_input", "")

        if self.context_augmenter:
            # 使用规则驱动的 ContextAugmenter 降级
            from core.conversation_manager import ConversationSession
            session = ConversationSession(session_id="fallback")
            for msg in history:
                from core.conversation_manager import Message, MessageRole
                session.add_message(Message(
                    role=msg.get("role", MessageRole.USER.value),
                    content=msg.get("content", ""),
                ))
            result = self.context_augmenter.augment_query(current_input, session)
            return SkillResult(
                success=True,
                data={
                    "enhanced_query": result.get("augmented_query", current_input),
                    "intent": result.get("inferred_intent", "general"),
                    "entities": result.get("entities", {}),
                    "context_used": bool(result.get("context", {})),
                },
                confidence=0.5,
            )

        return SkillResult(
            success=True,
            data={
                "enhanced_query": current_input,
                "intent": "general",
                "entities": {"heroes": [], "items": [], "skills": []},
                "context_used": False,
            },
            confidence=0.3,
        )

    def _build_prompt(
        self,
        history: List[Dict[str, str]],
        current_input: str,
    ) -> str:
        history_text = self._format_history(history)
        if self.prompt_manager:
            return self.prompt_manager.get_prompt(
                "dialogue_understand",
                variables={
                    "history": history_text,
                    "current_input": current_input,
                },
            )
        return f"""你是一名 Dota 2 助手，需要理解用户的对话上下文。

## 对话历史
{history_text}

## 当前用户输入
{current_input}

请以 JSON 格式输出：
{{
  "enhanced_query": "消解后的完整查询",
  "intent": "intent_type",
  "entities": {{
    "heroes": ["英雄列表"],
    "items": ["物品列表"],
    "skills": ["技能列表"]
  }},
  "context_used": true/false
}}"""

    def _format_history(self, history: List[Dict[str, str]]) -> str:
        lines = []
        for msg in history[-10:]:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            lines.append(f"{role}: {content}")
        return "\n".join(lines) if lines else "（无历史对话）"

    def _parse_fallback(self, response: str, current_input: str) -> Dict[str, Any]:
        """LLM 返回非 JSON 时的兜底解析"""
        return {
            "enhanced_query": current_input,
            "intent": "unknown",
            "entities": {"heroes": [], "items": [], "skills": []},
            "context_used": False,
            "raw_response": response,
        }
```

**设计要点**：

- LLM 输出要求为 JSON，便于下游直接使用。
- 降级时复用现有 `ContextAugmenter`，保持向后兼容。
- `intent` 值与现有 `ContextAugmenter.INTENT_KEYWORDS` 保持一致（`recommend_heroes`, `recommend_items`, `recommend_skills`, `analyze_matchups`, `general`）。

### 7.3 版本强势查询 Skill

**现有对应代码**: `tools/hero_tools.py#GetMetaHeroesTool`

当前 `GetMetaHeroesTool` 返回排序后的英雄列表，但缺乏自然语言总结。Skill 封装为可直接回答的单元。

**文件**: `skills/meta_analyzer/skill.py`

```python
from typing import Any, Dict, Optional, Callable, Awaitable

from ..base import BaseSkill, SkillContext, SkillResult


class MetaAnalyzerSkill(BaseSkill):
    """版本强势查询 Skill

    输入: 用户查询字符串（如"当前版本哪些英雄强势？"）
    输出: {"answer": "自然语言回答", "meta_heroes": [...]}
    """

    def __init__(
        self,
        llm_client,
        data_fetcher: Callable[[], Awaitable[Dict[str, Any]]],
        prompt_manager=None,
        cache_ttl: int = 3600,
        **kwargs,
    ):
        super().__init__(
            name="meta_analyzer",
            version="1.0.0",
            description="查询当前版本热门/强势英雄",
            **kwargs,
        )
        self.llm_client = llm_client
        self.data_fetcher = data_fetcher
        self.prompt_manager = prompt_manager
        self._cache: Optional[Dict[str, Any]] = None
        self._cache_time: float = 0.0
        self._cache_ttl = cache_ttl

    async def execute(
        self,
        input_data: str,
        context: Optional[SkillContext] = None,
    ) -> SkillResult:
        meta_data = await self._fetch_meta_data()

        prompt = self._build_prompt(input_data, meta_data)
        response = await self.llm_client.generate(prompt)

        return SkillResult(
            success=True,
            data={
                "answer": response,
                "meta_heroes": meta_data.get("meta_heroes", []),
            },
            confidence=0.8 if meta_data.get("meta_heroes") else 0.5,
            metadata={"hero_count": len(meta_data.get("meta_heroes", []))},
        )

    async def _fallback(
        self,
        input_data: str,
        context: Optional[SkillContext] = None,
        error: Optional[Exception] = None,
    ) -> SkillResult:
        meta_data = await self._fetch_meta_data()
        heroes = meta_data.get("meta_heroes", [])

        if heroes:
            names = [h.get("hero_name", "未知") for h in heroes[:10]]
            answer = f"当前版本强势英雄（按胜率+选取率排序）：{', '.join(names)}"
        else:
            answer = "版本数据暂不可用，请稍后再试。"

        return SkillResult(
            success=True,
            data={
                "answer": answer,
                "meta_heroes": heroes,
            },
            confidence=0.4,
        )

    async def _fetch_meta_data(self) -> Dict[str, Any]:
        import time
        now = time.time()
        if self._cache and (now - self._cache_time) < self._cache_ttl:
            return self._cache

        data = await self.data_fetcher()
        self._cache = data
        self._cache_time = now
        return data

    def _build_prompt(self, query: str, meta_data: Dict[str, Any]) -> str:
        heroes_text = json.dumps(meta_data.get("meta_heroes", [])[:20], ensure_ascii=False, indent=2)
        if self.prompt_manager:
            return self.prompt_manager.get_prompt(
                "meta_query",
                variables={
                    "meta_data": heroes_text,
                    "user_query": query,
                },
            )
        return f"""你是一名 Dota 2 版本分析师。

## 当前版本数据
{heroes_text}

## 用户问题
{query}

请根据版本数据回答用户问题，控制在 200 字以内。"""
```

**设计要点**：

- `data_fetcher` 由调用方注入，解耦数据来源。实际可绑定 `GetMetaHeroesTool._get_meta` 或自定义函数。
- 增加缓存机制，避免频繁调用 API。

### 7.4 知识查询 Skill

**现有对应代码**: `tools/knowledge_tools.py#KnowledgeQueryTool`

当前 `KnowledgeQueryTool` 返回结构化检索结果，需要 Agent 二次处理。Skill 直接生成自然语言答案。

**文件**: `skills/knowledge_query/skill.py`

```python
from typing import Any, Dict, List, Optional

from ..base import BaseSkill, SkillContext, SkillResult


class KnowledgeQuerySkill(BaseSkill):
    """知识查询 Skill

    输入: 用户查询字符串（如"PA 怎么出装？"）
    输出: {"answer": "自然语言回答", "sources": [...]}
    """

    def __init__(
        self,
        llm_client,
        vector_store,
        fusion_engine=None,
        top_k: int = 5,
        prompt_manager=None,
        **kwargs,
    ):
        super().__init__(
            name="knowledge_query",
            version="1.0.0",
            description="检索攻略文档并生成回答",
            **kwargs,
        )
        self.llm_client = llm_client
        self.vector_store = vector_store
        self.fusion_engine = fusion_engine
        self.top_k = top_k
        self.prompt_manager = prompt_manager

    async def execute(
        self,
        input_data: str,
        context: Optional[SkillContext] = None,
    ) -> SkillResult:
        # 1. 向量检索
        docs = await self.vector_store.search(input_data, n_results=self.top_k)

        # 2. 可选：知识融合
        context_text = ""
        sources = []
        if self.fusion_engine and docs:
            # 简化处理：将检索结果作为非结构化知识传入融合引擎
            fused = self.fusion_engine.merge(
                structured_knowledge=[],
                unstructured_knowledge=docs.get("results", []),
                query=input_data,
            )
            context_text = fused.to_dict().get("answer", "")
            sources = fused.to_dict().get("sources", [])
        else:
            results = docs.get("results", []) if isinstance(docs, dict) else docs
            context_text = "\n\n".join([
                d.get("text", d.get("content", "")) for d in results
            ])
            sources = [d.get("metadata", {}) for d in results]

        # 3. LLM 生成回答
        prompt = self._build_prompt(input_data, context_text)
        response = await self.llm_client.generate(prompt)

        return SkillResult(
            success=True,
            data={
                "answer": response,
                "sources": sources,
            },
            confidence=0.85 if sources else 0.4,
            metadata={"docs_count": len(sources)},
        )

    async def _fallback(
        self,
        input_data: str,
        context: Optional[SkillContext] = None,
        error: Optional[Exception] = None,
    ) -> SkillResult:
        return SkillResult(
            success=True,
            data={
                "answer": "知识库查询暂不可用，请稍后再试。",
                "sources": [],
            },
            confidence=0.2,
        )

    def _build_prompt(self, query: str, context_text: str) -> str:
        if self.prompt_manager:
            return self.prompt_manager.get_prompt(
                "knowledge_query_skill",
                variables={
                    "context": context_text,
                    "query": query,
                },
            )
        return f"""基于以下攻略资料回答用户问题：

## 攻略资料
{context_text}

## 用户问题
{query}

请给出准确、简洁的回答。"""
```

**设计要点**：

- 复用现有 `vector_store.search()` 和 `fusion_engine.merge()`。
- `vector_store.search` 的返回格式需兼容当前实现（`{"results": [...]}` 或列表）。

### 7.5 智能搜索 Skill

**现有对应代码**: `tools/search_tools.py#DuckDuckGoSearchTool`

当前 `DuckDuckGoSearchTool` 返回搜索结果列表。Skill 封装为 LLM 摘要后的直接答案。

**文件**: `skills/web_search/skill.py`

```python
from typing import Any, Dict, List, Optional

from ..base import BaseSkill, SkillContext, SkillResult


class WebSearchSkill(BaseSkill):
    """智能搜索 Skill

    输入: 搜索关键词
    输出: {"answer": "自然语言摘要", "sources": [...]}
    """

    def __init__(
        self,
        llm_client,
        search_engine,
        max_results: int = 5,
        prompt_manager=None,
        **kwargs,
    ):
        super().__init__(
            name="web_search",
            version="1.0.0",
            description="搜索最新 Dota 2 信息并生成摘要",
            **kwargs,
        )
        self.llm_client = llm_client
        self.search_engine = search_engine
        self.max_results = max_results
        self.prompt_manager = prompt_manager

    async def execute(
        self,
        input_data: str,
        context: Optional[SkillContext] = None,
    ) -> SkillResult:
        query = f"Dota 2 {input_data}"

        # 1. 搜索
        search_result = await self.search_engine.search(query, max_results=self.max_results)

        # 兼容现有 Tool 返回格式
        results = search_result
        if isinstance(search_result, dict):
            results = search_result.get("results", [])

        # 2. LLM 摘要
        results_text = "\n\n".join([
            f"标题：{r.get('title', '')}\n摘要：{r.get('snippet', r.get('body', ''))}\n链接：{r.get('url', r.get('href', ''))}"
            for r in results
        ])
        prompt = self._build_prompt(input_data, results_text)
        response = await self.llm_client.generate(prompt)

        return SkillResult(
            success=True,
            data={
                "answer": response,
                "sources": [
                    {"title": r.get("title", ""), "url": r.get("url", r.get("href", ""))}
                    for r in results
                ],
            },
            confidence=0.75 if results else 0.3,
            metadata={"result_count": len(results)},
        )

    async def _fallback(
        self,
        input_data: str,
        context: Optional[SkillContext] = None,
        error: Optional[Exception] = None,
    ) -> SkillResult:
        return SkillResult(
            success=True,
            data={
                "answer": "搜索功能暂不可用，请稍后再试。",
                "sources": [],
            },
            confidence=0.2,
        )

    def _build_prompt(self, query: str, results_text: str) -> str:
        if self.prompt_manager:
            return self.prompt_manager.get_prompt(
                "web_search_skill",
                variables={
                    "results": results_text,
                    "query": query,
                },
            )
        return f"""基于以下搜索结果回答用户问题：

## 搜索结果
{results_text}

## 用户问题
{query}

请给出简洁准确的回答，并标注信息来源。"""
```

**设计要点**：

- `search_engine` 由调用方注入，可绑定 `DuckDuckGoSearchTool` 实例或简单封装函数。
- 兼容现有 `DuckDuckGoSearchTool.execute()` 的返回格式（`ToolResult` 或字典）。

---

## 八、与现有代码集成方案

### 8.1 AgentController 集成

**修改文件**: `core/agent_controller.py`

在 `AgentController.__init__` 末尾添加 Skill 初始化：

```python
from skills import get_registry, SkillContext
from skills.lineup_analyzer import LineupAnalyzerSkill
from skills.dialogue_understander import DialogueUnderstanderSkill
from skills.meta_analyzer import MetaAnalyzerSkill
from skills.knowledge_query import KnowledgeQuerySkill
from skills.web_search import WebSearchSkill


class AgentController:
    def __init__(self, ...):
        # ... 现有初始化代码 ...
        self._init_skill_system()

    def _init_skill_system(self) -> None:
        """初始化并注册所有 Skill"""
        registry = get_registry()

        skills_config = self._load_skills_config()
        if not skills_config.get("enabled", True):
            logger.info("Skill 系统未启用")
            return

        # 阵容分析 Skill
        from analyzers.hero_analyzer import HeroAnalyzer
        from utils.api_client import OpenDotaClient
        hero_analyzer = HeroAnalyzer(client=OpenDotaClient())

        registry.register(LineupAnalyzerSkill(
            llm_client=self.llm_client,
            hero_analyzer=hero_analyzer,
            prompt_manager=self.prompt_manager,
            timeout=skills_config.get("lineup_analyzer", {}).get("timeout", 15.0),
        ))

        # 多轮对话理解 Skill
        registry.register(DialogueUnderstanderSkill(
            llm_client=self.llm_client,
            context_augmenter=self.context_augmenter,
            prompt_manager=self.prompt_manager,
            timeout=skills_config.get("dialogue_understander", {}).get("timeout", 10.0),
        ))

        # 版本强势查询 Skill
        async def fetch_meta():
            from tools.hero_tools import GetMetaHeroesTool
            tool = GetMetaHeroesTool(client=OpenDotaClient())
            return tool._get_meta(limit=20)

        registry.register(MetaAnalyzerSkill(
            llm_client=self.llm_client,
            data_fetcher=fetch_meta,
            prompt_manager=self.prompt_manager,
            timeout=skills_config.get("meta_analyzer", {}).get("timeout", 20.0),
        ))

        # 知识查询 Skill
        if self.knowledge_enabled and self.vector_store:
            registry.register(KnowledgeQuerySkill(
                llm_client=self.llm_client,
                vector_store=self.vector_store,
                fusion_engine=self.fusion_engine,
                prompt_manager=self.prompt_manager,
                top_k=skills_config.get("knowledge_query", {}).get("top_k", 5),
                timeout=skills_config.get("knowledge_query", {}).get("timeout", 15.0),
            ))

        # 智能搜索 Skill
        from tools.search_tools import DuckDuckGoSearchTool
        registry.register(WebSearchSkill(
            llm_client=self.llm_client,
            search_engine=DuckDuckGoSearchTool(),
            prompt_manager=self.prompt_manager,
            max_results=skills_config.get("web_search", {}).get("max_results", 5),
            timeout=skills_config.get("web_search", {}).get("timeout", 20.0),
        ))

        logger.info(f"Skill 系统初始化完成，已注册 {len(registry.list_all())} 个 Skill")

    def _load_skills_config(self) -> Dict[str, Any]:
        """加载 Skill 配置"""
        import yaml
        config_path = Path(__file__).parent.parent / "config" / "skills_config.yaml"
        if config_path.exists():
            with open(config_path, 'r', encoding='utf-8') as f:
                return yaml.safe_load(f).get("skills", {})
        return {"enabled": True}
```

### 8.2 在 ReAct 循环中使用 Skill

在 `AgentController._think()` 或 `AgentController.solve()` 中，可在 LLM 工具选择前增加 Skill 路由：

```python
async def _route_to_skill(self, thought: AgentThought) -> Optional[SkillResult]:
    """判断当前查询是否可直接由 Skill 处理"""
    registry = get_registry()
    query = thought.query

    # 示例：阵容分析类查询直接路由到 lineup_analyzer
    if any(kw in query for kw in ["阵容", "阵容分析", "双方阵容"]):
        # 从上下文中提取双方阵容
        our_heroes = thought.context.get("our_heroes", [])
        enemy_heroes = thought.context.get("enemy_heroes", [])
        if our_heroes or enemy_heroes:
            return await registry.invoke(
                "lineup_analyzer",
                {"radiant_heroes": our_heroes, "dire_heroes": enemy_heroes},
                SkillContext(session_id=thought.context.get("session_id")),
            )

    # 示例：版本强势查询
    if any(kw in query for kw in ["版本强势", "热门英雄", "强势英雄"]):
        return await registry.invoke(
            "meta_analyzer",
            query,
            SkillContext(session_id=thought.context.get("session_id")),
        )

    return None
```

**集成策略**：

- 第一阶段：Skill 与现有 Tool 并行，AgentController 优先尝试 Skill 路由，失败时回退到传统 ReAct 工具调用。
- 第二阶段：将 Skill 也封装为 Tool，让 LLM 工具选择器决定是否调用。
- 第三阶段：完全替换原有 Tool 中的 LLM 驱动部分，保留纯数据查询 Tool。

### 8.3 Web API 暴露

**修改文件**: `web/app.py`

```python
from skills import get_registry, SkillContext


@app.route('/api/skills', methods=['GET'])
def list_skills():
    """列出所有已注册的 Skill"""
    registry = get_registry()
    return jsonify({
        "skills": [
            {"name": name, "enabled": registry.get(name).enabled}
            for name in registry.list_all()
        ],
    })


@app.route('/api/skills/<name>/invoke', methods=['POST'])
def invoke_skill(name):
    """调用指定 Skill"""
    import asyncio

    registry = get_registry()
    data = request.json or {}
    input_data = data.get("input")
    context_data = data.get("context", {})

    context = SkillContext(
        session_id=context_data.get("session_id"),
        user_id=context_data.get("user_id"),
        trace_id=context_data.get("trace_id"),
    )

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        result = loop.run_until_complete(
            registry.invoke(name, input_data, context)
        )
        return jsonify(result.to_dict())
    finally:
        loop.close()
```

---

## 九、配置设计

**文件**: `config/skills_config.yaml`

```yaml
# Skill 全局配置
skills:
  enabled: true
  timeout: 30.0
  fallback_enabled: true

  # 各 Skill 单独配置
  lineup_analyzer:
    enabled: true
    timeout: 15.0

  dialogue_understander:
    enabled: true
    timeout: 10.0

  meta_analyzer:
    enabled: true
    timeout: 20.0
    cache_ttl: 3600

  knowledge_query:
    enabled: true
    timeout: 15.0
    top_k: 5

  web_search:
    enabled: true
    timeout: 20.0
    max_results: 5
```

---

## 十、Trace 与 Langfuse 集成

Skill 执行需要接入现有可观测性体系：

1. **Trace 上下文传递**：`SkillContext.trace_id` 和 `session_id` 从当前 Trace 上下文获取。
2. **Span 嵌套**：每个 Skill 的 `execute` 方法内部使用 `TraceSpan` 包裹 LLM 调用和数据查询。
3. **Langfuse 评分**：Skill 执行完成后，将 `confidence` 和 `fallback_used` 作为 metadata 上报。

示例：

```python
from utils.trace_context import TraceSpan

async def execute(self, input_data, context=None):
    ctx = context or SkillContext()
    with TraceSpan(f"skill_{self.name}", parent=...):
        # LLM 调用
        with TraceSpan(f"skill_{self.name}_llm"):
            response = await self.llm_client.generate(prompt)
    ...
```

---

## 十一、测试方案

### 11.1 单元测试

| 测试文件 | 覆盖内容 |
|---------|---------|
| `tests/skills/test_base.py` | BaseSkill 成功/降级/双失败路径、超时 |
| `tests/skills/test_registry.py` | 单例、注册/注销/重复注册、invoke |
| `tests/skills/test_fallback.py` | FallbackHandler 链式降级 |
| `tests/skills/test_lineup_analyzer.py` | 正常分析、结构化数据缺失、降级 |
| `tests/skills/test_dialogue_understander.py` | JSON 解析、指代消解、规则降级 |
| `tests/skills/test_meta_analyzer.py` | 数据获取、缓存、降级 |
| `tests/skills/test_knowledge_query.py` | 向量检索、融合、空结果降级 |
| `tests/skills/test_web_search.py` | 搜索、摘要、搜索失败降级 |

### 11.2 集成测试

| 测试文件 | 覆盖内容 |
|---------|---------|
| `tests/integration/test_skill_integration.py` | AgentController 初始化 Skill、API 调用 |

### 11.3 Mock 策略

- `llm_client`：mock `generate()` 返回固定字符串或 JSON。
- `vector_store`：mock `search()` 返回固定文档。
- `search_engine`：mock `search()` 返回固定结果。
- `hero_analyzer`：mock `analyze_team_composition()` 返回固定结构化数据。

---

## 十二、实施计划

| 阶段 | 时间 | 任务 | 验收标准 |
|------|------|------|---------|
| **阶段 1** | 第 1 周 | 基础设施：`skills/base.py`, `registry.py`, `exceptions.py`, `fallback.py` + 基础测试 | 单元测试全部通过 |
| **阶段 2** | 第 2 周 | 实现 `lineup_analyzer`, `dialogue_understander` Skill + Prompt + 测试 | 单测通过，可独立调用 |
| **阶段 3** | 第 3 周 | 实现 `meta_analyzer`, `knowledge_query`, `web_search` Skill + 测试 | 单测通过，可独立调用 |
| **阶段 4** | 第 4 周 | AgentController 集成、Web API 暴露、`skills_config.yaml` 配置 | E2E 测试通过 |
| **阶段 5** | 第 5 周 | 接入 Trace/Langfuse、补充集成测试、文档更新 | Trace 可观测、集成测试通过 |
| **阶段 6** | 第 6 周 | 灰度验证、性能调优、逐步移除旧代码中的重复 LLM 调用 | 性能指标达标 |

---

## 十三、验收标准

1. **功能完整性**：5 个 Skill 全部实现并可在 `SkillRegistry` 中注册和调用。
2. **接口一致性**：所有 Skill 继承 `BaseSkill`，返回 `SkillResult`。
3. **降级有效**：LLM 不可用或超时时，每个 Skill 都能返回合理的降级结果。
4. **测试覆盖**：单元测试覆盖率 > 80%，集成测试覆盖 AgentController 和 Web API。
5. **性能指标**：单 Skill P99 调用延迟 < 5 秒（含 LLM 推理）。
6. **可观测性**：Skill 调用接入 Trace 和 Langfuse，包含 confidence 和 fallback_used 字段。
7. **配置化**：所有 Skill 可通过 `config/skills_config.yaml` 单独开关和调参。
8. **向后兼容**：原有 Tool 和 Augmenter 在 Skill 未启用或失败时仍能正常工作。

---

## 十四、风险与缓解

| 风险 | 缓解措施 |
|------|---------|
| LLM 调用延迟高 | 设置 Skill 级超时，失败时自动降级 |
| Skill 与现有 Tool 功能重叠 | 渐进迁移，保留旧实现作为 fallback，稳定后移除 |
| Prompt 版本管理不一致 | 复用 `PromptManager`，所有 Skill Prompt 统一配置 |
| 多个 Skill 串联增加延迟 | AgentController 中仅对明确场景路由到 Skill，避免滥用 |
| 异步与现有同步代码冲突 | Web 层使用 `asyncio.new_event_loop()` 兼容；AgentController 逐步异步化 |
| 测试复杂 | 所有外部依赖通过构造函数注入，便于 mock |

---

## 十五、预期收益

| 维度 | 当前能力 | 升级后能力 | 收益 |
|------|---------|-----------|------|
| **可测试性** | 需要 mock 整个 Agent | Skill 独立测试，接口清晰 | 测试复杂度降低 |
| **可复用性** | 能力嵌入 Agent 内部 | 独立能力单元，可跨入口复用 | 复用性提升 |
| **主 Agent 复杂度** | 硬编码调用逻辑 | 只需编排调度 | AgentController 更清晰 |
| **降级一致性** | 各模块各自实现 | 统一降级框架 | 维护成本降低 |
| **Prompt 管理** | 部分硬编码 | 统一 PromptManager 管理 | 版本化、A/B 测试更便捷 |

---

> **文档版本**: v1.0  
> **创建时间**: 2026-07-09  
> **预计完成**: 2026-08-20（第 6 周）
