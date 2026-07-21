"""提示词加载器"""
from pathlib import Path
from typing import Any, Dict, Optional

import yaml

from post_match_review.observability.logger import get_logger

logger = get_logger("pmr.prompt.loader")


class PromptLoader:
    """提示词加载器
    
    从 YAML 文件加载提示词模板，支持变量替换。
    """

    def __init__(self, prompts_dir: Optional[str] = None) -> None:
        """初始化加载器
        
        Args:
            prompts_dir: 提示词目录路径，默认为项目内的 prompts 目录
        """
        if prompts_dir:
            self._prompts_dir = Path(prompts_dir)
        else:
            # 默认使用 post_match_review/prompts 目录
            self._prompts_dir = Path(__file__).parent.parent / "prompts"
        
        self._cache: Dict[str, Dict[str, Any]] = {}
        logger.info(f"PromptLoader 初始化: prompts_dir={self._prompts_dir}")

    def load(self, template_name: str) -> Dict[str, Any]:
        """加载提示词模板
        
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
        if template_name in self._cache:
            cached_time = self._cache[template_name].get("_loaded_at", 0)
            file_mtime = yaml_path.stat().st_mtime
            if cached_time >= file_mtime:
                return self._cache[template_name]
        
        try:
            with open(yaml_path, "r", encoding="utf-8") as f:
                template = yaml.safe_load(f)
            
            # 记录加载时间用于缓存失效判断
            template["_loaded_at"] = yaml_path.stat().st_mtime
            self._cache[template_name] = template
            logger.info(f"提示词模板加载成功: {template_name}")
            return template
            
        except Exception as e:
            logger.error(f"加载提示词模板失败: {template_name}, error={e}")
            return {}

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


# 全局单例
_loader: Optional[PromptLoader] = None


def get_prompt_loader() -> PromptLoader:
    """获取全局提示词加载器实例"""
    global _loader
    if _loader is None:
        _loader = PromptLoader()
    return _loader
