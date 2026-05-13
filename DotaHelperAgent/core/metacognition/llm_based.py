"""基于 LLM 的元认知评估器（高级实现）

特点：
- 更智能的知识边界判断
- 自然语言推理
- 需要 LLM API 调用
- 可作为规则实现的增强版

注意：
- 如果 LLM 调用失败，会自动降级到保守评估
- 建议与规则实现混合使用（LLM 知识边界 + 规则澄清生成）
"""

from typing import Dict, List, Any, Optional
import json
import re
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from core.metacognition.interfaces import (
    IKnowledgeBoundary,
    KnowledgeAssessment,
    ConfidenceLevel
)
from utils.log_config import get_logger
from utils.trace_context import TraceSpan, get_current_trace

logger = get_logger("llm_based_metacognition", component="core")


class LLMBasedKnowledgeBoundary(IKnowledgeBoundary):
    """基于 LLM 的知识边界评估
    
    使用 LLM 进行自然语言推理，判断知识掌握程度
    
    扩展方式：
    - 继承此类并重写 ASSESSMENT_PROMPT 或解析逻辑
    - 或实现 IKnowledgeBoundary 接口创建全新实现
    """
    
    ASSESSMENT_PROMPT = """你是一个 AI 助手的元认知评估模块。请评估你对以下问题的知识掌握程度。

## 用户查询
{query}

## 可用工具
{available_tools}

## 当前上下文
{context}

## 评估要求
请从以下维度评估（0-1 分）：
1. 知识覆盖度：你是否有足够的数据回答这个问题？
2. 数据质量：你的数据是否足够新和可靠？
3. 工具匹配度：你是否有合适的工具来处理这个问题？

请返回 JSON 格式：
{{
    "coverage_score": 0.8,
    "quality_score": 0.7,
    "tool_match_score": 0.9,
    "overall_score": 0.8,
    "reasoning": "评估理由...",
    "limitations": ["限制 1", "限制 2"],
    "data_sources": ["数据源 1"]
}}

只返回 JSON，不要其他内容："""
    
    def __init__(self, llm_client, tool_registry=None):
        """初始化
        
        Args:
            llm_client: LLM 客户端
            tool_registry: 工具注册表
        """
        self.llm = llm_client
        self.tool_registry = tool_registry
    
    def assess(self, query: str, context: Dict[str, Any]) -> KnowledgeAssessment:
        """使用 LLM 评估知识掌握程度"""
        trace_ctx = get_current_trace()
        
        with TraceSpan("llm_knowledge_boundary_assess"):
            logger.info_ctx(
                "开始 LLM 知识边界评估",
                session_id=trace_ctx.session_id if trace_ctx else None,
                extra_data={"query": query}
            )
            
            try:
                prompt = self.ASSESSMENT_PROMPT.format(
                    query=query,
                    available_tools=self._format_tools(),
                    context=json.dumps(context, ensure_ascii=False, indent=2)
                )
                
                logger.debug_ctx(
                    "调用 LLM 进行评估",
                    session_id=trace_ctx.session_id if trace_ctx else None
                )
                
                response = self.llm.chat(
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=512,
                    temperature=0.2
                )
                
                if "error" in response:
                    raise Exception(response["error"])
                
                content = response["choices"][0]["message"]["content"]
                assessment_data = self._parse_response(content)
                
                assessment = KnowledgeAssessment(
                    confidence_score=assessment_data["overall_score"],
                    confidence_level=self._score_to_level(assessment_data["overall_score"]),
                    knowledge_coverage=assessment_data["coverage_score"],
                    data_quality_score=assessment_data["quality_score"],
                    reasoning=assessment_data["reasoning"],
                    limitations=assessment_data.get("limitations", []),
                    data_sources=assessment_data.get("data_sources", [])
                )
                
                logger.info_ctx(
                    "LLM 知识边界评估完成",
                    session_id=trace_ctx.session_id if trace_ctx else None,
                    extra_data={
                        "confidence_score": round(assessment.confidence_score, 3),
                        "confidence_level": assessment.confidence_level.value
                    }
                )
                
                return assessment
                
            except Exception as e:
                logger.warning_ctx(
                    "LLM 评估失败，降级到默认评估",
                    session_id=trace_ctx.session_id if trace_ctx else None,
                    extra_data={"error": str(e)}
                )
                
                return KnowledgeAssessment(
                    confidence_score=0.5,
                    confidence_level=ConfidenceLevel.MEDIUM,
                    knowledge_coverage=0.5,
                    data_quality_score=0.5,
                    reasoning=f"LLM 评估失败：{str(e)}，使用默认评估",
                    limitations=["评估失败，使用保守估计"],
                    data_sources=[]
                )
    
    def _format_tools(self) -> str:
        """格式化工具列表"""
        if not self.tool_registry:
            return "无可用工具"
        
        tools = self.tool_registry.list_tools()
        return ", ".join(tools) if tools else "无可用工具"
    
    def _parse_response(self, content: str) -> Dict[str, Any]:
        """解析 LLM 响应"""
        json_match = re.search(r'\{.*\}', content, re.DOTALL)
        if not json_match:
            raise ValueError("LLM 返回格式不正确")
        
        return json.loads(json_match.group())
    
    def _score_to_level(self, score: float) -> ConfidenceLevel:
        """分数转等级"""
        if score >= 0.9:
            return ConfidenceLevel.VERY_HIGH
        elif score >= 0.7:
            return ConfidenceLevel.HIGH
        elif score >= 0.5:
            return ConfidenceLevel.MEDIUM
        elif score >= 0.3:
            return ConfidenceLevel.LOW
        else:
            return ConfidenceLevel.VERY_LOW
