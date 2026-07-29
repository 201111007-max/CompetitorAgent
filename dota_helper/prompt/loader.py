"""统一提示词模板加载器

提供 mtime 自动失效缓存，支持所有 YAML 模板的统一加载和渲染。
作为项目唯一的模板加载入口，PromptBuilder 委托此加载器而非内置加载。
"""
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from dota_helper.observability.logger import get_logger

logger = get_logger("prompt.loader")


class PromptLoader:
    """统一提示词模板加载器

    从 YAML 文件加载提示词模板，支持变量替换和 mtime 自动失效缓存。
    所有组件（PromptBuilder/DreamRecap/BackgroundReviewer）统一使用此加载器。
    """

    def __init__(self, prompts_dir: Optional[str] = None) -> None:
        """初始化加载器

        Args:
            prompts_dir: 提示词目录路径，默认为项目内的 prompts 目录
        """
        if prompts_dir:
            self._prompts_dir = Path(prompts_dir)
        else:
            # 默认使用 dota_helper/prompts 目录
            self._prompts_dir = Path(__file__).parent.parent / "prompts"

        # 缓存: {template_name: (content_dict, loaded_mtime)}
        self._cache: Dict[str, tuple] = {}
        logger.info(f"PromptLoader 初始化: prompts_dir={self._prompts_dir}")

    def load(self, template_name: str) -> Dict[str, Any]:
        """加载提示词模板（带 mtime 自动失效缓存）

        Args:
            template_name: 模板名称（不含 .yaml 后缀）

        Returns:
            Dict[str, Any]: 模板内容
        """
        yaml_path = self._prompts_dir / f"{template_name}.yaml"

        if not yaml_path.exists():
            logger.warning(f"提示词模板不存在: {yaml_path}")
            return {}

        # 检查缓存和文件修改时间
        file_mtime = yaml_path.stat().st_mtime
        if template_name in self._cache:
            cached_content, cached_mtime = self._cache[template_name]
            if cached_mtime >= file_mtime:
                return cached_content

        try:
            with open(yaml_path, "r", encoding="utf-8") as f:
                template = yaml.safe_load(f)

            self._cache[template_name] = (template, file_mtime)
            logger.debug(f"提示词模板加载成功: {template_name}")
            return template

        except Exception as e:
            logger.error(f"加载提示词模板失败: {template_name}, error={e}")
            return {}

    def load_tactical(self, phase: str) -> Dict[str, Any]:
        """加载战术阶段模板

        PromptBuilder 委托此方法加载 tactical_{phase}.yaml 模板，
        消除内置加载逻辑，统一缓存策略。

        Args:
            phase: 分析阶段名称（如 laning, teamfight）

        Returns:
            Dict[str, Any]: 模板内容
        """
        return self.load(f"tactical_{phase}")

    def render(
        self,
        template_name: str,
        section: str,
        **kwargs: Any,
    ) -> str:
        """渲染提示词模板

        Args:
            template_name: 模板名称
            section: 模板中的部分名称（如 'system', 'user'）
            **kwargs: 用于替换模板中的变量

        Returns:
            str: 渲染后的提示词
        """
        template = self.load(template_name)

        if not template:
            logger.warning(f"模板为空，返回空字符串: {template_name}")
            return ""

        # 获取指定部分
        content = template.get(section, "")

        if not content:
            logger.warning(f"模板部分不存在: {template_name}.{section}")
            return ""

        # 变量替换
        try:
            rendered = content.format(**kwargs)
            return rendered
        except KeyError as e:
            logger.error(f"模板变量缺失: {template_name}.{section}, missing={e}")
            return content
        except Exception as e:
            logger.error(f"渲染模板失败: {template_name}.{section}, error={e}")
            return content

    def get_mtime(self, template_name: str) -> float:
        """获取模板文件修改时间

        Args:
            template_name: 模板名称

        Returns:
            float: 文件修改时间戳，不存在返回 0.0
        """
        yaml_path = self._prompts_dir / f"{template_name}.yaml"
        if yaml_path.exists():
            return yaml_path.stat().st_mtime
        return 0.0

    def invalidate(self, template_name: Optional[str] = None) -> None:
        """手动失效缓存

        Args:
            template_name: 指定模板名称（None 则清除全部缓存）
        """
        if template_name is None:
            self._cache.clear()
            logger.debug("已清除所有模板缓存")
        elif template_name in self._cache:
            del self._cache[template_name]
            logger.debug(f"已清除模板缓存: {template_name}")

    def list_templates(self) -> List[str]:
        """列出所有可用模板

        Returns:
            List[str]: 模板名称列表（不含 .yaml 后缀）
        """
        templates = []
        for yaml_path in self._prompts_dir.glob("*.yaml"):
            templates.append(yaml_path.stem)
        return sorted(templates)


# 全局单例
_loader: Optional[PromptLoader] = None


def get_prompt_loader() -> PromptLoader:
    """获取全局提示词加载器实例

    Returns:
        PromptLoader: 全局单例
    """
    global _loader
    if _loader is None:
        _loader = PromptLoader()
    return _loader
