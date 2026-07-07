# Skill 抽取 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 DotaHelperAgent 中轻量、单次 LLM 调用的产品功能抽取为独立可复用的 Skill 单元，包括阵容分析、多轮对话理解、版本强势查询、知识查询、智能搜索。

**Architecture:** 定义统一 Skill 接口 → 各功能实现为独立 Skill → 主 Agent 通过 SkillRegistry 注册和调度 → 保留规则驱动降级方案作为兜底

**Tech Stack:** Python, Abstract Base Class, Langfuse (Trace), PyYAML (Config)

---

## 背景与目标

根据 [ARCHITECTURE_ANALYSIS.md 第十七章](../ARCHITECTURE_ANALYSIS.md#十七skill-subagent-可替代功能分析) 的分析，DotaHelperAgent 中有 5 个产品功能适合用 Skill 模式替代实现：

| 产品功能 | 适用原因 |
|---------|---------|
| 阵容分析 | 单次 LLM 推理，输入输出边界清晰 |
| 多轮对话上下文理解 | 单次 LLM 调用完成语义理解 |
| 版本强势查询 | 数据查询 + 单次 LLM 总结 |
| 知识查询 | 向量检索 + 单次 LLM 总结 |
| 智能搜索 | 搜索引擎 + 单次 LLM 摘要 |

**核心收益**：
- 可测试性：Skill 独立测试，接口清晰
- 可复用性：跨场景复用
- 主 Agent 简化：只需编排调度
- 降级统一：统一降级框架

---

## File Structure

| Action | File | Responsibility |
|--------|------|---------------|
| Create | `skills/__init__.py` | Skill 包初始化，导出公共接口 |
| Create | `skills/base.py` | Skill 抽象基类（ABC） |
| Create | `skills/registry.py` | Skill 注册表，单例模式 |
| Create | `skills/exceptions.py` | Skill 异常定义 |
| Create | `skills/fallback.py` | 统一降级框架 |
| Create | `skills/lineup_analyzer/__init__.py` | 阵容分析 Skill |
| Create | `skills/lineup_analyzer/skill.py` | 阵容分析 Skill 实现 |
| Create | `skills/lineup_analyzer/prompts.yaml` | 阵容分析 Prompt 模板 |
| Create | `skills/dialogue_understander/__init__.py` | 多轮对话理解 Skill |
| Create | `skills/dialogue_understander/skill.py` | 多轮对话理解 Skill 实现 |
| Create | `skills/dialogue_understander/prompts.yaml` | 对话理解 Prompt 模板 |
| Create | `skills/meta_analyzer/__init__.py` | 版本强势查询 Skill |
| Create | `skills/meta_analyzer/skill.py` | 版本强势查询 Skill 实现 |
| Create | `skills/meta_analyzer/prompts.yaml` | 版本强势 Prompt 模板 |
| Create | `skills/knowledge_query/__init__.py` | 知识查询 Skill |
| Create | `skills/knowledge_query/skill.py` | 知识查询 Skill 实现 |
| Create | `skills/web_search/__init__.py` | 智能搜索 Skill |
| Create | `skills/web_search/skill.py` | 智能搜索 Skill 实现 |
| Create | `config/skills_config.yaml` | Skill 全局配置 |
| Create | `tests/skills/__init__.py` | 测试包 |
| Create | `tests/skills/test_base.py` | 基类测试 |
| Create | `tests/skills/test_registry.py` | 注册表测试 |
| Create | `tests/skills/test_fallback.py` | 降级框架测试 |
| Create | `tests/skills/test_lineup_analyzer.py` | 阵容分析测试 |
| Create | `tests/skills/test_dialogue_understander.py` | 对话理解测试 |
| Create | `tests/skills/test_meta_analyzer.py` | 版本强势测试 |
| Create | `tests/skills/test_knowledge_query.py` | 知识查询测试 |
| Create | `tests/skills/test_web_search.py` | 智能搜索测试 |
| Modify | `core/agent_controller.py` | 集成 SkillRegistry，改造调用方式 |
| Modify | `web/app.py` | 添加 Skill 状态查询 API |

---

## 任务阶段划分

### 阶段 1：基础设施搭建（第 1 周）

#### Task 1.1: Skill 抽象基类

**Files:**
- Create: `skills/__init__.py`
- Create: `skills/base.py`
- Create: `skills/exceptions.py`

- [ ] **Step 1: Create `skills/__init__.py`**

```python
"""Skill 抽象层

将 DotaHelperAgent 中的轻量产品功能抽象为独立可复用的 Skill 单元。

核心组件：
- BaseSkill: 所有 Skill 的抽象基类
- SkillRegistry: Skill 注册中心
- FallbackHandler: 统一降级处理器
"""

from .base import BaseSkill, SkillResult, SkillContext
from .registry import SkillRegistry, get_registry
from .exceptions import (
    SkillException,
    SkillExecutionError,
    SkillTimeoutError,
    SkillFallbackError,
)
from .fallback import FallbackHandler, FallbackStrategy

__all__ = [
    'BaseSkill',
    'SkillResult',
    'SkillContext',
    'SkillRegistry',
    'get_registry',
    'FallbackHandler',
    'FallbackStrategy',
    'SkillException',
    'SkillExecutionError',
    'SkillTimeoutError',
    'SkillFallbackError',
]
```

- [ ] **Step 2: Create `skills/exceptions.py`**

```python
"""Skill 异常定义

定义 Skill 执行过程中可能抛出的异常类型。
"""

from typing import Optional


class SkillException(Exception):
    """Skill 基础异常"""
    
    def __init__(self, message: str, skill_name: Optional[str] = None):
        self.skill_name = skill_name
        super().__init__(message)


class SkillExecutionError(SkillException):
    """Skill 执行错误（如 LLM 调用失败、参数错误）"""
    pass


class SkillTimeoutError(SkillException):
    """Skill 执行超时"""
    pass


class SkillFallbackError(SkillException):
    """Skill 降级策略也失败"""
    pass
```

- [ ] **Step 3: Create `skills/base.py`**

```python
"""Skill 抽象基类

所有具体 Skill 必须继承 BaseSkill 并实现 execute 方法。
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Callable, Awaitable
import time
import logging

from .exceptions import SkillExecutionError

logger = logging.getLogger(__name__)


@dataclass
class SkillContext:
    """Skill 执行上下文
    
    Attributes:
        session_id: 会话 ID
        user_id: 用户 ID
        trace_id: 追踪 ID（用于 Langfuse）
        metadata: 额外元数据
    """
    session_id: Optional[str] = None
    user_id: Optional[str] = None
    trace_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SkillResult:
    """Skill 执行结果
    
    Attributes:
        success: 是否执行成功
        data: 结果数据
        error: 错误信息（如果失败）
        confidence: 置信度 (0.0-1.0)
        execution_time: 执行耗时（秒）
        fallback_used: 是否使用了降级方案
        metadata: 额外元数据
    """
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
    """Skill 抽象基类
    
    所有具体 Skill 必须继承此类并实现 execute 和 _fallback 方法。
    
    Attributes:
        name: Skill 名称（唯一）
        version: Skill 版本
        description: Skill 描述
        timeout: 执行超时时间（秒）
    """
    
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
        """执行 Skill 主逻辑（LLM 推理）
        
        Args:
            input_data: 输入数据
            context: 执行上下文
            
        Returns:
            SkillResult: 执行结果
        """
        pass
    
    @abstractmethod
    async def _fallback(
        self,
        input_data: Any,
        context: Optional[SkillContext] = None,
        error: Optional[Exception] = None,
    ) -> SkillResult:
        """降级方案（规则驱动或缓存返回）
        
        当主逻辑执行失败时调用此方法。
        
        Args:
            input_data: 输入数据
            context: 执行上下文
            error: 主逻辑抛出的异常
            
        Returns:
            SkillResult: 降级结果
        """
        pass
    
    async def run(
        self,
        input_data: Any,
        context: Optional[SkillContext] = None,
    ) -> SkillResult:
        """执行入口（带降级和超时处理）
        
        优先执行 execute，失败时自动调用 _fallback。
        """
        context = context or SkillContext()
        start_time = time.time()
        
        try:
            import asyncio
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
        """启用 Skill"""
        self._enabled = True
    
    def disable(self) -> None:
        """禁用 Skill"""
        self._enabled = False
    
    @property
    def enabled(self) -> bool:
        return self._enabled
```

#### Task 1.2: Skill 注册表

**Files:**
- Create: `skills/registry.py`

- [ ] **Step 1: Create `skills/registry.py`**

```python
"""Skill 注册表

提供 Skill 的注册、查询、调用能力。
采用单例模式，全局共享一个注册表实例。
"""

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
        """注册 Skill
        
        Args:
            skill: Skill 实例
            
        Raises:
            ValueError: Skill 名称已存在
        """
        if skill.name in self._skills:
            raise ValueError(f"Skill '{skill.name}' already registered")
        self._skills[skill.name] = skill
        logger.info(f"Registered skill: {skill.name} v{skill.version}")
    
    def unregister(self, name: str) -> None:
        """注销 Skill"""
        if name in self._skills:
            del self._skills[name]
            logger.info(f"Unregistered skill: {name}")
    
    def get(self, name: str) -> Optional[BaseSkill]:
        """获取 Skill"""
        return self._skills.get(name)
    
    def list_all(self) -> List[str]:
        """列出所有已注册的 Skill 名称"""
        return list(self._skills.keys())
    
    async def invoke(
        self,
        name: str,
        input_data,
        context: Optional[SkillContext] = None,
    ) -> SkillResult:
        """调用 Skill
        
        Args:
            name: Skill 名称
            input_data: 输入数据
            context: 执行上下文
            
        Returns:
            SkillResult: 执行结果
        """
        skill = self.get(name)
        if skill is None:
            raise SkillExecutionError(f"Skill '{name}' not found", skill_name=name)
        if not skill.enabled:
            raise SkillExecutionError(f"Skill '{name}' is disabled", skill_name=name)
        return await skill.run(input_data, context)


def get_registry() -> SkillRegistry:
    """获取全局注册表单例"""
    return SkillRegistry()
```

#### Task 1.3: 降级框架

**Files:**
- Create: `skills/fallback.py`

- [ ] **Step 1: Create `skills/fallback.py`**

```python
"""统一降级框架

当 LLM 驱动的主逻辑失败时，按策略执行降级方案。
"""

import logging
from enum import Enum
from typing import Any, Callable, Awaitable, Optional

from .base import BaseSkill, SkillContext, SkillResult

logger = logging.getLogger(__name__)


class FallbackStrategy(Enum):
    """降级策略"""
    RULE_BASED = "rule_based"       # 规则驱动
    CACHE = "cache"                  # 缓存返回
    DEFAULT = "default"              # 默认值
    CHAIN = "chain"                  # 链式降级（依次尝试）


class FallbackHandler:
    """降级处理器"""
    
    @staticmethod
    async def execute_with_fallback(
        primary: Callable[[Any, Optional[SkillContext]], Awaitable[SkillResult]],
        fallback_chain: list,
        input_data: Any,
        context: Optional[SkillContext] = None,
    ) -> SkillResult:
        """执行主逻辑并在失败时依次尝试降级方案
        
        Args:
            primary: 主逻辑（通常是 LLM 调用）
            fallback_chain: 降级方案列表，每个元素是 (name, callable) 元组
            input_data: 输入数据
            context: 上下文
            
        Returns:
            SkillResult: 主逻辑或降级方案的执行结果
        """
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

#### Task 1.4: 基础测试

**Files:**
- Create: `tests/skills/__init__.py`
- Create: `tests/skills/test_base.py`
- Create: `tests/skills/test_registry.py`
- Create: `tests/skills/test_fallback.py`

- [ ] **Step 1: Create `tests/skills/__init__.py`**

```python
"""Skill 测试包"""
```

- [ ] **Step 2: Create `tests/skills/test_base.py`**

```python
"""Skill 基类测试"""

import asyncio
import pytest
from skills.base import BaseSkill, SkillResult, SkillContext
from skills.exceptions import SkillExecutionError


class MockSkill(BaseSkill):
    def __init__(self, name: str, fail_main: bool = False, fail_fallback: bool = False):
        super().__init__(name=name, timeout=5.0)
        self.fail_main = fail_main
        self.fail_fallback = fail_fallback
    
    async def execute(self, input_data, context=None):
        if self.fail_main:
            raise RuntimeError("Main execution failed")
        return SkillResult(success=True, data=f"main-{input_data}")
    
    async def _fallback(self, input_data, context=None, error=None):
        if self.fail_fallback:
            raise RuntimeError("Fallback failed")
        return SkillResult(success=True, data=f"fallback-{input_data}")


@pytest.mark.asyncio
async def test_skill_success():
    skill = MockSkill("test_skill")
    result = await skill.run("input")
    assert result.success
    assert result.data == "main-input"
    assert not result.fallback_used


@pytest.mark.asyncio
async def test_skill_fallback():
    skill = MockSkill("test_skill", fail_main=True)
    result = await skill.run("input")
    assert result.success
    assert result.data == "fallback-input"
    assert result.fallback_used


@pytest.mark.asyncio
async def test_skill_both_fail():
    skill = MockSkill("test_skill", fail_main=True, fail_fallback=True)
    with pytest.raises(SkillExecutionError):
        await skill.run("input")
```

- [ ] **Step 3: Create `tests/skills/test_registry.py`**

```python
"""注册表测试"""

import pytest
from skills.registry import SkillRegistry
from skills.base import BaseSkill, SkillResult


class DummySkill(BaseSkill):
    async def execute(self, input_data, context=None):
        return SkillResult(success=True, data=input_data)
    async def _fallback(self, input_data, context=None, error=None):
        return SkillResult(success=True, data=input_data)


def test_registry_singleton():
    r1 = SkillRegistry()
    r2 = SkillRegistry()
    assert r1 is r2


def test_register_and_get():
    registry = SkillRegistry()
    registry._skills.clear()  # 测试隔离
    skill = DummySkill(name="dummy")
    registry.register(skill)
    assert registry.get("dummy") is skill
    assert "dummy" in registry.list_all()


def test_register_duplicate():
    registry = SkillRegistry()
    registry._skills.clear()
    skill = DummySkill(name="dummy")
    registry.register(skill)
    with pytest.raises(ValueError):
        registry.register(skill)
```

---

### 阶段 2：实现具体 Skill（第 2-3 周）

#### Task 2.1: 阵容分析 Skill

**Files:**
- Create: `skills/lineup_analyzer/__init__.py`
- Create: `skills/lineup_analyzer/skill.py`
- Create: `skills/lineup_analyzer/prompts.yaml`
- Create: `tests/skills/test_lineup_analyzer.py`

- [ ] **Step 1: Create `skills/lineup_analyzer/prompts.yaml`**

```yaml
lineup_analysis:
  version: "1.0.0"
  template: |
    你是一名专业的 Dota 2 阵容分析专家。

    ## 己方阵容
    {radiant_heroes}

    ## 敌方阵容
    {dire_heroes}

    ## 任务
    分析双方阵容的优劣势，包括：
    1. 己方阵容优势（控制、爆发、推进、分推等）
    2. 己方阵容劣势（被克制、缺少某些能力）
    3. 敌方阵容优势
    4. 敌方阵容劣势
    5. 关键对决点（哪些对线/团战是胜负手）
    6. 整体胜率评估

    请用简洁清晰的语言输出，控制在 300 字以内。
  variables:
    - radiant_heroes
    - dire_heroes
```

- [ ] **Step 2: Create `skills/lineup_analyzer/skill.py`**

```python
"""阵容分析 Skill

分析敌我双方阵容的优劣势，给出阵容评估。
"""

from typing import Any, Dict, List, Optional

import yaml
from pathlib import Path

from ..base import BaseSkill, SkillContext, SkillResult


class LineupAnalyzerSkill(BaseSkill):
    """阵容分析 Skill"""
    
    def __init__(self, llm_client, prompt_path: Optional[str] = None, **kwargs):
        super().__init__(
            name="lineup_analyzer",
            version="1.0.0",
            description="分析敌我双方阵容的优劣势",
            **kwargs,
        )
        self.llm_client = llm_client
        self.prompt_path = prompt_path or str(
            Path(__file__).parent / "prompts.yaml"
        )
        self._prompts = self._load_prompts()
    
    def _load_prompts(self) -> Dict[str, Any]:
        with open(self.prompt_path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    
    def _format_prompt(self, radiant_heroes: List[str], dire_heroes: List[str]) -> str:
        template = self._prompts['lineup_analysis']['template']
        return template.format(
            radiant_heroes="、".join(radiant_heroes),
            dire_heroes="、".join(dire_heroes),
        )
    
    async def execute(
        self,
        input_data: Dict[str, List[str]],
        context: Optional[SkillContext] = None,
    ) -> SkillResult:
        """执行阵容分析
        
        Args:
            input_data: {
                "radiant_heroes": ["英雄1", "英雄2", ...],
                "dire_heroes": ["英雄1", "英雄2", ...]
            }
        """
        radiant = input_data.get("radiant_heroes", [])
        dire = input_data.get("dire_heroes", [])
        
        prompt = self._format_prompt(radiant, dire)
        response = await self.llm_client.generate(prompt)
        
        return SkillResult(
            success=True,
            data={
                "analysis": response,
                "radiant_heroes": radiant,
                "dire_heroes": dire,
            },
            confidence=0.85,
        )
    
    async def _fallback(
        self,
        input_data: Dict[str, List[str]],
        context: Optional[SkillContext] = None,
        error: Optional[Exception] = None,
    ) -> SkillResult:
        """降级方案：基于规则简单评估"""
        radiant = input_data.get("radiant_heroes", [])
        dire = input_data.get("dire_heroes", [])
        
        return SkillResult(
            success=True,
            data={
                "analysis": f"阵容分析暂不可用。己方英雄数：{len(radiant)}，敌方英雄数：{len(dire)}",
                "radiant_heroes": radiant,
                "dire_heroes": dire,
            },
            confidence=0.3,
        )
```

- [ ] **Step 3: Create `skills/lineup_analyzer/__init__.py`**

```python
from .skill import LineupAnalyzerSkill

__all__ = ['LineupAnalyzerSkill']
```

#### Task 2.2: 多轮对话理解 Skill

**Files:**
- Create: `skills/dialogue_understander/__init__.py`
- Create: `skills/dialogue_understander/skill.py`
- Create: `skills/dialogue_understander/prompts.yaml`
- Create: `tests/skills/test_dialogue_understander.py`

- [ ] **Step 1: Create `skills/dialogue_understander/prompts.yaml`**

```yaml
dialogue_understand:
  version: "1.0.0"
  template: |
    你是一名 Dota 2 助手，需要理解用户的对话上下文。

    ## 对话历史
    {history}

    ## 当前用户输入
    {current_input}

    ## 任务
    1. 指代消解：识别代词（"它"、"他"、"那个英雄"）指代的具体英雄/物品
    2. 意图推断：用户当前想了解什么（克制、出装、技能加点、阵容分析等）
    3. 实体提取：提取所有英雄名称、物品名称、技能名称

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
    }}
  variables:
    - history
    - current_input
