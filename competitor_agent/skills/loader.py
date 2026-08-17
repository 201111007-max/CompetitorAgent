"""SkillLoader — 两层 skill 注入（设计文档 48，参考 Dota2-Agent `utils/skill_loader.py`）

第一层：short descriptions（`get_descriptions`，供系统提示概览）。
第二层：全文内容（`get`/`get_content`，注入具体 skill 块）。

目录缺省读包内 `skills/`（本文件所在目录）；`SKILLS_DIR` 环境变量可覆盖
（测试/评测注入确定性内容）。文件缺失/解析失败 → `get()` 返回 None，
注入点静默跳过（不影响主流程）。
"""
from __future__ import annotations

import os
import re
from pathlib import Path

_SKILLS_DIR_ENV = "SKILLS_DIR"
_DEFAULT_SKILLS_DIR = Path(__file__).parent


def _skills_dir() -> Path:
    """技能目录：环境变量 SKILLS_DIR 优先，缺省包内 skills/。"""
    override = os.environ.get(_SKILLS_DIR_ENV)
    return Path(override) if override else _DEFAULT_SKILLS_DIR


class SkillLoader:
    """从 skills/*.md（YAML frontmatter + 正文）加载技能，按文件名 stem 索引。"""

    def __init__(self, skills_dir: Path | str | None = None) -> None:
        self.skills_dir = Path(skills_dir) if skills_dir is not None else _skills_dir()
        self.skills: dict[str, dict[str, str | dict[str, str]]] = {}
        self.reload()

    def reload(self) -> None:
        """重读目录下所有 *.md（缺目录/读失败静默跳过）。"""
        self.skills = {}
        if not self.skills_dir.exists():
            return
        for path in sorted(self.skills_dir.glob("*.md")):
            try:
                text = path.read_text(encoding="utf-8")
            except OSError:
                continue
            meta, body = self._parse_frontmatter(text)
            self.skills[path.stem] = {"meta": meta, "body": body}

    @staticmethod
    def _parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
        """解析 markdown frontmatter（与 Dota2-Agent `utils/skill_loader.py` 语义对齐）：

        ---
        key: value
        ---
        body...
        """
        if not text:
            return {}, ""
        normalized = text.replace("\r\n", "\n")
        match = re.match(r"^---\n(.*?)\n---\n?(.*)$", normalized, re.DOTALL)
        if not match:
            return {}, normalized.strip()
        meta_raw = match.group(1).strip()
        body = match.group(2).strip()
        meta: dict[str, str] = {}
        for line in meta_raw.splitlines():
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            meta[key.strip()] = value.strip()
        return meta, body

    def get_descriptions(self) -> str:
        """第一层：全部技能的 name + description 清单。"""
        lines = []
        for name in sorted(self.skills):
            skill = self.skills[name]
            meta_raw = skill.get("meta")
            meta = meta_raw if isinstance(meta_raw, dict) else {}
            desc = str(meta.get("description") or "No description")
            lines.append(f"- {name}: {desc}")
        return "\n".join(lines)

    def get_content(self, name: str) -> str:
        """第二层：包装为 `<skill name="...">body</skill>` 的完整块（未知技能返回可读错误）。"""
        key = (name or "").strip()
        if not key:
            return "Error: Missing required field 'name' for load_skill."
        skill = self.skills.get(key)
        if not skill:
            return f"Error: Unknown skill '{key}'."
        body = str(skill.get("body") or "").strip()
        return f'<skill name="{key}">\n{body}\n</skill>'

    def get(self, name: str) -> str | None:
        """直接取正文（缺失/解析失败 → None，注入点据此静默跳过）。"""
        skill = self.skills.get((name or "").strip())
        if not skill:
            return None
        body = str(skill.get("body") or "").strip()
        return body or None


_loader: SkillLoader | None = None


def get_skill_loader(skills_dir: Path | str | None = None) -> SkillLoader:
    """模块级单例（懒加载 + 缓存）；显式传目录时绕过缓存建新实例（测试用）。"""
    global _loader
    if skills_dir is not None:
        return SkillLoader(skills_dir=skills_dir)
    if _loader is None:
        _loader = SkillLoader()
    return _loader
