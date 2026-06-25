"""Prompt 存储策略模块

实现 Prompt 的存储和获取策略，支持：
- Langfuse 远程存储（主策略）
- 本地 YAML 文件存储（降级策略）
"""

from typing import Dict, Any, Optional, List
from dataclasses import dataclass
from pathlib import Path
import yaml
import logging

logger = logging.getLogger(__name__)


@dataclass
class PromptTemplate:
    """Prompt 模板"""
    name: str
    content: str
    version: int
    variables: List[str]       # 模板变量列表
    metadata: Dict[str, Any]   # 元数据（作者、描述、标签等）


class PromptStrategy:
    """Prompt 存储策略接口"""

    def get_prompt(
        self, name: str, version: Optional[int] = None
    ) -> Optional[PromptTemplate]:
        """获取指定名称和版本的 Prompt"""
        raise NotImplementedError

    def list_prompts(self) -> List[str]:
        """列出所有可用的 Prompt 名称"""
        raise NotImplementedError

    def create_prompt(
        self, name: str, content: str, metadata: Optional[Dict] = None
    ) -> PromptTemplate:
        """创建新版本的 Prompt"""
        raise NotImplementedError


class LangfusePromptStrategy(PromptStrategy):
    """基于 Langfuse 的 Prompt 存储策略"""

    def __init__(self, langfuse_client):
        """初始化 Langfuse 策略
        
        Args:
            langfuse_client: Langfuse 客户端实例
        """
        self.client = langfuse_client

    def get_prompt(self, name: str, version: Optional[int] = None) -> Optional[PromptTemplate]:
        """从 Langfuse 获取 Prompt"""
        try:
            # Langfuse API 调用
            if version:
                prompt = self.client.get_prompt(name, version=version)
            else:
                prompt = self.client.get_prompt(name)
            
            if not prompt:
                return None
            
            # 转换为 PromptTemplate
            return PromptTemplate(
                name=name,
                content=prompt.prompt if hasattr(prompt, 'prompt') else str(prompt),
                version=version or 1,
                variables=[],  # Langfuse 不直接提供变量列表
                metadata={"source": "langfuse"}
            )
        except Exception as e:
            logger.warning(f"从 Langfuse 获取 Prompt '{name}' 失败: {e}")
            return None

    def list_prompts(self) -> List[str]:
        """列出 Langfuse 中的所有 Prompt"""
        try:
            # Langfuse 可能没有列出所有 Prompt 的 API
            # 这里返回空列表，实际使用时依赖本地配置
            return []
        except Exception as e:
            logger.warning(f"列出 Langfuse Prompts 失败: {e}")
            return []

    def create_prompt(self, name: str, content: str, metadata: Optional[Dict] = None) -> PromptTemplate:
        """在 Langfuse 中创建新版本"""
        try:
            # Langfuse API 调用创建 Prompt
            prompt = self.client.create_prompt(
                name=name,
                prompt=content,
                labels=metadata.get("labels", []) if metadata else []
            )
            
            return PromptTemplate(
                name=name,
                content=content,
                version=1,  # Langfuse 会自动管理版本
                variables=[],
                metadata=metadata or {}
            )
        except Exception as e:
            logger.error(f"在 Langfuse 中创建 Prompt '{name}' 失败: {e}")
            raise


class LocalYAMLPromptStrategy(PromptStrategy):
    """基于本地 YAML 文件的 Prompt 存储策略（降级方案）"""

    def __init__(self, prompts_dir: str = "config/prompts"):
        """初始化本地 YAML 策略
        
        Args:
            prompts_dir: Prompt 配置文件目录
        """
        self.prompts_dir = Path(prompts_dir)
        self._cache: Dict[str, Dict[int, PromptTemplate]] = {}
        self._load_all()

    def _load_all(self) -> None:
        """加载所有 YAML 配置文件"""
        if not self.prompts_dir.exists():
            logger.warning(f"Prompt 配置目录不存在: {self.prompts_dir}")
            return
        
        for yaml_file in self.prompts_dir.glob("*.yaml"):
            try:
                with open(yaml_file, 'r', encoding='utf-8') as f:
                    data = yaml.safe_load(f)
                
                if not data or 'prompts' not in data:
                    continue
                
                for prompt_name, prompt_data in data['prompts'].items():
                    template = PromptTemplate(
                        name=prompt_name,
                        content=prompt_data.get('content', ''),
                        version=prompt_data.get('version', 1),
                        variables=prompt_data.get('variables', []),
                        metadata=prompt_data.get('metadata', {})
                    )
                    
                    if prompt_name not in self._cache:
                        self._cache[prompt_name] = {}
                    
                    self._cache[prompt_name][template.version] = template
                    
                logger.info(f"加载 Prompt 配置文件: {yaml_file.name}")
            except Exception as e:
                logger.error(f"加载 Prompt 配置文件 {yaml_file} 失败: {e}")

    def get_prompt(self, name: str, version: Optional[int] = None) -> Optional[PromptTemplate]:
        """从本地缓存中获取 Prompt"""
        if name not in self._cache:
            return None
        
        versions = self._cache[name]
        
        if version is None:
            # 返回最新版本
            return max(versions.values(), key=lambda t: t.version)
        else:
            return versions.get(version)

    def list_prompts(self) -> List[str]:
        """返回所有已加载的 Prompt 名称"""
        return list(self._cache.keys())

    def create_prompt(self, name: str, content: str, metadata: Optional[Dict] = None) -> PromptTemplate:
        """本地策略不支持创建，仅作为只读降级方案"""
        raise NotImplementedError("Local YAML strategy is read-only")
