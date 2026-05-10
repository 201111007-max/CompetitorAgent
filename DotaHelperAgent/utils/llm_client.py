"""LLM 客户端模块 - 支持本地部署的大模型调用

配置说明：
- 默认从 config/llm_config.yaml 加载配置
- 支持代码中直接配置（优先级更高）
- 支持环境变量覆盖
"""

import requests
import json
from typing import Dict, List, Optional, Any, Generator

# 从核心配置模块导入 LLMConfig
try:
    from ..core.config import LLMConfig
except ImportError:
    from core.config import LLMConfig


class LLMClient:
    """LLM 客户端
    
    支持本地部署的模型，如 LM Studio、Ollama、vLLM 等
    默认使用 OpenAI 兼容的 API 格式
    """
    
    def __init__(self, config: Optional[LLMConfig] = None):
        """初始化 LLM 客户端
        
        Args:
            config: LLM 配置，如果为 None 则使用默认配置
        """
        self.config = config or LLMConfig()
        self.session = requests.Session()
        
        # 设置请求头
        headers = {
            "Content-Type": "application/json",
        }
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        
        self.session.headers.update(headers)
    
    def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        stream: Optional[bool] = None
    ) -> Dict[str, Any]:
        """发送聊天请求
        
        Args:
            messages: 消息列表，格式为 [{"role": "user", "content": "..."}, ...]
            temperature: 温度参数（覆盖配置）
            max_tokens: 最大生成 token 数（覆盖配置）
            stream: 是否流式输出（覆盖配置）
            
        Returns:
            API 响应结果
        """
        url = f"{self.config.base_url}/chat/completions"
        
        payload = {
            "model": self.config.model,
            "messages": messages,
            "temperature": temperature or self.config.temperature,
            "max_tokens": max_tokens or self.config.max_tokens,
            "top_p": self.config.top_p,
            "stream": stream if stream is not None else self.config.stream,
        }
        
        try:
            response = self.session.post(
                url,
                json=payload,
                timeout=self.config.timeout
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"LLM 请求失败: {e}")
            return {"error": str(e)}
    
    def chat_stream(
        self,
        messages: List[Dict[str, str]],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None
    ) -> Generator[str, None, None]:
        """流式发送聊天请求
        
        Args:
            messages: 消息列表
            temperature: 温度参数
            max_tokens: 最大生成 token 数
            
        Yields:
            生成的文本片段
        """
        url = f"{self.config.base_url}/chat/completions"
        
        payload = {
            "model": self.config.model,
            "messages": messages,
            "temperature": temperature or self.config.temperature,
            "max_tokens": max_tokens or self.config.max_tokens,
            "top_p": self.config.top_p,
            "stream": True,
        }
        
        try:
            response = self.session.post(
                url,
                json=payload,
                timeout=self.config.timeout,
                stream=True
            )
            response.raise_for_status()
            
            for line in response.iter_lines():
                if line:
                    line = line.decode('utf-8')
                    if line.startswith('data: '):
                        data = line[6:]
                        if data == '[DONE]':
                            break
                        try:
                            chunk = json.loads(data)
                            delta = chunk.get('choices', [{}])[0].get('delta', {})
                            content = delta.get('content', '')
                            if content:
                                yield content
                        except json.JSONDecodeError:
                            continue
        except requests.exceptions.RequestException as e:
            print(f"LLM 流式请求失败: {e}")
            yield f"[错误: {e}]"
    
    def complete(
        self,
        prompt: str,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None
    ) -> str:
        """简单的文本补全
        
        Args:
            prompt: 提示文本
            temperature: 温度参数
            max_tokens: 最大生成 token 数
            
        Returns:
            生成的文本
        """
        messages = [{"role": "user", "content": prompt}]
        response = self.chat(messages, temperature, max_tokens)
        
        if "error" in response:
            return f"生成失败: {response['error']}"
        
        try:
            return response['choices'][0]['message']['content']
        except (KeyError, IndexError) as e:
            return f"解析响应失败: {e}"
    
    def check_health(self) -> bool:
        """检查 LLM 服务是否可用
        
        Returns:
            是否可用
        """
        try:
            # 尝试获取模型列表或发送简单请求
            url = f"{self.config.base_url}/models"
            response = self.session.get(url, timeout=5)
            return response.status_code == 200
        except requests.exceptions.RequestException:
            return False
    
    def get_models(self) -> List[str]:
        """获取可用的模型列表
        
        Returns:
            模型名称列表
        """
        try:
            url = f"{self.config.base_url}/models"
            response = self.session.get(url, timeout=self.config.timeout)
            response.raise_for_status()
            data = response.json()
            return [model.get('id', '') for model in data.get('data', [])]
        except requests.exceptions.RequestException as e:
            print(f"获取模型列表失败: {e}")
            return []


