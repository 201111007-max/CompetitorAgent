"""竞品实体定义"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Competitor:
    """竞品（唯一键 = name，小写+连字符规范名）"""

    name: str
    aliases: list[str] = field(default_factory=list)
    category: str = "ai_coding_agent"
    official_links: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", self.name.strip().lower().replace(" ", "-"))


@dataclass(frozen=True)
class CompetitorProfile:
    """竞品画像（含注册来源，用于记忆/知识库索引）"""

    competitor: Competitor
    description: str = ""
    registry_source: str = "user"  # user / registry / discovered
