"""技能沉淀模块 - Level 3 记忆层

同时管理经验技能（.md + YAML frontmatter）和分析技能（.yaml）。
经验技能用于存储复盘沉淀的知识，分析技能用于定义可扩展的分析维度。
"""
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from post_match_review.interfaces.skill import ISkillStore, IAnalysisSkillStore
from post_match_review.observability.logger import get_logger

logger = get_logger("pmr.memory.skill_store")


class SkillStore(ISkillStore, IAnalysisSkillStore):
    """Level 3: 技能沉淀（SKILL.md + 分析技能 YAML）

    双协议实现：
    - ISkillStore: 经验技能管理（.md + YAML frontmatter）
    - IAnalysisSkillStore: 分析技能管理（.yaml）

    目录结构：
        {skills_dir}/
        ├── *.md           # 经验技能（Markdown + YAML frontmatter）
        └── analysis/      # 分析技能子目录
            └── *.yaml     # 用户自定义分析技能
    """

    def __init__(self, skills_dir: str) -> None:
        self._skills_dir = Path(skills_dir)
        self._skills_dir.mkdir(parents=True, exist_ok=True)
        self._analysis_skills_dir = self._skills_dir / "analysis"
        self._analysis_skills_dir.mkdir(parents=True, exist_ok=True)
        logger.info(
            "SkillStore 初始化完成: skills_dir=%s, analysis_dir=%s",
            self._skills_dir, self._analysis_skills_dir,
        )

    # ── 经验技能方法（ISkillStore 协议）──

    def save_skill(
        self,
        name: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """保存或更新经验技能"""
        skill_path = self._skills_dir / f"{name}.md"
        metadata = metadata or {}

        if skill_path.exists():
            existing = self._parse_skill_file(skill_path)
            if existing:
                metadata["version"] = existing.get("version", 0) + 1
                metadata["updated_at"] = datetime.now().strftime("%Y-%m-%d")
                if "created_at" not in metadata:
                    metadata["created_at"] = existing.get("created_at", datetime.now().strftime("%Y-%m-%d"))
            else:
                metadata["version"] = 1
                metadata["created_at"] = datetime.now().strftime("%Y-%m-%d")
                metadata["updated_at"] = datetime.now().strftime("%Y-%m-%d")
        else:
            metadata["version"] = 1
            metadata["created_at"] = datetime.now().strftime("%Y-%m-%d")
            metadata["updated_at"] = datetime.now().strftime("%Y-%m-%d")

        metadata["name"] = name
        frontmatter = yaml.dump(metadata, allow_unicode=True, default_flow_style=False)
        full_content = f"---\n{frontmatter}---\n\n{content}"

        skill_path.write_text(full_content, encoding="utf-8")
        logger.info(f"技能保存完成: {name} (version={metadata['version']})")

    def load_skill(self, name: str) -> Optional[Dict[str, Any]]:
        """加载指定经验技能"""
        skill_path = self._skills_dir / f"{name}.md"
        if not skill_path.exists():
            return None
        return self._parse_skill_file(skill_path)

    def list_skills(self) -> List[Dict[str, Any]]:
        """列出所有经验技能"""
        skills = []
        for skill_file in self._skills_dir.glob("*.md"):
            skill = self._parse_skill_file(skill_file)
            if skill:
                skills.append(skill)
        return skills

    def check_conflict(
        self,
        name: str,
        content: str,
    ) -> Optional[Dict[str, Any]]:
        """检查与已有技能是否冲突"""
        existing = self.load_skill(name)
        if not existing:
            return None

        existing_content = existing.get("content", "")
        similarity = self._calculate_similarity(existing_content, content)

        if similarity > 0.7:
            return {
                "conflict": True,
                "similarity": similarity,
                "existing_version": existing.get("version", 1),
                "recommendation": "update",
            }
        elif similarity > 0.3:
            return {
                "conflict": True,
                "similarity": similarity,
                "existing_version": existing.get("version", 1),
                "recommendation": "merge",
            }
        return None

    # ── 分析技能方法（IAnalysisSkillStore 协议）──

    def save_analysis_skill(
        self,
        name: str,
        skill_definition: Dict[str, Any],
    ) -> None:
        """保存分析技能定义为 YAML 文件

        Args:
            name: 技能名称（不含扩展名）
            skill_definition: 完整的 YAML 技能定义字典
        """
        skill_path = self._analysis_skills_dir / f"{name}.yaml"
        with open(skill_path, "w", encoding="utf-8") as f:
            yaml.dump(skill_definition, f, allow_unicode=True, default_flow_style=False)
        logger.info("分析技能保存完成: %s", name)

    def load_analysis_skill(self, name: str) -> Optional[Dict[str, Any]]:
        """加载分析技能定义

        Args:
            name: 技能名称（不含扩展名）

        Returns:
            Optional[Dict[str, Any]]: 技能定义字典，不存在时返回 None
        """
        skill_path = self._analysis_skills_dir / f"{name}.yaml"
        if not skill_path.exists():
            return None
        try:
            with open(skill_path, "r", encoding="utf-8") as f:
                definition = yaml.safe_load(f)
            if definition:
                definition["_file_path"] = str(skill_path)
                definition["_file_name"] = skill_path.stem
                definition["_source"] = "custom"
            return definition
        except Exception as e:
            logger.error("加载分析技能失败: %s, error=%s", name, e)
            return None

    def list_analysis_skills(self) -> List[Dict[str, Any]]:
        """列出所有用户自定义分析技能

        Returns:
            List[Dict[str, Any]]: 分析技能定义列表
        """
        skills: List[Dict[str, Any]] = []
        for skill_file in self._analysis_skills_dir.glob("*.yaml"):
            try:
                with open(skill_file, "r", encoding="utf-8") as f:
                    definition = yaml.safe_load(f)
                if definition:
                    definition["_file_path"] = str(skill_file)
                    definition["_file_name"] = skill_file.stem
                    definition["_source"] = "custom"
                    skills.append(definition)
            except Exception as e:
                logger.error("解析分析技能文件失败: %s, error=%s", skill_file, e)
        return skills

    # ── 内置分析技能方法（prompts/skills/ 目录）──

    def load_builtin_skill(self, name: str) -> Optional[Dict[str, Any]]:
        """从 prompts/skills/ 目录加载内置分析技能

        Args:
            name: 技能名称（不含扩展名）

        Returns:
            Optional[Dict[str, Any]]: 技能定义字典，不存在时返回 None
        """
        prompts_skills_dir = Path(__file__).parent.parent / "prompts" / "skills"
        skill_path = prompts_skills_dir / f"{name}.yaml"
        if not skill_path.exists():
            return None
        try:
            with open(skill_path, "r", encoding="utf-8") as f:
                definition = yaml.safe_load(f)
            if definition:
                definition["_file_path"] = str(skill_path)
                definition["_file_name"] = skill_path.stem
                definition["_source"] = "builtin"
            return definition
        except Exception as e:
            logger.error("加载内置分析技能失败: %s, error=%s", name, e)
            return None

    def list_builtin_skills(self) -> List[Dict[str, Any]]:
        """列出内置分析技能（prompts/skills/ 目录）

        Returns:
            List[Dict[str, Any]]: 内置分析技能定义列表
        """
        prompts_skills_dir = Path(__file__).parent.parent / "prompts" / "skills"
        if not prompts_skills_dir.exists():
            return []
        skills: List[Dict[str, Any]] = []
        for skill_file in prompts_skills_dir.glob("*.yaml"):
            try:
                with open(skill_file, "r", encoding="utf-8") as f:
                    definition = yaml.safe_load(f)
                if definition:
                    definition["_file_path"] = str(skill_file)
                    definition["_file_name"] = skill_file.stem
                    definition["_source"] = "builtin"
                    skills.append(definition)
            except Exception as e:
                logger.error("解析内置分析技能失败: %s, error=%s", skill_file, e)
        return skills

    # ── 私有辅助方法 ──

    def _parse_skill_file(self, skill_path: Path) -> Optional[Dict[str, Any]]:
        """解析经验技能文件（Markdown + YAML frontmatter）
        
        支持灵活的 frontmatter 格式，兼容不同的换行符和空行数量。
        """
        try:
            content = skill_path.read_text(encoding="utf-8")
            # 放宽正则：支持 \r\n 和灵活的空行数量
            match = re.match(r"^---\s*\n(.*?)\n---\s*\n+(.*)$", content, re.DOTALL)
            if not match:
                return None

            frontmatter = yaml.safe_load(match.group(1))
            body = match.group(2)

            return {
                **frontmatter,
                "content": body,
                "file_path": str(skill_path),
            }
        except Exception as e:
            logger.error(f"解析技能文件失败: {skill_path}, error={e}")
            return None

    def _calculate_similarity(self, text1: str, text2: str) -> float:
        """计算文本相似度（简单Jaccard相似度）"""
        words1 = set(text1.lower().split())
        words2 = set(text2.lower().split())

        if not words1 or not words2:
            return 0.0

        intersection = words1 & words2
        union = words1 | words2

        return len(intersection) / len(union)