class DotaLLMAnalyzer:
    """基于 LLM 的 Dota 2 分析器
    
    使用大模型增强分析能力，提供自然语言解释和策略建议
    """
    
    def __init__(self, llm_client: LLMClient):
        """初始化
        
        Args:
            llm_client: LLM 客户端实例
        """
        self.llm = llm_client
    
    def explain_recommendation(
        self,
        hero_name: str,
        enemy_heroes: List[str],
        win_rate: float,
        reasons: List[str]
    ) -> str:
        """解释为什么推荐这个英雄
        
        Args:
            hero_name: 推荐的英雄名称
            enemy_heroes: 敌方英雄列表
            win_rate: 胜率
            reasons: 推荐理由
            
        Returns:
            自然语言解释
        """
        prompt = f"""作为 Dota 2 专家，请解释为什么 {hero_name} 是应对敌方阵容的好选择。

敌方阵容: {', '.join(enemy_heroes)}
统计数据: 胜率 {win_rate:.1%}
数据支撑: {', '.join(reasons)}

请用中文简要解释（100字以内）：
1. 这个英雄的核心优势
2. 针对敌方哪个英雄最有效
3. 使用时的关键技巧
"""
        return self.llm.complete(prompt, temperature=0.7, max_tokens=200)
    
    def analyze_team_composition(
        self,
        our_heroes: List[str],
        enemy_heroes: List[str]
    ) -> str:
        """分析阵容优劣势
        
        Args:
            our_heroes: 己方英雄列表
            enemy_heroes: 敌方英雄列表
            
        Returns:
            阵容分析
        """
        prompt = f"""分析以下 Dota 2 阵容的优劣势：

己方阵容: {', '.join(our_heroes) if our_heroes else '暂无'}
敌方阵容: {', '.join(enemy_heroes)}

请用中文分析：
1. 己方阵容的优势和劣势
2. 敌方阵容的威胁点
3. 游戏各阶段的策略建议（前期/中期/后期）
4. 团战关键要点
"""
        return self.llm.complete(prompt, temperature=0.7, max_tokens=400)
    
    def suggest_item_build(
        self,
        hero_name: str,
        enemy_heroes: List[str],
        game_stage: str
    ) -> str:
        """根据局势建议出装
        
        Args:
            hero_name: 英雄名称
            enemy_heroes: 敌方英雄列表
            game_stage: 游戏阶段
            
        Returns:
            出装建议
        """
        prompt = f"""作为 Dota 2 装备专家，为 {hero_name} 在 {game_stage} 阶段提供出装建议。

敌方阵容：{', '.join(enemy_heroes)}

请用中文建议：
1. 核心装备及原因
2. 针对敌方阵容的防御装备
3. 可选的功能性装备
"""
        return self.llm.complete(prompt, temperature=0.7, max_tokens=300)
    
    def recommend_heroes(
        self,
        our_heroes: List[str],
        enemy_heroes: List[str],
        top_n: int = 3
    ) -> List[Dict[str, Any]]:
        """基于 LLM 的英雄推荐
        
        Args:
            our_heroes: 己方已选英雄列表
            enemy_heroes: 敌方已选英雄列表
            top_n: 推荐数量
            
        Returns:
            推荐英雄列表，每个包含 hero_name, score, reasons
        """
        our_team_str = ', '.join(our_heroes) if our_heroes else '暂无'
        enemy_team_str = ', '.join(enemy_heroes)
        
        prompt = f"""作为 Dota 2 专家，请根据以下阵容推荐 {top_n} 个最佳英雄选择。

己方阵容：{our_team_str}
敌方阵容：{enemy_team_str}

请分析：
1. 己方阵容缺少什么定位（控制/输出/辅助/坦克）
2. 敌方阵容的威胁点
3. 推荐 {top_n} 个英雄，并说明理由

请严格按照以下 JSON 格式返回（不要有其他文字）：
{{
    "recommendations": [
        {{
            "hero_name": "英雄名称",
            "score": 0.95,
            "reasons": ["理由 1", "理由 2", "理由 3"]
        }}
    ]
}}

注意：
- score 范围 0-1，表示推荐强度
- reasons 数组包含 2-3 个推荐理由
- 推荐英雄应该是 Dota 2 中真实存在的英雄
"""
        
        response = self.llm.chat(messages=[{"role": "user", "content": prompt}], temperature=0.7, max_tokens=1000)
        
        if "error" in response:
            raise Exception(f"LLM 推荐失败：{response['error']}")
        
        try:
            content = response['choices'][0]['message']['content']
            import json
            result = json.loads(content)
            recommendations = result.get('recommendations', [])
            
            # 验证和规范化数据
            validated = []
            for rec in recommendations[:top_n]:
                validated.append({
                    'hero_name': rec.get('hero_name', 'Unknown'),
                    'score': float(rec.get('score', 0.5)),
                    'reasons': rec.get('reasons', [])
                })
            
            return validated
        except (KeyError, IndexError, json.JSONDecodeError) as e:
            raise Exception(f"解析 LLM 响应失败：{e}")
    
    def answer_question(self, question: str, context: Optional[str] = None) -> str:
        """回答用户关于 Dota 2 的问题
        
        Args:
            question: 用户问题
            context: 可选的上下文信息
            
        Returns:
            回答
        """
        system_prompt = "你是 Dota 2 专家助手，擅长英雄克制、出装推荐和策略分析。请用中文简洁回答。"
        
        messages = [
            {"role": "system", "content": system_prompt},
        ]
        
        if context:
            messages.append({"role": "user", "content": f"背景信息：{context}"})
        
        messages.append({"role": "user", "content": question})
        
        response = self.llm.chat(messages, temperature=0.7, max_tokens=500)
        
        if "error" in response:
            return f"回答失败: {response['error']}"
        
        try:
            return response['choices'][0]['message']['content']
        except (KeyError, IndexError) as e:
            return f"解析响应失败: {e}"
