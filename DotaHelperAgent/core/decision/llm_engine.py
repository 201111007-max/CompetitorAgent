"""
LLM 增强引擎 - 结合知识库和实时状态的复杂推理

职责：
- 检索知识库中的攻略文档
- 构建上下文感知的 Prompt
- 调用 LLM 生成个性化建议
- 处理长尾场景和复杂决策

数据来源：
- 知识库（knowledge/）
- 实时游戏状态（GSI）
- LLM 推理能力
"""

from typing import Dict, Any, List, Optional
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)


@dataclass
class LLMRecommendation:
    """LLM 推荐结果"""
    engine: str = "llm"
    recommendation: str = ""
    confidence: float = 0.0
    knowledge_sources: List[str] = None
    
    def __post_init__(self):
        if self.knowledge_sources is None:
            self.knowledge_sources = []
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "engine": self.engine,
            "recommendation": self.recommendation,
            "confidence": self.confidence,
            "knowledge_sources": self.knowledge_sources
        }


class LLMEngine:
    """LLM 增强引擎"""
    
    def __init__(self, config: Optional[Dict[str, Any]] = None, prompt_manager=None):
        """
        初始化 LLM 引擎
        
        Args:
            config: 配置字典
            prompt_manager: Prompt 管理器（可选）
        """
        self.config = config or {}
        self.llm_client = None
        self.knowledge_system = None
        self.prompt_manager = prompt_manager
        logger.info("LLM 增强引擎初始化完成")
    
    def set_llm_client(self, llm_client):
        """
        设置 LLM 客户端
        
        Args:
            llm_client: LLM 客户端实例
        """
        self.llm_client = llm_client
        logger.info("LLM 引擎设置 LLM 客户端")
    
    def set_knowledge_system(self, knowledge_system):
        """
        设置知识库系统
        
        Args:
            knowledge_system: 知识库系统实例
        """
        self.knowledge_system = knowledge_system
        logger.info("LLM 引擎设置知识库系统")
    
    def generate_recommendation(
        self,
        event: Any,
        game_state: Any
    ) -> Optional[LLMRecommendation]:
        """
        生成推荐
        
        Args:
            event: GSI 事件对象
            game_state: 游戏状态（GameState 对象或字典）
        
        Returns:
            推荐结果，如果失败返回 None
        """
        if not self.llm_client or not self.knowledge_system:
            logger.warning("LLM 客户端或知识库未设置")
            return None
        
        try:
            # 归一化 game_state 为字典
            game_state_dict = self._normalize_game_state(game_state)
            
            # 提取事件类型
            event_type = event.event_type if hasattr(event, 'event_type') else str(event)
            
            # 1. 检索相关知识
            hero_name = game_state_dict.get("hero_name", "未知英雄")
            knowledge = self._query_knowledge(hero_name, event_type)
            
            # 2. 构建 Prompt
            prompt = self._build_prompt(event_type, game_state_dict, knowledge)
            
            # 3. 调用 LLM
            response = self._call_llm(prompt)
            
            if not response:
                return None
            
            # 4. 构建推荐结果
            return LLMRecommendation(
                engine="llm",
                recommendation=response,
                confidence=0.6,  # LLM 置信度较低
                knowledge_sources=[k.get("title", "") for k in knowledge]
            )
        
        except Exception as e:
            logger.error(f"生成 LLM 推荐失败: {e}")
            return None
    
    def _normalize_game_state(self, game_state: Any) -> Dict[str, Any]:
        """
        将游戏状态归一化为字典
        
        Args:
            game_state: GameState 对象或字典
        
        Returns:
            归一化后的字典
        """
        if game_state is None:
            return {}
        
        if isinstance(game_state, dict):
            return game_state
        
        # GameState 对象，转换为字典
        if hasattr(game_state, 'to_dict'):
            return game_state.to_dict()
        
        return {}
    
    def _query_knowledge(self, hero_name: str, event_type: str) -> List[Dict[str, Any]]:
        """
        查询知识库
        
        Args:
            hero_name: 英雄名称
            event_type: 事件类型
        
        Returns:
            知识列表
        """
        if not self.knowledge_system:
            return []
        
        try:
            # 构建查询语句
            query = f"{hero_name} {event_type} 攻略"
            
            # 查询知识库
            results = self.knowledge_system.query(query, top_k=3)
            
            return results if results else []
        
        except Exception as e:
            logger.error(f"查询知识库失败: {e}")
            return []
    
    def _build_prompt(
        self,
        event_type: str,
        game_state: Dict[str, Any],
        knowledge: List[Dict[str, Any]]
    ) -> str:
        """
        构建 Prompt
        
        Args:
            event_type: 事件类型
            game_state: 游戏状态
            knowledge: 知识列表
        
        Returns:
            Prompt 字符串
        """
        # 提取游戏状态信息
        hero_name = game_state.get("hero_name", "未知英雄")
        health = game_state.get("health", 0)
        max_health = game_state.get("max_health", 1)
        mana = game_state.get("mana", 0)
        max_mana = game_state.get("max_mana", 1)
        gold = game_state.get("gold", 0)
        game_time = game_state.get("game_time", 0)
        kills = game_state.get("kills", 0)
        deaths = game_state.get("deaths", 0)
        assists = game_state.get("assists", 0)
        
        # 格式化知识内容
        knowledge_text = self._format_knowledge(knowledge)
        
        # 使用 PromptManager 获取 Prompt
        if self.prompt_manager:
            prompt = self.prompt_manager.get_prompt(
                "game_advice",
                variables={
                    "hero_name": hero_name,
                    "health": str(health),
                    "max_health": str(max_health),
                    "health_percent": f"{health/max_health*100:.1f}" if max_health > 0 else "0",
                    "mana": str(mana),
                    "max_mana": str(max_mana),
                    "mana_percent": f"{mana/max_mana*100:.1f}" if max_mana > 0 else "0",
                    "gold": str(gold),
                    "game_time_formatted": f"{game_time // 60}分{game_time % 60}秒",
                    "kills": str(kills),
                    "deaths": str(deaths),
                    "assists": str(assists),
                    "event_type": event_type,
                    "knowledge_text": knowledge_text
                }
            )
        else:
            # 降级方案：使用硬编码 Prompt
            prompt = f"""你是一位专业的 Dota 2 游戏助手。请根据当前游戏状态和触发事件，给出专业的游戏建议。

## 当前游戏状态

- **英雄**: {hero_name}
- **血量**: {health}/{max_health} ({health/max_health*100:.1f}%)
- **魔法**: {mana}/{max_mana} ({mana/max_mana*100:.1f}%)
- **金钱**: {gold}
- **游戏时间**: {game_time // 60}分{game_time % 60}秒
- **KDA**: {kills}/{deaths}/{assists}

## 触发事件

{event_type}

## 相关攻略知识

{knowledge_text}

## 请回答

基于以上信息，请给出：
1. 当前局势分析（1-2句话）
2. 具体行动建议（2-3条）
3. 出装或技能建议（如果适用）

请用简洁、专业的语言回答。"""
        
        return prompt
    
    def _format_knowledge(self, knowledge: List[Dict[str, Any]]) -> str:
        """
        格式化知识内容
        
        Args:
            knowledge: 知识列表
        
        Returns:
            格式化后的知识文本
        """
        if not knowledge:
            return "暂无相关攻略知识"
        
        formatted_parts = []
        for i, k in enumerate(knowledge, 1):
            title = k.get("title", "未知")
            content = k.get("content", "")
            
            # 截取前200字符
            if len(content) > 200:
                content = content[:200] + "..."
            
            formatted_parts.append(f"### {i}. {title}\n{content}")
        
        return "\n\n".join(formatted_parts)
    
    def _call_llm(self, prompt: str) -> Optional[str]:
        """
        调用 LLM
        
        Args:
            prompt: Prompt 字符串
        
        Returns:
            LLM 响应文本
        """
        if not self.llm_client:
            return None
        
        try:
            # 构建消息
            messages = [
                {
                    "role": "system",
                    "content": "你是 Dota 2 专业游戏助手，擅长分析游戏局势并给出专业建议。请用简洁、准确的语言回答。"
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ]
            
            # 调用 LLM
            response = self.llm_client.chat_completion(
                messages=messages,
                temperature=0.7,
                max_tokens=500
            )
            
            if response and "choices" in response:
                return response["choices"][0]["message"]["content"]
            
            return None
        
        except Exception as e:
            logger.error(f"调用 LLM 失败: {e}")
            return None
