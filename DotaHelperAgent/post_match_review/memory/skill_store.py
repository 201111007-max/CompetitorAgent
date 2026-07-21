"""技能沉淀模块 - Level 3 记忆层"""
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from post_match_review.interfaces.skill import ISkillStore
from post_match_review.observability.logger import get_logger

logger = get_logger("pmr.memory.skill_store")


class SkillStore(ISkillStore):
    """Level 3: 技能沉淀（SKILL.md）"""

    def __init__(self, skills_dir: str) -> None:
        self._skills_dir = Path(skills_dir)
        self._skills_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"SkillStore 初始化完成: {self._skills_dir}")

    def save_skill(
        self,
        name: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """保存或更新技能"""
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
        """加载指定技能"""
        skill_path = self._skills_dir / f"{name}.md"
        if not skill_path.exists():
            return None
        return self._parse_skill_file(skill_path)

    def list_skills(self) -> List[Dict[str, Any]]:
        """列出所有技能"""
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

    def _parse_skill_file(self, skill_path: Path) -> Optional[Dict[str, Any]]:
        """解析技能文件
        
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
