"""技能存储接口定义

ISkillStore: 经验技能存储接口（Markdown 格式）
IAnalysisSkillStore: 分析技能存储接口（YAML 格式）
"""
from typing import Any, Dict, List, Optional, Protocol


class ISkillStore(Protocol):
    """经验技能存储接口（Markdown 格式）"""

    def save_skill(
        self,
        name: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """保存或更新经验技能"""
        ...

    def load_skill(self, name: str) -> Optional[Dict[str, Any]]:
        """加载指定经验技能"""
        ...

    def list_skills(self) -> List[Dict[str, Any]]:
        """列出所有经验技能"""
        ...

    def check_conflict(
        self,
        name: str,
        content: str,
    ) -> Optional[Dict[str, Any]]:
        """检查与已有技能是否冲突"""
        ...


class IAnalysisSkillStore(Protocol):
    """分析技能存储接口（YAML 格式）

    分析技能以纯 YAML 文件存储，包含分析框架、数据需求、
    输出 Schema 等完整定义，供 SkillDrivenAnalyzer 使用。
    """

    def save_analysis_skill(
        self,
        name: str,
        skill_definition: Dict[str, Any],
    ) -> None:
        """保存分析技能定义

        Args:
            name: 技能名称
            skill_definition: 完整的 YAML 技能定义字典
        """
        ...

    def load_analysis_skill(self, name: str) -> Optional[Dict[str, Any]]:
        """加载分析技能定义

        Args:
            name: 技能名称

        Returns:
            Optional[Dict[str, Any]]: 技能定义字典，不存在时返回 None
        """
        ...

    def list_analysis_skills(self) -> List[Dict[str, Any]]:
        """列出所有分析技能

        Returns:
            List[Dict[str, Any]]: 分析技能定义列表
        """
        ...
