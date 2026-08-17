"""skills 包（设计文档 48）：写死代码知识型规则 → skill 文档注入 LLM

导出 SkillLoader / get_skill_loader（单例）；9 个 skill md 与 loader.py 同目录。
"""
from competitor_agent.skills.loader import SkillLoader, get_skill_loader

__all__ = ["SkillLoader", "get_skill_loader"]
