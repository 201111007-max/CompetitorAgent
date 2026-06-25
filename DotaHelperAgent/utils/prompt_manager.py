"""Prompt 管理器模块

统一管理所有 LLM Prompt 模板，支持：
- 多策略后端（Langfuse / 本地 YAML）
- 自动降级（Langfuse 不可用时回退到本地）
- 内存缓存（减少 API 调用）
- 变量替换（模板渲染）
"""

from typing import Dict, Any, Optional, List
import time
import logging

from utils.prompt_strategy import PromptStrategy, PromptTemplate, LocalYAMLPromptStrategy

logger = logging.getLogger(__name__)


class PromptNotFoundError(Exception):
    """Prompt 未找到异常"""
    pass


class PromptManager:
    """Prompt 管理器 - 统一管理所有 LLM Prompt 模板

    支持：
    - 多策略后端（Langfuse / 本地 YAML）
    - 自动降级（Langfuse 不可用时回退到本地）
    - 内存缓存（减少 API 调用）
    - 变量替换（模板渲染）
    """

    def __init__(
        self,
        primary_strategy: Optional[PromptStrategy] = None,
        fallback_strategy: Optional[PromptStrategy] = None,
        cache_ttl: int = 300,
    ):
        """初始化 Prompt 管理器
        
        Args:
            primary_strategy: 主策略（如 Langfuse）
            fallback_strategy: 降级策略（如本地 YAML）
            cache_ttl: 缓存过期时间（秒）
        """
        self._primary = primary_strategy
        self._fallback = fallback_strategy or LocalYAMLPromptStrategy()
        self._cache_ttl = cache_ttl
        self._cache: Dict[str, tuple] = {}  # key -> (PromptTemplate, timestamp)

    def get_prompt(
        self,
        name: str,
        version: Optional[int] = None,
        variables: Optional[Dict[str, Any]] = None,
    ) -> str:
        """获取 Prompt 内容，支持变量替换

        Args:
            name: Prompt 名称（如 "hero_recommendation"）
            version: 版本号（None 表示最新版本）
            variables: 模板变量字典

        Returns:
            渲染后的 Prompt 字符串
        """
        template = self._get_template(name, version)
        content = template.content

        if variables:
            for key, value in variables.items():
                content = content.replace(f"{{{{{key}}}}}", str(value))

        return content

    def _get_template(self, name: str, version: Optional[int] = None) -> PromptTemplate:
        """获取 Prompt 模板（带缓存）
        
        Args:
            name: Prompt 名称
            version: 版本号
            
        Returns:
            Prompt 模板
            
        Raises:
            PromptNotFoundError: 当 Prompt 在所有策略中都未找到时
        """
        cache_key = f"{name}:{version or 'latest'}"

        # 检查缓存
        if cache_key in self._cache:
            template, timestamp = self._cache[cache_key]
            if time.time() - timestamp < self._cache_ttl:
                return template

        # 尝试主策略
        template = None
        if self._primary:
            try:
                template = self._primary.get_prompt(name, version)
                if template:
                    logger.debug(f"从主策略获取 Prompt '{name}' 成功")
            except Exception as e:
                logger.warning(f"主策略获取 Prompt '{name}' 失败: {e}")

        # 降级到备用策略
        if template is None:
            try:
                template = self._fallback.get_prompt(name, version)
                if template:
                    logger.debug(f"从降级策略获取 Prompt '{name}' 成功")
            except Exception as e:
                logger.warning(f"降级策略获取 Prompt '{name}' 失败: {e}")

        if template is None:
            raise PromptNotFoundError(f"Prompt '{name}' (version={version or 'latest'}) 在所有策略中都未找到")

        # 更新缓存
        self._cache[cache_key] = (template, time.time())
        return template

    def list_prompts(self) -> List[str]:
        """列出所有可用的 Prompt 名称
        
        Returns:
            Prompt 名称列表
        """
        names = set()
        if self._primary:
            try:
                names.update(self._primary.list_prompts())
            except Exception:
                pass
        try:
            names.update(self._fallback.list_prompts())
        except Exception:
            pass
        return sorted(names)

    def get_prompt_metadata(self, name: str, version: Optional[int] = None) -> Dict[str, Any]:
        """获取 Prompt 元数据
        
        Args:
            name: Prompt 名称
            version: 版本号
            
        Returns:
            元数据字典
        """
        template = self._get_template(name, version)
        return {
            "name": template.name,
            "version": template.version,
            "variables": template.variables,
            "metadata": template.metadata
        }

    def invalidate_cache(self, name: Optional[str] = None) -> None:
        """清除缓存
        
        Args:
            name: Prompt 名称（None 表示清除所有缓存）
        """
        if name:
            keys_to_remove = [k for k in self._cache if k.startswith(f"{name}:")]
            for k in keys_to_remove:
                del self._cache[k]
            logger.debug(f"已清除 Prompt '{name}' 的缓存")
        else:
            self._cache.clear()
            logger.debug("已清除所有 Prompt 缓存")

    def get_cache_stats(self) -> Dict[str, Any]:
        """获取缓存统计信息
        
        Returns:
            缓存统计字典
        """
        return {
            "cache_size": len(self._cache),
            "cache_ttl": self._cache_ttl,
            "cached_prompts": list(self._cache.keys())
        }
