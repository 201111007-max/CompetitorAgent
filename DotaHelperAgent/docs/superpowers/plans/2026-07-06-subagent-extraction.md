# SubAgent 抽取 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 DotaHelperAgent 中需要多步推理的产品功能抽取为独立的 SubAgent 单元，包括英雄克制推荐、出装推荐、技能加点推荐、游戏事件提醒、主动推荐、用户反馈学习。

**Architecture:** 定义统一 SubAgent 接口 → 各功能实现为独立 SubAgent（自带工具集和推理能力）→ 主 Agent 通过 SubAgentOrchestrator 调度 → 保留规则驱动降级方案

**Tech Stack:** Python, Abstract Base Class, AsyncIO, Langfuse (Trace), PyYAML (Config)

---

## 背景与目标

根据 [ARCHITECTURE_ANALYSIS.md 第十七章](../ARCHITECTURE_ANALYSIS.md#十七skill-subagent-可替代功能分析) 的分析，DotaHelperAgent 中有 6 个产品功能适合用 SubAgent 模式替代实现：

| 产品功能 | 适用原因 |
|---------|---------|
| 英雄克制推荐 | 多步推理：API 调用 + 数据分析 + LLM 评估 + 排序 |
| 出装推荐 | 多步推理：查数据 + 分析局势 + 查询物品库 + LLM 推荐 |
| 技能加点推荐 | 多步推理：查技能 + 分析局势 + LLM 生成加点 |
| 游戏事件提醒 | 事件检测 + 上下文构建 + LLM 生成建议 |
| 主动推荐 | 感知状态 + 判断触发 + 生成建议 |
| 用户反馈学习 | 收集 + 评估 + 调整闭环 |

**核心收益**：
- 可测试性：SubAgent 独立测试，接口清晰
- 可替换性：可替换 LLM 实现或工具集
- 自主编排：SubAgent 可自主决定调用哪些工具
- 降级统一：统一降级框架

---

## File Structure

| Action | File | Responsibility |
|--------|------|---------------|
| Create | `subagents/__init__.py` | SubAgent 包初始化 |
| Create | `subagents/base.py` | SubAgent 抽象基类（带工具调用能力） |
| Create | `subagents/orchestrator.py` | SubAgent 编排器（类似主 Agent） |
| Create | `subagents/tool_executor.py` | 工具执行器（异步并行） |
| Create | `subagents/exceptions.py` | SubAgent 异常定义 |
| Create | `subagents/counter_pick/__init__.py` | 英雄克制推荐 SubAgent |
| Create | `subagents/counter_pick/agent.py` | 英雄克制 SubAgent 实现 |
| Create | `subagents/counter_pick/tools.py` | 英雄克制专用工具 |
| Create | `subagents/counter_pick/prompts.yaml` | Prompt 模板 |
| Create | `subagents/item_recommender/__init__.py` | 出装推荐 SubAgent |
| Create | `subagents/item_recommender/agent.py` | 出装推荐 SubAgent 实现 |
| Create | `subagents/item_recommender/tools.py` | 出装推荐专用工具 |
| Create | `subagents/skill_builder/__init__.py` | 技能加点 SubAgent |
| Create | `subagents/skill_builder/agent.py` | 技能加点 SubAgent 实现 |
| Create | `subagents/skill_builder/tools.py` | 技能加点专用工具 |
| Create | `subagents/event_advisor/__init__.py` | 游戏事件提醒 SubAgent |
| Create | `subagents/event_advisor/agent.py` | 事件提醒 SubAgent 实现 |
| Create | `subagents/proactive_recommender/__init__.py` | 主动推荐 SubAgent |
| Create | `subagents/proactive_recommender/agent.py` | 主动推荐 SubAgent 实现 |
| Create | `subagents/feedback_learner/__init__.py` | 反馈学习 SubAgent |
| Create | `subagents/feedback_learner/agent.py` | 反馈学习 SubAgent 实现 |
| Create | `config/subagents_config.yaml` | SubAgent 全局配置 |
| Create | `tests/subagents/__init__.py` | 测试包 |
| Create | `tests/subagents/test_base.py` | 基类测试 |
| Create | `tests/subagents/test_orchestrator.py` | 编排器测试 |
| Create | `tests/subagents/test_counter_pick.py` | 英雄克制测试 |
| Create | `tests/subagents/test_item_recommender.py` | 出装推荐测试 |
| Create | `tests/subagents/test_skill_builder.py` | 技能加点测试 |
| Create | `tests/subagents/test_event_advisor.py` | 事件提醒测试 |
| Modify | `core/agent_controller.py` | 集成 SubAgentOrchestrator |
| Modify | `web/app.py` | 添加 SubAgent API 端点 |

---

## 任务阶段划分

### 阶段 1：基础设施搭建（第 1-2 周）

#### Task 1.1: SubAgent 抽象基类

**Files:**
- Create: `subagents/__init__.py`
- Create: `subagents/exceptions.py`
- Create: `subagents/base.py`

- [ ] **Step 1: Create `subagents/__init__.py`**

```python
"""SubAgent 抽象层

将 DotaHelperAgent 中需要多步推理的产品功能抽象为独立 SubAgent。

核心组件：
- BaseSubAgent: 所有 SubAgent 的抽象基类
- SubAgentOrchestrator: SubAgent 编排器
- ToolExecutor: 工具执行器
"""

from .base import BaseSubAgent, SubAgentResult, SubAgentContext, AgentStep
from .orchestrator import SubAgentOrchestrator, get_orchestrator
from .tool_executor import ToolExecutor
from .exceptions import (
    SubAgentException,
    SubAgentExecutionError,
    SubAgentMaxStepsError,
    SubAgentToolError,
)

__all__ = [
    'BaseSubAgent',
    'SubAgentResult',
    'SubAgentContext',
    'AgentStep',
    'SubAgentOrchestrator',
    'get_orchestrator',
    'ToolExecutor',
    'SubAgentException',
    'SubAgentExecutionError',
    'SubAgentMaxStepsError',
    'SubAgentToolError',
]
```

- [ ] **Step 2: Create `subagents/exceptions.py`**

```python
"""SubAgent 异常定义"""

from typing import Optional


class SubAgentException(Exception):
    """SubAgent 基础异常"""
    
    def __init__(self, message: str, subagent_name: Optional[str] = None):
        self.subagent_name = subagent_name
        super().__init__(message)


class SubAgentExecutionError(SubAgentException):
    """SubAgent 执行错误"""
    pass


class SubAgentMaxStepsError(SubAgentException):
    """SubAgent 超过最大步数"""
    pass


class SubAgentToolError(SubAgentException):
    """SubAgent 工具调用错误"""
    pass
```

- [ ] **Step 3: Create `subagents/base.py`**

```python
"""SubAgent 抽象基类

所有具体 SubAgent 必须继承 BaseSubAgent 并实现 think、act、observe 循环。
SubAgent 具备自主调用工具的能力，可完成多步推理。
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
import asyncio
import time
import logging

from .exceptions import SubAgentExecutionError, SubAgentMaxStepsError, SubAgentToolError

logger = logging.getLogger(__name__)


@dataclass
class AgentStep:
    """SubAgent 单步执行记录"""
    step_number: int
    thought: str
    action: str
    action_input: Dict[str, Any]
    observation: Any
    timestamp: float = field(default_factory=time.time)


@dataclass
class SubAgentContext:
    """SubAgent 执行上下文"""
    session_id: Optional[str] = None
    user_id: Optional[str] = None
    trace_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SubAgentResult:
    """SubAgent 执行结果"""
    success: bool
    data: Any
    error: Optional[str] = None
    confidence: float = 1.0
    execution_time: float = 0.0
    steps: List[AgentStep] = field(default_factory=list)
    fallback_used: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'success': self.success,
            'data': self.data,
            'error': self.error,
            'confidence': self.confidence,
            'execution_time': self.execution_time,
            'steps_count': len(self.steps),
            'fallback_used': self.fallback_used,
            'metadata': self.metadata,
        }


class BaseSubAgent(ABC):
    """SubAgent 抽象基类
    
    采用 ReAct 推理循环：Think → Act → Observe → ... → Finish
    
    Attributes:
        name: SubAgent 名称
        version: 版本
        max_steps: 最大推理步数
        timeout: 总超时时间
    """
    
    def __init__(
        self,
        name: str,
        version: str = "1.0.0",
        description: str = "",
        max_steps: int = 5,
        timeout: float = 60.0,
    ):
        self.name = name
        self.version = version
        self.description = description
        self.max_steps = max_steps
        self.timeout = timeout
        self._tools: Dict[str, callable] = {}
        self._enabled = True
    
    def register_tool(self, name: str, func: callable, description: str = "") -> None:
        """注册工具"""
        self._tools[name] = {
            'func': func,
            'description': description,
        }
        logger.info(f"SubAgent '{self.name}' registered tool: {name}")
    
    def list_tools(self) -> List[str]:
        """列出所有工具"""
        return list(self._tools.keys())
    
    @abstractmethod
    async def think(
        self,
        input_data: Any,
        context: SubAgentContext,
        history: List[AgentStep],
    ) -> Dict[str, Any]:
        """思考步骤：决定下一步动作
        
        Returns:
            {
                "thought": "推理过程",
                "action": "tool_name" or "finish",
                "action_input": {...}
            }
        """
        pass
    
    @abstractmethod
    async def _fallback(
        self,
        input_data: Any,
        context: Optional[SubAgentContext] = None,
        error: Optional[Exception] = None,
    ) -> SubAgentResult:
        """降级方案"""
        pass
    
    async def execute_tool(self, name: str, input_data: Dict[str, Any]) -> Any:
        """执行工具"""
        if name not in self._tools:
            raise SubAgentToolError(f"Tool '{name}' not found", subagent_name=self.name)
        try:
            tool_info = self._tools[name]
            result = await tool_info['func'](**input_data)
            return result
        except Exception as e:
            raise SubAgentToolError(
                f"Tool '{name}' execution failed: {e}",
                subagent_name=self.name,
            ) from e
    
    async def run(
        self,
        input_data: Any,
        context: Optional[SubAgentContext] = None,
    ) -> SubAgentResult:
        """执行入口（ReAct 循环）"""
        context = context or SubAgentContext()
        start_time = time.time()
        steps: List[AgentStep] = []
        
        try:
            for step_num in range(1, self.max_steps + 1):
                # 检查总超时
                if time.time() - start_time > self.timeout:
                    raise SubAgentExecutionError(
                        f"SubAgent '{self.name}' timeout",
                        subagent_name=self.name,
                    )
                
                # 1. Think
                decision = await self.think(input_data, context, steps)
                
                thought = decision.get("thought", "")
                action = decision.get("action", "")
                action_input = decision.get("action_input", {})
                
                # 2. Act & Observe
                if action == "finish":
                    # 结束循环
                    return SubAgentResult(
                        success=True,
                        data=action_input,
                        execution_time=time.time() - start_time,
                        steps=steps,
                        confidence=0.85,
                    )
                
                # 执行工具
                try:
                    observation = await self.execute_tool(action, action_input)
                except SubAgentToolError as e:
                    observation = {"error": str(e)}
                
                # 3. 记录步骤
                step = AgentStep(
                    step_number=step_num,
                    thought=thought,
                    action=action,
                    action_input=action_input,
                    observation=observation,
                )
                steps.append(step)
            
            # 超过最大步数
            raise SubAgentMaxStepsError(
                f"SubAgent '{self.name}' exceeded max steps ({self.max_steps})",
                subagent_name=self.name,
            )
        
        except Exception as e:
            logger.warning(
                f"SubAgent '{self.name}' execution failed: {e}, "
                f"falling back to rule-based approach"
            )
            try:
                fallback_result = await self._fallback(input_data, context, e)
                fallback_result.execution_time = time.time() - start_time
                fallback_result.fallback_used = True
                fallback_result.steps = steps
                return fallback_result
            except Exception as fallback_error:
                raise SubAgentExecutionError(
                    f"Both main and fallback failed: {fallback_error}",
                    subagent_name=self.name,
                ) from fallback_error
    
    def enable(self) -> None:
        self._enabled = True
    
    def disable(self) -> None:
        self._enabled = False
    
    @property
    def enabled(self) -> bool:
        return self._enabled
```

#### Task 1.2: 工具执行器

**Files:**
- Create: `subagents/tool_executor.py`

- [ ] **Step 1: Create `subagents/tool_executor.py`**

```python
"""工具执行器

支持并行执行多个独立的工具调用，提升 SubAgent 效率。
"""

import asyncio
import logging
from typing import Any, Dict, List, Optional

from .exceptions import SubAgentToolError

logger = logging.getLogger(__name__)


class ToolExecutor:
    """工具执行器"""
    
    def __init__(self, max_concurrency: int = 5):
        self.max_concurrency = max_concurrency
        self._semaphore = asyncio.Semaphore(max_concurrency)
    
    async def execute(
        self,
        tool_name: str,
        tool_func: callable,
        input_data: Dict[str, Any],
        timeout: float = 30.0,
    ) -> Any:
        """执行单个工具"""
        async with self._semaphore:
            try:
                result = await asyncio.wait_for(
                    tool_func(**input_data),
                    timeout=timeout,
                )
                return result
            except asyncio.TimeoutError:
                raise SubAgentToolError(
                    f"Tool '{tool_name}' timeout after {timeout}s"
                )
            except Exception as e:
                raise SubAgentToolError(f"Tool '{tool_name}' failed: {e}") from e
    
    async def execute_parallel(
        self,
        tool_calls: List[Dict[str, Any]],
    ) -> List[Any]:
        """并行执行多个工具调用
        
        Args:
            tool_calls: [{"name": str, "func": callable, "input": dict, "timeout": float}, ...]
            
        Returns:
            List of results (same order as input)
        """
        tasks = [
            self.execute(
                call["name"],
                call["func"],
                call["input"],
                call.get("timeout", 30.0),
            )
            for call in tool_calls
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return results
```

#### Task 1.3: SubAgent 编排器

**Files:**
- Create: `subagents/orchestrator.py`

- [ ] **Step 1: Create `subagents/orchestrator.py`**

```python
"""SubAgent 编排器

全局管理所有 SubAgent，提供注册、查询、调用能力。
"""

import logging
from typing import Dict, List, Optional

from .base import BaseSubAgent, SubAgentResult, SubAgentContext
from .exceptions import SubAgentExecutionError

logger = logging.getLogger(__name__)


class SubAgentOrchestrator:
    """SubAgent 编排器（单例）"""
    
    _instance: Optional['SubAgentOrchestrator'] = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        self._subagents: Dict[str, BaseSubAgent] = {}
        self._initialized = True
    
    def register(self, subagent: BaseSubAgent) -> None:
        """注册 SubAgent"""
        if subagent.name in self._subagents:
            raise ValueError(f"SubAgent '{subagent.name}' already registered")
        self._subagents[subagent.name] = subagent
        logger.info(f"Registered SubAgent: {subagent.name} v{subagent.version}")
    
    def unregister(self, name: str) -> None:
        if name in self._subagents:
            del self._subagents[name]
    
    def get(self, name: str) -> Optional[BaseSubAgent]:
        return self._subagents.get(name)
    
    def list_all(self) -> List[str]:
        return list(self._subagents.keys())
    
    async def invoke(
        self,
        name: str,
        input_data,
        context: Optional[SubAgentContext] = None,
    ) -> SubAgentResult:
        """调用指定 SubAgent"""
        subagent = self.get(name)
        if subagent is None:
            raise SubAgentExecutionError(f"SubAgent '{name}' not found", subagent_name=name)
        if not subagent.enabled:
            raise SubAgentExecutionError(f"SubAgent '{name}' is disabled", subagent_name=name)
        return await subagent.run(input_data, context)


def get_orchestrator() -> SubAgentOrchestrator:
    """获取全局编排器单例"""
    return SubAgentOrchestrator()
```

#### Task 1.4: 基础测试

**Files:**
- Create: `tests/subagents/__init__.py`
- Create: `tests/subagents/test_base.py`
- Create: `tests/subagents/test_orchestrator.py`

- [ ] **Step 1: Create `tests/subagents/__init__.py`**

```python
"""SubAgent 测试包"""
```

- [ ] **Step 2: Create `tests/subagents/test_base.py`**

```python
"""SubAgent 基类测试"""

import asyncio
import pytest
from subagents.base import BaseSubAgent, SubAgentResult, SubAgentContext


class MockSubAgent(BaseSubAgent):
    def __init__(self, fail_at_step: int = None):
        super().__init__(name="mock", max_steps=5, timeout=10.0)
        self.fail_at_step = fail_at_step
        self.current_step = 0
    
    async def think(self, input_data, context, history):
        self.current_step += 1
        if self.fail_at_step and self.current_step >= self.fail_at_step:
            raise RuntimeError("Think failed")
        
        if self.current_step >= 3:
            return {"thought": "done", "action": "finish", "action_input": {"result": "ok"}}
        
        return {
            "thought": f"step {self.current_step}",
            "action": "mock_tool",
            "action_input": {"x": self.current_step},
        }
    
    async def _fallback(self, input_data, context=None, error=None):
        return SubAgentResult(
            success=True,
            data={"fallback": True},
        )
    
    async def mock_tool(self, x: int):
        return {"echo": x}


@pytest.mark.asyncio
async def test_subagent_success():
    agent = MockSubAgent()
    agent.register_tool("mock_tool", agent.mock_tool, "Mock tool")
    result = await agent.run("input")
    assert result.success
    assert result.data == {"result": "ok"}
    assert len(result.steps) == 2  # 两次 think 然后 finish


@pytest.mark.asyncio
async def test_subagent_fallback():
    agent = MockSubAgent(fail_at_step=2)
    agent.register_tool("mock_tool", agent.mock_tool, "Mock tool")
    result = await agent.run("input")
    assert result.success
    assert result.fallback_used
    assert result.data == {"fallback": True}


@pytest.mark.asyncio
async def test_subagent_max_steps():
    class InfiniteAgent(MockSubAgent):
        async def think(self, input_data, context, history):
            return {"thought": "loop", "action": "mock_tool", "action_input": {"x": 1}}
    
    agent = InfiniteAgent()
    agent.max_steps = 3
    agent.register_tool("mock_tool", agent.mock_tool, "Mock tool")
    
    from subagents.exceptions import SubAgentMaxStepsError
    with pytest.raises(SubAgentExecutionError):
        await agent.run("input")
```

---

### 阶段 2：实现具体 SubAgent（第 3-5 周）

#### Task 2.1: 英雄克制推荐 SubAgent

**Files:**
- Create: `subagents/counter_pick/__init__.py`
- Create: `subagents/counter_pick/tools.py`
- Create: `subagents/counter_pick/prompts.yaml`
- Create: `subagents/counter_pick/agent.py`
- Create: `tests/subagents/test_counter_pick.py`

- [ ] **Step 1: Create `subagents/counter_pick/tools.py`**

```python
"""英雄克制推荐专用工具"""

from typing import Any, Dict, List


async def fetch_hero_matchups(enemy_hero: str, top_n: int = 5) -> List[Dict[str, Any]]:
    """获取英雄对局数据
    
    Args:
        enemy_hero: 敌方英雄名称
        top_n: 返回前 N 个克制英雄
        
    Returns:
        [{"hero": "英雄名", "win_rate": 0.58, "advantage": "克制原因"}, ...]
    """
    # TODO: 实际实现时调用 OpenDota API
    # 这里使用 mock 数据
    return [
        {"hero": "敌法师", "win_rate": 0.58, "advantage": "法术免疫克制 PA 标记"},
        {"hero": "潮汐猎人", "win_rate": 0.56, "advantage": "技能增强降低 PA 输出"},
    ]


async def fetch_hero_synergies(my_hero: str) -> List[Dict[str, Any]]:
    """获取英雄协同数据"""
    return [
        {"hero": "水晶室女", "synergy": "提供蓝量回复和控制"},
    ]
```

- [ ] **Step 2: Create `subagents/counter_pick/prompts.yaml`**

```yaml
counter_pick_think:
  version: "1.0.0"
  template: |
    你是 Dota 2 英雄克制分析专家。

    ## 敌方阵容
    {enemy_heroes}

    ## 已查询的对局数据
    {matchup_data}

    ## 历史步骤
    {history}

    ## 当前步骤
    第 {step_number} 步

    ## 任务
    决定下一步动作：
    1. 如果还有敌方英雄没查询克制数据 → 调用 fetch_hero_matchups 工具
    2. 如果数据查询完成 → 综合分析并返回 top 5 克制英雄，action="finish"
    
    请以 JSON 格式输出：
    {{
      "thought": "你的推理过程",
      "action": "fetch_hero_matchups" 或 "finish",
      "action_input": {{...}}
    }}
  variables:
    - enemy_heroes
    - matchup_data
    - history
    - step_number
```

- [ ] **Step 3: Create `subagents/counter_pick/agent.py`**

```python
"""英雄克制推荐 SubAgent"""

import json
from typing import Any, Dict, List, Optional
from pathlib import Path

import yaml

from ..base import BaseSubAgent, SubAgentContext, SubAgentResult, AgentStep


class CounterPickSubAgent(BaseSubAgent):
    """英雄克制推荐 SubAgent"""
    
    def __init__(self, llm_client, prompt_path: Optional[str] = None, **kwargs):
        super().__init__(
            name="counter_pick",
            version="1.0.0",
            description="根据敌方阵容推荐克制英雄",
            max_steps=8,
            **kwargs,
        )
        self.llm_client = llm_client
        self.prompt_path = prompt_path or str(
            Path(__file__).parent / "prompts.yaml"
        )
        self._prompts = self._load_prompts()
        self._matchup_data: Dict[str, Any] = {}
        
        # 注册工具
        from .tools import fetch_hero_matchups, fetch_hero_synergies
        self.register_tool("fetch_hero_matchups", fetch_hero_matchups, "获取英雄对局数据")
        self.register_tool("fetch_hero_synergies", fetch_hero_synergies, "获取英雄协同数据")
    
    def _load_prompts(self) -> Dict[str, Any]:
        with open(self.prompt_path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    
    async def think(
        self,
        input_data: Dict[str, Any],
        context: SubAgentContext,
        history: List[AgentStep],
    ) -> Dict[str, Any]:
        enemy_heroes = input_data.get("enemy_heroes", [])
        
        # 构造 prompt
        template = self._prompts['counter_pick_think']['template']
        prompt = template.format(
            enemy_heroes="、".join(enemy_heroes),
            matchup_data=json.dumps(self._matchup_data, ensure_ascii=False),
            history="\n".join([
                f"Step {s.step_number}: {s.thought} → {s.action}"
                for s in history
            ]) or "（无）",
            step_number=len(history) + 1,
        )
        
        response = await self.llm_client.generate(prompt)
        
        try:
            return json.loads(response)
        except json.JSONDecodeError:
            # 解析失败时默认 finish
            return {
                "thought": "Parse error, finishing",
                "action": "finish",
                "action_input": {"recommendations": []},
            }
    
    async def _fallback(
        self,
        input_data: Dict[str, Any],
        context: Optional[SubAgentContext] = None,
        error: Optional[Exception] = None,
    ) -> SubAgentResult:
        """降级方案：基于规则简单返回"""
        enemy_heroes = input_data.get("enemy_heroes", [])
        return SubAgentResult(
            success=True,
            data={
                "recommendations": [
                    {"hero": "推荐英雄待补充", "reason": "分析暂不可用，请稍后重试"},
                ],
                "enemy_heroes": enemy_heroes,
            },
            confidence=0.3,
        )
```

- [ ] **Step 4: Create `subagents/counter_pick/__init__.py`**

```python
from .agent import CounterPickSubAgent

__all__ = ['CounterPickSubAgent']
```

#### Task 2.2: 出装推荐 SubAgent

**Files:**
- Create: `subagents/item_recommender/__init__.py`
- Create: `subagents/item_recommender/tools.py`
- Create: `subagents/item_recommender/agent.py`

- [ ] **Step 1: Create `subagents/item_recommender/tools.py`**

```python
"""出装推荐专用工具"""

from typing import Any, Dict, List


async def fetch_hero_items(hero_name: str) -> List[Dict[str, Any]]:
    """获取英雄常用物品"""
    return [
        {"name": "相位靴", "category": "鞋子", "win_rate": 0.62},
        {"name": "黑皇杖", "category": "核心", "win_rate": 0.71},
    ]


async def fetch_counter_items(enemy_heroes: List[str]) -> List[Dict[str, Any]]:
    """获取针对敌方阵容的物品"""
    return [
        {"name": "天堂之杖", "counter": "敌方有沉默/缴械时", "priority": "high"},
    ]


async def fetch_item_synergies(hero_name: str) -> List[Dict[str, Any]]:
    """获取物品协同"""
    return [
        {"items": ["黯灭", "代达罗斯之殇"], "synergy": "暴击流输出"},
    ]
```

- [ ] **Step 2: Create `subagents/item_recommender/agent.py`**

```python
"""出装推荐 SubAgent"""

import json
from typing import Any, Dict, Optional
from pathlib import Path

import yaml

from ..base import BaseSubAgent, SubAgentContext, SubAgentResult, AgentStep


class ItemRecommenderSubAgent(BaseSubAgent):
    """出装推荐 SubAgent"""
    
    def __init__(self, llm_client, prompt_path: Optional[str] = None, **kwargs):
        super().__init__(
            name="item_recommender",
            version="1.0.0",
            description="推荐英雄出装（核心、针对、局势）",
            max_steps=6,
            **kwargs,
        )
        self.llm_client = llm_client
        self.prompt_path = prompt_path or str(
            Path(__file__).parent / "prompts.yaml"
        )
        self._item_data: Dict[str, Any] = {}
        
        from .tools import fetch_hero_items, fetch_counter_items, fetch_item_synergies
        self.register_tool("fetch_hero_items", fetch_hero_items, "获取英雄常用物品")
        self.register_tool("fetch_counter_items", fetch_counter_items, "获取针对敌方物品")
        self.register_tool("fetch_item_synergies", fetch_item_synergies, "获取物品协同")
    
    async def think(
        self,
        input_data: Dict[str, Any],
        context: SubAgentContext,
        history: List[AgentStep],
    ) -> Dict[str, Any]:
        # 简化版：直接调用所有工具后 finish
        hero_name = input_data.get("hero_name", "")
        enemy_heroes = input_data.get("enemy_heroes", [])
        
        if len(history) == 0:
            return {
                "thought": "先查询英雄常用物品",
                "action": "fetch_hero_items",
                "action_input": {"hero_name": hero_name},
            }
        elif len(history) == 1:
            return {
                "thought": "查询针对物品",
                "action": "fetch_counter_items",
                "action_input": {"enemy_heroes": enemy_heroes},
            }
        elif len(history) == 2:
            return {
                "thought": "查询物品协同",
                "action": "fetch_item_synergies",
                "action_input": {"hero_name": hero_name},
            }
        else:
            # 综合所有数据生成推荐
            prompt = f"""基于以下数据生成出装推荐：

## 英雄常用物品
{json.dumps(self._item_data.get('hero_items', []), ensure_ascii=False)}

## 针对敌方物品
{json.dumps(self._item_data.get('counter_items', []), ensure_ascii=False)}

## 物品协同
{json.dumps(self._item_data.get('synergies', []), ensure_ascii=False)}

## 英雄
{hero_name}

## 敌方
{json.dumps(enemy_heroes, ensure_ascii=False)}

请输出 JSON 格式：
{{
  "core_items": ["核心物品"],
  "counter_items": ["针对物品"],
  "situational_items": ["局势物品"]
}}"""
            
            response = await self.llm_client.generate(prompt)
            try:
                return {
                    "thought": "生成最终推荐",
                    "action": "finish",
                    "action_input": json.loads(response),
                }
            except json.JSONDecodeError:
                return {
                    "thought": "Parse error",
                    "action": "finish",
                    "action_input": {
                        "core_items": [],
                        "counter_items": [],
                        "situational_items": [],
                    },
                }
    
    async def _fallback(
        self,
        input_data: Dict[str, Any],
        context: Optional[SubAgentContext] = None,
        error: Optional[Exception] = None,
    ) -> SubAgentResult:
        return SubAgentResult(
            success=True,
            data={
                "core_items": [],
                "counter_items": [],
                "situational_items": [],
                "message": "出装推荐暂不可用",
            },
            confidence=0.3,
        )
```

- [ ] **Step 3: Create `subagents/item_recommender/__init__.py`**

```python
from .agent import ItemRecommenderSubAgent

__all__ = ['ItemRecommenderSubAgent']
```

#### Task 2.3: 技能加点 SubAgent（简化版）

**Files:**
- Create: `subagents/skill_builder/__init__.py`
- Create: `subagents/skill_builder/tools.py`
- Create: `subagents/skill_builder/agent.py`

- [ ] **Step 1: Create `subagents/skill_builder/tools.py`**

```python
"""技能加点专用工具"""

from typing import Any, Dict, List


async def fetch_hero_skills(hero_name: str) -> List[Dict[str, Any]]:
    """获取英雄技能信息"""
    return [
        {"name": "技能1", "priority": 1, "description": "主要输出技能"},
        {"name": "技能2", "priority": 2, "description": "辅助技能"},
    ]


async def fetch_meta_skill_build(hero_name: str) -> List[Dict[str, Any]]:
    """获取当前版本主流加点"""
    return [
        {"level": 1, "skill": "技能1"},
        {"level": 2, "skill": "技能2"},
    ]
```

- [ ] **Step 2: Create `subagents/skill_builder/agent.py`**

```python
"""技能加点推荐 SubAgent"""

import json
from typing import Any, Dict, Optional

from ..base import BaseSubAgent, SubAgentContext, SubAgentResult, AgentStep


class SkillBuilderSubAgent(BaseSubAgent):
    """技能加点 SubAgent"""
    
    def __init__(self, llm_client, **kwargs):
        super().__init__(
            name="skill_builder",
            version="1.0.0",
            description="推荐技能加点顺序和天赋树",
            max_steps=4,
            **kwargs,
        )
        self.llm_client = llm_client
        self._skill_data: Dict[str, Any] = {}
        
        from .tools import fetch_hero_skills, fetch_meta_skill_build
        self.register_tool("fetch_hero_skills", fetch_hero_skills, "获取英雄技能信息")
        self.register_tool("fetch_meta_skill_build", fetch_meta_skill_build, "获取主流加点")
    
    async def think(
        self,
        input_data: Dict[str, Any],
        context: SubAgentContext,
        history: List[AgentStep],
    ) -> Dict[str, Any]:
        hero_name = input_data.get("hero_name", "")
        
        if len(history) == 0:
            return {
                "thought": "查询英雄技能",
                "action": "fetch_hero_skills",
                "action_input": {"hero_name": hero_name},
            }
        elif len(history) == 1:
            return {
                "thought": "查询主流加点",
                "action": "fetch_meta_skill_build",
                "action_input": {"hero_name": hero_name},
            }
        else:
            # 生成最终加点方案
            prompt = f"""基于以下数据生成技能加点方案：

## 英雄技能
{json.dumps(self._skill_data.get('skills', []), ensure_ascii=False)}

## 主流加点
{json.dumps(self._skill_data.get('meta', []), ensure_ascii=False)}

## 当前局势
{input_data.get('situation', 'normal')}

请输出 JSON 格式：
{{
  "skill_order": [
    {{"level": 1, "skill": "技能名"}},
    ...
  ],
  "talent_build": "10/15/20/25级天赋选择",
  "reasoning": "理由说明"
}}"""
            
            response = await self.llm_client.generate(prompt)
            try:
                return {
                    "thought": "生成加点方案",
                    "action": "finish",
                    "action_input": json.loads(response),
                }
            except json.JSONDecodeError:
                return {
                    "thought": "Parse error",
                    "action": "finish",
                    "action_input": {
                        "skill_order": [],
                        "talent_build": "",
                        "reasoning": "解析失败",
                    },
                }
    
    async def _fallback(
        self,
        input_data: Dict[str, Any],
        context: Optional[SubAgentContext] = None,
        error: Optional[Exception] = None,
    ) -> SubAgentResult:
        return SubAgentResult(
            success=True,
            data={
                "skill_order": [],
                "talent_build": "",
                "reasoning": "技能加点推荐暂不可用",
            },
            confidence=0.3,
        )
```

#### Task 2.4: 游戏事件提醒 SubAgent（简化版）

**Files:**
- Create: `subagents/event_advisor/__init__.py`
- Create: `subagents/event_advisor/agent.py`

- [ ] **Step 1: Create `subagents/event_advisor/agent.py`**

```python
"""游戏事件提醒 SubAgent

订阅 GSI 事件，自动判断是否需要提醒并生成建议。
"""

import json
from typing import Any, Dict, Optional

from ..base import BaseSubAgent, SubAgentContext, SubAgentResult, AgentStep


class EventAdvisorSubAgent(BaseSubAgent):
    """游戏事件提醒 SubAgent"""
    
    def __init__(self, llm_client, event_detector, **kwargs):
        super().__init__(
            name="event_advisor",
            version="1.0.0",
            description="游戏事件检测和提醒生成",
            max_steps=3,
            **kwargs,
        )
        self.llm_client = llm_client
        self.event_detector = event_detector
        self.register_tool("detect_event", event_detector.detect, "检测游戏事件")
    
    async def think(
        self,
        input_data: Dict[str, Any],
        context: SubAgentContext,
        history: List[AgentStep],
    ) -> Dict[str, Any]:
        if len(history) == 0:
            return {
                "thought": "检测当前游戏事件",
                "action": "detect_event",
                "action_input": {"game_state": input_data.get("game_state", {})},
            }
        else:
            # 基于检测到的事件生成建议
            last_step = history[-1]
            event = last_step.observation
            
            prompt = f"""基于以下游戏事件生成提醒建议：

## 事件
{json.dumps(event, ensure_ascii=False)}

## 当前状态
{json.dumps(input_data.get('game_state', {}), ensure_ascii=False)}

请输出 JSON：
{{
  "should_remind": true/false,
  "reminder_text": "提醒内容（简洁，< 30字）",
  "priority": "high/medium/low",
  "audio_file": "对应语音文件（如果有）"
}}"""
            
            response = await self.llm_client.generate(prompt)
            try:
                return {
                    "thought": "生成提醒",
                    "action": "finish",
                    "action_input": json.loads(response),
                }
            except json.JSONDecodeError:
                return {
                    "thought": "Parse error",
                    "action": "finish",
                    "action_input": {
                        "should_remind": False,
                        "reminder_text": "",
                    },
                }
    
    async def _fallback(
        self,
        input_data: Dict[str, Any],
        context: Optional[SubAgentContext] = None,
        error: Optional[Exception] = None,
    ) -> SubAgentResult:
        return SubAgentResult(
            success=True,
            data={"should_remind": False, "reminder_text": ""},
            confidence=0.3,
        )
```

#### Task 2.5: 主动推荐 SubAgent（简化版）

**Files:**
- Create: `subagents/proactive_recommender/__init__.py`
- Create: `subagents/proactive_recommender/agent.py`

- [ ] **Step 1: Create `subagents/proactive_recommender/agent.py`**

```python
"""主动推荐 SubAgent

根据游戏状态自动判断是否需要推送建议。
"""

from ..base import BaseSubAgent, SubAgentContext, SubAgentResult, AgentStep
from ..event_advisor.agent import EventAdvisorSubAgent


class ProactiveRecommenderSubAgent(BaseSubAgent):
    """主动推荐 SubAgent（复用 EventAdvisor 并增加状态判断）"""
    
    def __init__(self, llm_client, state_manager, **kwargs):
        super().__init__(
            name="proactive_recommender",
            version="1.0.0",
            description="根据游戏状态主动推送建议",
            max_steps=4,
            **kwargs,
        )
        self.llm_client = llm_client
        self.state_manager = state_manager
        self.register_tool("get_game_state", state_manager.get_state, "获取游戏状态")
    
    async def think(
        self,
        input_data: Dict[str, Any],
        context: SubAgentContext,
        history: List[AgentStep],
    ) -> Dict[str, Any]:
        if len(history) == 0:
            return {
                "thought": "获取最新游戏状态",
                "action": "get_game_state",
                "action_input": {},
            }
        else:
            game_state = history[-1].observation
            # 判断是否需要主动推荐
            prompt = f"""基于以下游戏状态判断是否需要主动推送建议：

## 状态
血量：{game_state.get('health_percent', 100)}%
金钱：{game_state.get('gold', 0)}
等级：{game_state.get('level', 1)}
游戏时间：{game_state.get('game_time', 0)}秒

如果血量<30%、金钱达到某装备价格、或有其他紧急情况，需要主动推荐。

请输出 JSON：
{{
  "should_recommend": true/false,
  "recommendation_type": "low_health/buy_item/team_fight/...",
  "message": "建议内容"
}}"""
            
            response = await self.llm_client.generate(prompt)
            import json
            try:
                return {
                    "thought": "判断推荐",
                    "action": "finish",
                    "action_input": json.loads(response),
                }
            except json.JSONDecodeError:
                return {
                    "thought": "Parse error",
                    "action": "finish",
                    "action_input": {"should_recommend": False},
                }
    
    async def _fallback(
        self,
        input_data: Dict[str, Any],
        context: Optional[SubAgentContext] = None,
        error: Optional[Exception] = None,
    ) -> SubAgentResult:
        return SubAgentResult(
            success=True,
            data={"should_recommend": False},
            confidence=0.3,
        )
```

#### Task 2.6: 用户反馈学习 SubAgent（简化版）

**Files:**
- Create: `subagents/feedback_learner/__init__.py`
- Create: `subagents/feedback_learner/agent.py`

- [ ] **Step 1: Create `subagents/feedback_learner/agent.py`**

```python
"""用户反馈学习 SubAgent

收集用户反馈，评估推荐效果，调整策略参数。
"""

import json
from typing import Any, Dict, Optional

from ..base import BaseSubAgent, SubAgentContext, SubAgentResult, AgentStep


class FeedbackLearnerSubAgent(BaseSubAgent):
    """用户反馈学习 SubAgent"""
    
    def __init__(self, llm_client, feedback_store, strategy_params, **kwargs):
        super().__init__(
            name="feedback_learner",
            version="1.0.0",
            description="根据用户反馈学习并调整推荐策略",
            max_steps=5,
            **kwargs,
        )
        self.llm_client = llm_client
        self.feedback_store = feedback_store
        self.strategy_params = strategy_params
        self.register_tool("fetch_feedback", feedback_store.get_recent, "获取近期反馈")
        self.register_tool("update_params", strategy_params.update, "更新策略参数")
    
    async def think(
        self,
        input_data: Dict[str, Any],
        context: SubAgentContext,
        history: List[AgentStep],
    ) -> Dict[str, Any]:
        if len(history) == 0:
            return {
                "thought": "获取近期用户反馈",
                "action": "fetch_feedback",
                "action_input": {"limit": 50},
            }
        else:
            feedback = history[-1].observation
            prompt = f"""基于以下用户反馈数据分析并调整策略：

## 反馈统计
{json.dumps(feedback, ensure_ascii=False)}

## 当前策略参数
{json.dumps(self.strategy_params.get_all(), ensure_ascii=False)}

请分析：
1. 哪些推荐效果好，哪些效果差？
2. 需要调整哪些参数（如推荐阈值、权重）？

请输出 JSON：
{{
  "analysis": "分析结果",
  "param_updates": {{"param_name": new_value}}
}}"""
            
            response = await self.llm_client.generate(prompt)
            try:
                analysis = json.loads(response)
                # 应用参数更新
                param_updates = analysis.get("param_updates", {})
                if param_updates:
                    return {
                        "thought": "更新策略参数",
                        "action": "update_params",
                        "action_input": {"updates": param_updates},
                    }
                else:
                    return {
                        "thought": "无需更新",
                        "action": "finish",
                        "action_input": analysis,
                    }
            except json.JSONDecodeError:
                return {
                    "thought": "Parse error",
                    "action": "finish",
                    "action_input": {"analysis": "解析失败"},
                }
    
    async def _fallback(
        self,
        input_data: Dict[str, Any],
        context: Optional[SubAgentContext] = None,
        error: Optional[Exception] = None,
    ) -> SubAgentResult:
        return SubAgentResult(
            success=True,
            data={"analysis": "反馈学习暂不可用"},
            confidence=0.3,
        )
```

---

### 阶段 3：集成与迁移（第 6 周）

#### Task 3.1: 配置文件

**Files:**
- Create: `config/subagents_config.yaml`

- [ ] **Step 1: Create `config/subagents_config.yaml`**

```yaml
# SubAgent 全局配置
subagents:
  enabled: true
  max_steps: 5
  timeout: 60.0
  fallback_enabled: true
  
  # 各 SubAgent 单独配置
  counter_pick:
    enabled: true
    max_steps: 8
    timeout: 45.0
  
  item_recommender:
    enabled: true
    max_steps: 6
    timeout: 30.0
  
  skill_builder:
    enabled: true
    max_steps: 4
    timeout: 20.0
  
  event_advisor:
    enabled: true
    max_steps: 3
    timeout: 10.0
  
  proactive_recommender:
    enabled: true
    max_steps: 4
    timeout: 15.0
  
  feedback_learner:
    enabled: true
    max_steps: 5
    timeout: 60.0
    trigger_interval: 3600  # 每小时触发一次
```

#### Task 3.2: AgentController 集成

**Files:**
- Modify: `core/agent_controller.py`

- [ ] **Step 1: Modify `core/agent_controller.py`**

在 `AgentController` 中注册 SubAgent：

```python
# 在 AgentController.__init__ 中添加
from subagents import get_orchestrator, SubAgentContext
from subagents.counter_pick import CounterPickSubAgent
from subagents.item_recommender import ItemRecommenderSubAgent
from subagents.skill_builder import SkillBuilderSubAgent
from subagents.event_advisor import EventAdvisorSubAgent
from subagents.proactive_recommender import ProactiveRecommenderSubAgent
from subagents.feedback_learner import FeedbackLearnerSubAgent

class AgentController:
    def __init__(self, ...):
        # ... 现有代码 ...
        self._register_subagents()
    
    def _register_subagents(self):
        """注册所有 SubAgent"""
        orchestrator = get_orchestrator()
        
        orchestrator.register(CounterPickSubAgent(
            llm_client=self.llm_client,
        ))
        orchestrator.register(ItemRecommenderSubAgent(
            llm_client=self.llm_client,
        ))
        orchestrator.register(SkillBuilderSubAgent(
            llm_client=self.llm_client,
        ))
        orchestrator.register(EventAdvisorSubAgent(
            llm_client=self.llm_client,
            event_detector=self.event_detector,
        ))
        orchestrator.register(ProactiveRecommenderSubAgent(
            llm_client=self.llm_client,
            state_manager=self.gsi_state_manager,
        ))
        orchestrator.register(FeedbackLearnerSubAgent(
            llm_client=self.llm_client,
            feedback_store=self.feedback_store,
            strategy_params=self.strategy_params,
        ))
```

#### Task 3.3: API 端点

**Files:**
- Modify: `web/app.py`

- [ ] **Step 1: Add SubAgent API to `web/app.py`**

```python
# 在 web/app.py 中添加

from subagents import get_orchestrator, SubAgentContext

@app.route('/api/subagents', methods=['GET'])
def list_subagents():
    """列出所有已注册的 SubAgent"""
    orchestrator = get_orchestrator()
    return jsonify({
        "subagents": orchestrator.list_all(),
    })

@app.route('/api/subagents/<name>/invoke', methods=['POST'])
def invoke_subagent(name):
    """调用指定 SubAgent"""
    import asyncio
    
    orchestrator = get_orchestrator()
    data = request.json or {}
    input_data = data.get("input")
    context_data = data.get("context", {})
    
    context = SubAgentContext(
        session_id=context_data.get("session_id"),
        user_id=context_data.get("user_id"),
        trace_id=context_data.get("trace_id"),
    )
    
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        result = loop.run_until_complete(
            orchestrator.invoke(name, input_data, context)
        )
        return jsonify(result.to_dict())
    finally:
        loop.close()
```

---

## 分阶段实施计划

| 阶段 | 时间 | 任务 | 验收标准 |
|------|------|------|---------|
| **阶段 1** | 第 1-2 周 | 基础设施搭建（基类、工具执行器、编排器、测试） | 所有基础设施测试通过 |
| **阶段 2.1** | 第 3 周 | 实现英雄克制推荐 SubAgent | 单元测试通过，可查询 OpenDota API |
| **阶段 2.2** | 第 3 周末 | 实现出装推荐 SubAgent | 单元测试通过 |
| **阶段 2.3** | 第 4 周初 | 实现技能加点 SubAgent | 单元测试通过 |
| **阶段 2.4** | 第 4 周中 | 实现游戏事件提醒 SubAgent | 单元测试通过，集成 GSI |
| **阶段 2.5** | 第 4 周末 | 实现主动推荐 SubAgent | 单元测试通过 |
| **阶段 2.6** | 第 5 周 | 实现用户反馈学习 SubAgent | 单元测试通过 |
| **阶段 3** | 第 6 周 | 集成到 AgentController、API 端点、E2E 测试 | 全部 SubAgent 可调用 |
| **阶段 4** | 第 6 周末 | 清理旧代码、文档更新 | 旧实现可移除 |

---

## 关键决策与注意事项

### 设计决策

1. **ReAct 循环**：每个 SubAgent 自主执行 Think → Act → Observe 循环
2. **工具隔离**：每个 SubAgent 拥有自己的工具集，互不干扰
3. **单例编排器**：全局共享 `SubAgentOrchestrator`
4. **降级统一**：每个 SubAgent 必须实现 `_fallback`
5. **最大步数限制**：防止无限循环，默认 5 步

### 风险与缓解

| 风险 | 缓解措施 |
|------|---------|
| SubAgent 执行时间长 | 设置 `max_steps` 和 `timeout` 双重限制 |
| 工具调用失败 | 工具执行器捕获异常，SubAgent 决定下一步 |
| 多 SubAgent 协作复杂 | 主 Agent 只负责编排，不关心内部细节 |
| 迁移过程破坏现有功能 | 渐进式迁移，保留旧实现作为降级方案 |

### 回退方案

- 保留现有功能代码作为降级方案
- 通过配置开关控制是否使用 SubAgent
- 主 Agent 调用 SubAgent 失败时自动回退到旧实现

---

## 验收标准

1. **功能完整性**：6 个 SubAgent 全部实现
2. **测试覆盖**：所有 SubAgent 单元测试通过，覆盖率 > 75%
3. **集成测试**：E2E 测试通过，主 Agent 可通过 SubAgent 完成典型任务
4. **性能指标**：单 SubAgent 执行时间 < 10 秒（含多步推理）
5. **降级有效**：SubAgent 失败时降级方案能返回合理结果
6. **可观测性**：每个 SubAgent 的执行步骤都被记录到 Trace

---

## 与 Skill 的对比

| 维度 | Skill | SubAgent |
|------|-------|----------|
| 复杂度 | 轻量（单次 LLM 调用） | 重（多步推理循环） |
| 工具调用 | 固定工具 | 动态选择工具 |
| 适用场景 | 数据查询+LLM 总结 | 复杂推理+多工具协作 |
| 执行时间 | < 3 秒 | 3-10 秒 |
| 错误处理 | 简单降级 | 复杂循环回退 |

---

> **文档版本**: v1.0
> **创建时间**: 2026-07-06
> **预计完成**: 2026-08-17（第 6 周）
