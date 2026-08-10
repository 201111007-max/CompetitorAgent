"""BaseAgent — 多 Agent 协作的基类与共享类型

为 team/ 下各 Agent 提供统一的生命周期与决策语义：
- AgentContext：一次分析任务的共享上下文（任务/竞品/缺口/预算/会话）
- AgentResult：Agent 产出物 + 状态（SUCCESS/RETRY/DEGRADED/FAILED）+ 决策理由
- BaseAgent：抽象基类，强制 run(ctx) 决策入口
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from competitor_agent.domain_types.strategy import CompetitorStrategy
from competitor_agent.interfaces.memory import IFourLayerMemory
from competitor_agent.team.message_bus import MessageBus

logger = logging.getLogger("competitor_agent.team.base_agent")


class AgentStatus(str, Enum):
    """Agent 决策结果状态"""

    SUCCESS = "success"      # 正常完成
    RETRY = "retry"          # 需要重试（可恢复失败）
    DEGRADED = "degraded"    # 降级完成（部分数据缺失）
    FAILED = "failed"        # 不可恢复失败


@dataclass
class AgentContext:
    """一次分析任务的共享上下文"""

    task: str
    strategy: CompetitorStrategy
    session_id: str = ""
    max_retries: int = 1
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentResult:
    """Agent 产出物 + 决策状态"""

    status: AgentStatus
    payload: Any = None
    reason: str = ""
    retries: int = 0

    @property
    def ok(self) -> bool:
        return self.status in (AgentStatus.SUCCESS, AgentStatus.DEGRADED)


class BaseAgent(ABC):
    """多 Agent 基类：注入总线与记忆，提供统一决策入口"""

    def __init__(
        self,
        name: str,
        bus: MessageBus,
        memory: IFourLayerMemory | None = None,
    ) -> None:
        self.name = name
        self._bus = bus
        self._memory = memory

    @abstractmethod
    def run(self, ctx: AgentContext) -> AgentResult:
        """执行 Agent 决策，返回带状态的 AgentResult。"""
        ...

    def _retry(self, ctx: AgentContext, exc: Exception) -> AgentResult:
        """统一的重试/降级决策：可重试则 RETRY，否则 FAILED。"""
        if ctx.max_retries > 0:
            ctx.max_retries -= 1
            logger.warning("[%s] 可重试失败，剩余 %d 次: %s", self.name, ctx.max_retries, exc)
            return AgentResult(status=AgentStatus.RETRY, reason=str(exc))
        logger.error("[%s] 不可恢复失败: %s", self.name, exc)
        return AgentResult(status=AgentStatus.FAILED, reason=str(exc))


__all__ = [
    "AgentContext",
    "AgentResult",
    "AgentStatus",
    "BaseAgent",
]