```

- [ ] **Step 2: Create `skills/dialogue_understander/skill.py`**

```python
"""多轮对话理解 Skill

处理对话中的指代消解、意图推断、实体提取。
"""

import json
from typing import Any, Dict, List, Optional
from pathlib import Path

import yaml

from ..base import BaseSkill, SkillContext, SkillResult


class DialogueUnderstanderSkill(BaseSkill):
    """多轮对话理解 Skill"""
    
    def __init__(self, llm_client, prompt_path: Optional[str] = None, **kwargs):
        super().__init__(
            name="dialogue_understander",
            version="1.0.0",
            description="多轮对话上下文理解（指代消解、意图推断、实体提取）",
            **kwargs,
        )
        self.llm_client = llm_client
        self.prompt_path = prompt_path or str(
            Path(__file__).parent / "prompts.yaml"
        )
        self._prompts = self._load_prompts()
    
    def _load_prompts(self) -> Dict[str, Any]:
        with open(self.prompt_path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    
    def _format_history(self, history: List[Dict[str, str]]) -> str:
        lines = []
        for msg in history[-10:]:  # 最近 10 条
            role = msg.get("role", "user")
            content = msg.get("content", "")
            lines.append(f"{role}: {content}")
        return "\n".join(lines) if lines else "（无历史对话）"
    
    async def execute(
        self,
        input_data: Dict[str, Any],
        context: Optional[SkillContext] = None,
    ) -> SkillResult:
        """执行对话理解
        
        Args:
            input_data: {
                "history": [{"role": "user/assistant", "content": "..."}, ...],
                "current_input": "用户当前输入"
            }
        """
        history = input_data.get("history", [])
        current_input = input_data.get("current_input", "")
        
        template = self._prompts['dialogue_understand']['template']
        prompt = template.format(
            history=self._format_history(history),
            current_input=current_input,
        )
        
        response = await self.llm_client.generate(prompt)
        
        try:
            parsed = json.loads(response)
        except json.JSONDecodeError:
            parsed = {
                "enhanced_query": current_input,
                "intent": "unknown",
                "entities": {"heroes": [], "items": [], "skills": []},
            }
        
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
        """降级方案：直接返回当前输入"""
        current_input = input_data.get("current_input", "")
        return SkillResult(
            success=True,
            data={
                "enhanced_query": current_input,
                "intent": "unknown",
                "entities": {"heroes": [], "items": [], "skills": []},
            },
            confidence=0.3,
        )
```

#### Task 2.3: 版本强势查询 Skill

**Files:**
- Create: `skills/meta_analyzer/__init__.py`
- Create: `skills/meta_analyzer/skill.py`
- Create: `skills/meta_analyzer/prompts.yaml`
- Create: `tests/skills/test_meta_analyzer.py`

- [ ] **Step 1: Create `skills/meta_analyzer/prompts.yaml`**

```yaml
meta_query:
  version: "1.0.0"
  template: |
    你是一名 Dota 2 版本分析师。

    ## 当前版本数据
    {meta_data}

    ## 用户问题
    {user_query}

    ## 任务
    根据版本数据回答用户问题，包括强势英雄、版本趋势、ban/pick 建议等。
    回答简洁清晰，控制在 200 字以内。
  variables:
    - meta_data
    - user_query
```

- [ ] **Step 2: Create `skills/meta_analyzer/skill.py`**

```python
"""版本强势查询 Skill

查询当前版本热门/强势英雄。
"""

from typing import Any, Dict, Optional
from pathlib import Path

import yaml

from ..base import BaseSkill, SkillContext, SkillResult


class MetaAnalyzerSkill(BaseSkill):
    """版本强势查询 Skill"""
    
    def __init__(self, llm_client, data_fetcher, prompt_path: Optional[str] = None, **kwargs):
        super().__init__(
            name="meta_analyzer",
            version="1.0.0",
            description="查询当前版本热门/强势英雄",
            **kwargs,
        )
        self.llm_client = llm_client
        self.data_fetcher = data_fetcher  # 获取版本数据的函数
        self.prompt_path = prompt_path or str(
            Path(__file__).parent / "prompts.yaml"
        )
        self._prompts = self._load_prompts()
    
    def _load_prompts(self) -> Dict[str, Any]:
        with open(self.prompt_path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    
    async def execute(
        self,
        input_data: str,
        context: Optional[SkillContext] = None,
    ) -> SkillResult:
        """执行版本强势查询
        
        Args:
            input_data: 用户查询（如"当前版本哪些英雄强势？"）
        """
        meta_data = await self.data_fetcher()
        
        template = self._prompts['meta_query']['template']
        prompt = template.format(
            meta_data=meta_data,
            user_query=input_data,
        )
        
        response = await self.llm_client.generate(prompt)
        
        return SkillResult(
            success=True,
            data={
                "answer": response,
                "meta_data": meta_data,
            },
            confidence=0.8,
        )
    
    async def _fallback(
        self,
        input_data: str,
        context: Optional[SkillContext] = None,
        error: Optional[Exception] = None,
    ) -> SkillResult:
        """降级方案：返回缓存或默认数据"""
        return SkillResult(
            success=True,
            data={
                "answer": "版本数据暂不可用，请稍后再试。",
                "meta_data": None,
            },
            confidence=0.2,
        )
```

#### Task 2.4: 知识查询 Skill

**Files:**
- Create: `skills/knowledge_query/__init__.py`
- Create: `skills/knowledge_query/skill.py`
- Create: `tests/skills/test_knowledge_query.py`

- [ ] **Step 1: Create `skills/knowledge_query/skill.py`**

```python
"""知识查询 Skill

检索攻略文档并生成回答。
"""

from typing import Any, Dict, List, Optional

from ..base import BaseSkill, SkillContext, SkillResult


class KnowledgeQuerySkill(BaseSkill):
    """知识查询 Skill"""
    
    def __init__(self, llm_client, vector_store, top_k: int = 5, **kwargs):
        super().__init__(
            name="knowledge_query",
            version="1.0.0",
            description="检索攻略文档并生成回答",
            **kwargs,
        )
        self.llm_client = llm_client
        self.vector_store = vector_store
        self.top_k = top_k
    
    async def execute(
        self,
        input_data: str,
        context: Optional[SkillContext] = None,
    ) -> SkillResult:
        """执行知识查询
        
        Args:
            input_data: 用户查询（如"PA 怎么出装？"）
        """
        # 1. 向量检索
        docs = await self.vector_store.search(input_data, top_k=self.top_k)
        
        # 2. 构造 prompt
        context_text = "\n\n".join([d.content for d in docs])
        prompt = f"""基于以下攻略资料回答用户问题：

## 攻略资料
{context_text}

## 用户问题
{input_data}

请给出准确、简洁的回答。"""
        
        # 3. LLM 生成回答
        response = await self.llm_client.generate(prompt)
        
        return SkillResult(
            success=True,
            data={
                "answer": response,
                "sources": [d.metadata for d in docs],
            },
            confidence=0.85,
            metadata={"docs_count": len(docs)},
        )
    
    async def _fallback(
        self,
        input_data: str,
        context: Optional[SkillContext] = None,
        error: Optional[Exception] = None,
    ) -> SkillResult:
        """降级方案：返回基础提示"""
        return SkillResult(
            success=True,
            data={
                "answer": "知识库查询暂不可用。",
                "sources": [],
            },
            confidence=0.2,
        )
```

#### Task 2.5: 智能搜索 Skill

**Files:**
- Create: `skills/web_search/__init__.py`
- Create: `skills/web_search/skill.py`
- Create: `tests/skills/test_web_search.py`

- [ ] **Step 1: Create `skills/web_search/skill.py`**

```python
"""智能搜索 Skill

使用 DuckDuckGo 搜索最新 Dota 2 信息并生成摘要。
"""

from typing import Any, Dict, List, Optional

from ..base import BaseSkill, SkillContext, SkillResult


class WebSearchSkill(BaseSkill):
    """智能搜索 Skill"""
    
    def __init__(self, llm_client, search_engine, max_results: int = 5, **kwargs):
        super().__init__(
            name="web_search",
            version="1.0.0",
            description="搜索最新 Dota 2 信息并生成摘要",
            **kwargs,
        )
        self.llm_client = llm_client
        self.search_engine = search_engine  # DuckDuckGo 搜索封装
        self.max_results = max_results
    
    async def execute(
        self,
        input_data: str,
        context: Optional[SkillContext] = None,
    ) -> SkillResult:
        """执行智能搜索
        
        Args:
            input_data: 搜索关键词
        """
        # 自动添加 Dota 2 前缀
        query = f"Dota 2 {input_data}"
        
        # 1. 搜索
        results = await self.search_engine.search(query, max_results=self.max_results)
        
        # 2. LLM 摘要
        results_text = "\n\n".join([
            f"标题：{r.title}\n摘要：{r.snippet}\n链接：{r.url}"
            for r in results
        ])
        prompt = f"""基于以下搜索结果回答用户问题：

## 搜索结果
{results_text}

## 用户问题
{input_data}

请给出简洁准确的回答，并标注信息来源。"""
        
        response = await self.llm_client.generate(prompt)
        
        return SkillResult(
            success=True,
            data={
                "answer": response,
                "sources": [{"title": r.title, "url": r.url} for r in results],
            },
            confidence=0.75,
        )
    
    async def _fallback(
        self,
        input_data: str,
        context: Optional[SkillContext] = None,
        error: Optional[Exception] = None,
    ) -> SkillResult:
        """降级方案"""
        return SkillResult(
            success=True,
            data={
                "answer": "搜索功能暂不可用。",
                "sources": [],
            },
            confidence=0.2,
        )
```

---

### 阶段 3：集成与迁移（第 4 周）

#### Task 3.1: Agent 集成

**Files:**
- Modify: `core/agent_controller.py`
- Create: `config/skills_config.yaml`

- [ ] **Step 1: Create `config/skills_config.yaml`**

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
    cache_ttl: 3600  # 缓存 1 小时
  
  knowledge_query:
    enabled: true
    timeout: 15.0
    top_k: 5
  
  web_search:
    enabled: true
    timeout: 20.0
    max_results: 5
```

- [ ] **Step 2: Modify `core/agent_controller.py`**

在 `agent_controller.py` 中添加 Skill 注册和调用逻辑：

```python
# 在 AgentController.__init__ 中添加
from skills import get_registry, SkillContext
from skills.lineup_analyzer import LineupAnalyzerSkill
from skills.dialogue_understander import DialogueUnderstanderSkill
from skills.meta_analyzer import MetaAnalyzerSkill
from skills.knowledge_query import KnowledgeQuerySkill
from skills.web_search import WebSearchSkill

class AgentController:
    def __init__(self, ...):
        # ... 现有初始化代码 ...
        self._register_skills()
    
    def _register_skills(self):
        """注册所有 Skill"""
        registry = get_registry()
        
        # 注册阵容分析 Skill
        registry.register(LineupAnalyzerSkill(
            llm_client=self.llm_client,
        ))
        
        # 注册多轮对话理解 Skill
        registry.register(DialogueUnderstanderSkill(
            llm_client=self.llm_client,
        ))
        
        # 注册版本强势 Skill
        registry.register(MetaAnalyzerSkill(
            llm_client=self.llm_client,
            data_fetcher=self._fetch_meta_data,
        ))
        
        # 注册知识查询 Skill
        registry.register(KnowledgeQuerySkill(
            llm_client=self.llm_client,
            vector_store=self.vector_store,
        ))
        
        # 注册智能搜索 Skill
        registry.register(WebSearchSkill(
            llm_client=self.llm_client,
            search_engine=self.search_engine,
        ))
```

#### Task 3.2: API 接口

**Files:**
- Modify: `web/app.py`

- [ ] **Step 1: Add Skill API endpoints to `web/app.py`**

```python
# 在 web/app.py 中添加

from skills import get_registry

@app.route('/api/skills', methods=['GET'])
def list_skills():
    """列出所有已注册的 Skill"""
    registry = get_registry()
    return jsonify({
        "skills": registry.list_all(),
    })

@app.route('/api/skills/<name>/invoke', methods=['POST'])
def invoke_skill(name):
    """调用指定 Skill"""
    import asyncio
    from skills import SkillContext
    
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

## 分阶段实施计划

| 阶段 | 时间 | 任务 | 验收标准 |
|------|------|------|---------|
| **阶段 1** | 第 1 周 | 基础设施搭建（基类、注册表、降级框架、测试） | 所有基础设施测试通过 |
| **阶段 2.1** | 第 2 周初 | 实现阵容分析 Skill | 单元测试通过，集成到 Agent |
| **阶段 2.2** | 第 2 周中 | 实现多轮对话理解 Skill | 单元测试通过，集成到 Agent |
| **阶段 2.3** | 第 2 周末 | 实现版本强势查询 Skill | 单元测试通过，集成到 Agent |
| **阶段 2.4** | 第 3 周初 | 实现知识查询 Skill | 单元测试通过，集成到 Agent |
| **阶段 2.5** | 第 3 周中 | 实现智能搜索 Skill | 单元测试通过，集成到 Agent |
| **阶段 3** | 第 3 周末 - 第 4 周 | 集成到 AgentController、API 接口、文档 | 全部 Skill 可通过 API 调用 |
| **阶段 4** | 第 4 周 | 清理旧代码、完整 E2E 测试、文档更新 | 旧实现可移除（保留作为参考） |

---

## 关键决策与注意事项

### 设计决策

1. **统一接口**：所有 Skill 继承 `BaseSkill`，实现 `execute` 和 `_fallback` 两个方法
2. **单例注册表**：全局共享一个 `SkillRegistry`，避免重复注册
3. **降级统一**：每个 Skill 必须实现 `_fallback`，主逻辑失败时自动调用
4. **Prompt 外置**：所有 Prompt 模板存放在 `prompts.yaml` 中，便于版本管理

### 风险与缓解

| 风险 | 缓解措施 |
|------|---------|
| LLM 调用延迟高 | Skill 设置超时时间，失败时降级 |
| 多个 Skill 串联调用增加延迟 | 主 Agent 优化调度，必要时串行调用 |
| 降级方案质量差 | 保留现有规则驱动实现作为参考 |
| 迁移过程破坏现有功能 | 渐进式迁移，先集成新 Skill，再移除旧代码 |

### 回退方案

- 保留现有功能代码，新 Skill 作为可选路径
- 通过配置开关控制是否使用 Skill
- 如有问题可快速回退到旧实现

---

## 验收标准

1. **功能完整性**：5 个 Skill 全部实现并集成
2. **测试覆盖**：所有 Skill 单元测试通过，覆盖率 > 80%
3. **集成测试**：E2E 测试通过，主 Agent 可通过 Skill 完成典型任务
4. **性能指标**：单 Skill 调用延迟 < 3 秒（含 LLM 推理）
5. **降级有效**：LLM 不可用时降级方案能返回合理结果
6. **文档完整**：API 文档、使用示例、架构图齐全

---

> **文档版本**: v1.0
> **创建时间**: 2026-07-06
> **预计完成**: 2026-08-03（第 4 周）
