"""战略规划器契约"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from competitor_agent.domain_types.strategy import CompetitorStrategy
from competitor_agent.interfaces.memory import IFourLayerMemory


@runtime_checkable
class IStrategicPlanner(Protocol):
    """把用户任务解析为信息缺口清单与预算分配"""

    def plan(self, task: str, memory: IFourLayerMemory) -> CompetitorStrategy:
        """产出：竞品识别 + InfoGap 清单（优先级/初始置信度）+ 维度预算 + 终止阈值。

        异常约定：
        - TaskNotSupportedError: 无法识别目标竞品，要求澄清
        """
        ...


__all__ = ["IStrategicPlanner"]
