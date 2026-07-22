"""分析器基类"""
import json
import re
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional

from post_match_review.interfaces.analyzer import IReviewAnalyzer
from post_match_review.interfaces.llm import ILLMClient
from post_match_review.domain_types.analysis import (
    AnalysisContext,
    AnalysisResult,
    Conclusion,
)
from post_match_review.domain_types.match_data import MatchData
from post_match_review.observability.logger import get_logger

logger = get_logger("analyzers.base")


class BaseLLMReviewAnalyzer(ABC):
    """LLM 驱动分析器基类

    提供模板方法模式，子类只需实现特定方法即可完成分析流程。
    """

    def __init__(self, llm_client: ILLMClient) -> None:
        """初始化基类

        Args:
            llm_client: LLM 客户端实例
        """
        self._llm_client = llm_client
        logger.info("初始化 LLM 分析器基类: %s", self.__class__.__name__)

    @property
    @abstractmethod
    def phase_name(self) -> str:
        """分析阶段名称（子类必须实现）"""
        ...

    @abstractmethod
    def build_prompt(
        self,
        match_data: MatchData,
        context: AnalysisContext,
    ) -> List[Dict[str, str]]:
        """构建提示词（子类必须实现）

        Args:
            match_data: 结构化比赛数据
            context: 分析上下文

        Returns:
            List[Dict[str, str]]: OpenAI 风格消息列表
        """
        ...

    @abstractmethod
    def parse_response(self, response: str) -> List[Conclusion]:
        """解析 LLM 响应为结论列表（子类必须实现）

        Args:
            response: LLM 原始响应文本

        Returns:
            List[Conclusion]: 解析后的结论列表
        """
        ...

    async def analyze(
        self,
        match_data: MatchData,
        context: AnalysisContext,
    ) -> AnalysisResult:
        """执行分析（模板方法）

        Args:
            match_data: 结构化比赛数据
            context: 分析上下文

        Returns:
            AnalysisResult: 分析结果
        """
        completed_phases = [r.phase for r in context.completed_results]
        logger.info(
            "[阶段:%s] 开始分析 match_id=%s, 已完成阶段=%s, 反馈=%s",
            self.phase_name,
            match_data.match_id,
            completed_phases,
            context.iteration_feedback,
        )

        # 1. 构建提示词
        messages = self.build_prompt(match_data, context)
        prompt_text = "\n".join(m.get("content", "") for m in messages)
        logger.debug(
            "[阶段:%s] 构建提示词完成，消息数=%d, 提示词长度=%d",
            self.phase_name,
            len(messages),
            len(prompt_text),
        )
        logger.debug(
            "[阶段:%s] 提示词内容:\n%s",
            self.phase_name,
            prompt_text,
        )

        # 2. 调用 LLM
        try:
            response = await self._llm_client.chat(messages)
            logger.debug(
                "[阶段:%s] LLM 响应长度: %d 字符",
                self.phase_name,
                len(response),
            )
            logger.info(
                "[阶段:%s] LLM 原始响应:\n%s",
                self.phase_name,
                response,
            )
        except Exception as e:
            logger.error(
                "[阶段:%s] LLM 调用失败: %s",
                self.phase_name,
                str(e),
                exc_info=True,
            )
            # 返回空结果，置信度为 0
            return AnalysisResult(
                phase=self.phase_name,
                conclusions=[],
                confidence=0.0,
                iterations_used=1,
                tokens_consumed=0,
                analysis_text=f"LLM 调用失败: {str(e)}",
            )

        # 3. 解析响应
        conclusions = self.parse_response(response)
        logger.info(
            "[阶段:%s] 解析出 %d 条结论",
            self.phase_name,
            len(conclusions),
        )
        for idx, conclusion in enumerate(conclusions):
            logger.info(
                "[阶段:%s] 结论 #%d: title=%s, impact=%s, has_evidence=%s, "
                "evidence=%s, suggestion=%s",
                self.phase_name,
                idx + 1,
                conclusion.title,
                conclusion.impact,
                conclusion.has_evidence,
                conclusion.evidence,
                conclusion.suggestion,
            )

        # 4. 计算置信度（结论平均置信度）
        confidence = self._calculate_confidence(conclusions)
        logger.info("[阶段:%s] 阶段置信度: %.2f", self.phase_name, confidence)

        # 5. 构建结果
        result = AnalysisResult(
            phase=self.phase_name,
            conclusions=conclusions,
            confidence=confidence,
            iterations_used=1,
            tokens_consumed=0,  # 由 TacticalLoop 填充
            analysis_text=response,
        )

        is_valid = self.validate_result(result)
        logger.info(
            "[阶段:%s] 结果验证: valid=%s, confidence=%.2f, conclusions=%d",
            self.phase_name,
            is_valid,
            result.confidence,
            len(result.conclusions),
        )

        return result

    def _calculate_confidence(self, conclusions: List[Conclusion]) -> float:
        """计算阶段置信度（结论平均置信度）

        Args:
            conclusions: 结论列表

        Returns:
            float: 平均置信度，范围 [0, 1]
        """
        if not conclusions:
            return 0.0

        # 基于证据数量和影响级别计算每条结论的置信度
        total_confidence = 0.0
        for conclusion in conclusions:
            conf = 0.6  # 基础置信度（LLM生成的结论本身就有价值）

            # 有证据支撑 +0.2
            if conclusion.has_evidence and len(conclusion.evidence) > 0:
                conf += 0.2

            # 影响级别调整
            if conclusion.impact == "high":
                conf += 0.1
            elif conclusion.impact == "low":
                conf -= 0.1

            total_confidence += min(conf, 1.0)

        return total_confidence / len(conclusions)

    def validate_result(self, result: AnalysisResult) -> bool:
        """验证分析结果是否有效

        Args:
            result: 待验证的分析结果

        Returns:
            bool: 结果是否有效
        """
        # 检查置信度 >= 0.6
        if result.confidence < 0.6:
            logger.warning(
                "[阶段:%s] 置信度过低: %.2f < 0.6",
                self.phase_name,
                result.confidence,
            )
            return False

        # 检查至少有一条结论有证据支撑
        has_evidence_count = sum(
            1 for c in result.conclusions if c.has_evidence
        )
        if has_evidence_count == 0:
            logger.warning(
                "[阶段:%s] 无结论包含证据支撑 (conclusions=%d)",
                self.phase_name,
                len(result.conclusions),
            )
            return False

        logger.debug("[阶段:%s] 结果验证通过", self.phase_name)
        return True


class BaseRuleReviewAnalyzer(ABC):
    """规则驱动分析器基类（LLM 不可用时的降级方案）

    基于预定义规则和阈值进行分析，不依赖 LLM。
    """

    @property
    @abstractmethod
    def phase_name(self) -> str:
        """分析阶段名称（子类必须实现）"""
        ...

    @abstractmethod
    def analyze_with_rules(
        self,
        match_data: MatchData,
        context: AnalysisContext,
    ) -> List[Conclusion]:
        """使用规则进行分析（子类必须实现）

        Args:
            match_data: 结构化比赛数据
            context: 分析上下文

        Returns:
            List[Conclusion]: 分析结论列表
        """
        ...

    async def analyze(
        self,
        match_data: MatchData,
        context: AnalysisContext,
    ) -> AnalysisResult:
        """执行规则分析

        Args:
            match_data: 结构化比赛数据
            context: 分析上下文

        Returns:
            AnalysisResult: 分析结果
        """
        logger.info(
            "[阶段:%s] 开始规则分析 match_id=%s",
            self.phase_name,
            match_data.match_id,
        )

        # 1. 执行规则分析
        conclusions = self.analyze_with_rules(match_data, context)
        logger.info(
            "[阶段:%s] 规则分析生成 %d 条结论",
            self.phase_name,
            len(conclusions),
        )
        for idx, conclusion in enumerate(conclusions):
            logger.info(
                "[阶段:%s] 结论 #%d: title=%s, impact=%s, has_evidence=%s, evidence=%s",
                self.phase_name,
                idx + 1,
                conclusion.title,
                conclusion.impact,
                conclusion.has_evidence,
                conclusion.evidence,
            )

        # 2. 计算置信度
        confidence = self._calculate_confidence(conclusions)
        logger.info("[阶段:%s] 阶段置信度: %.2f", self.phase_name, confidence)

        # 3. 构建结果
        result = AnalysisResult(
            phase=self.phase_name,
            conclusions=conclusions,
            confidence=confidence,
            iterations_used=1,
            tokens_consumed=0,
            analysis_text="[规则驱动分析]",
        )

        is_valid = self.validate_result(result)
        logger.info(
            "[阶段:%s] 规则结果验证: valid=%s, confidence=%.2f, conclusions=%d",
            self.phase_name,
            is_valid,
            result.confidence,
            len(result.conclusions),
        )

        return result

    def _calculate_confidence(self, conclusions: List[Conclusion]) -> float:
        """计算阶段置信度

        Args:
            conclusions: 结论列表

        Returns:
            float: 平均置信度
        """
        if not conclusions:
            return 0.0

        total_confidence = 0.0
        for conclusion in conclusions:
            conf = 0.6  # 规则分析基础置信度较低

            if conclusion.has_evidence and len(conclusion.evidence) > 0:
                conf += 0.1

            total_confidence += min(conf, 1.0)

        return total_confidence / len(conclusions)

    def validate_result(self, result: AnalysisResult) -> bool:
        """验证分析结果是否有效

        Args:
            result: 待验证的分析结果

        Returns:
            bool: 结果是否有效
        """
        # 规则分析的验证标准略低
        if result.confidence < 0.5:
            logger.warning(
                "[阶段:%s] 规则分析置信度过低: %.2f < 0.5",
                self.phase_name,
                result.confidence,
            )
            return False

        if len(result.conclusions) == 0:
            logger.warning(
                "[阶段:%s] 规则分析无结论",
                self.phase_name,
            )
            return False

        logger.debug("[阶段:%s] 规则结果验证通过", self.phase_name)
        return True


def parse_json_response(response: str) -> Optional[Dict[str, Any]]:
    """从 LLM 响应中解析 JSON

    支持从 markdown 代码块中提取 JSON，处理嵌套结构。

    Args:
        response: LLM 原始响应文本

    Returns:
        Optional[Dict[str, Any]]: 解析后的字典，失败返回 None
    """
    # 尝试直接解析
    try:
        return json.loads(response)
    except json.JSONDecodeError:
        pass

    # 尝试提取 ```json ... ``` 或 ``` ... ``` 代码块
    # 使用非贪婪匹配，确保每个代码块独立匹配
    code_block_pattern = re.compile(r"```(?:json)?\s*\n?(.*?)\n?\s*```", re.DOTALL)
    for match in code_block_pattern.finditer(response):
        json_str = match.group(1).strip()
        try:
            result = json.loads(json_str)
            if isinstance(result, dict):
                return result
        except json.JSONDecodeError:
            continue

    # 尝试提取 { ... } 块（使用括号匹配算法处理嵌套）
    json_obj = _extract_json_object(response)
    if json_obj is not None:
        return json_obj

    logger.warning("无法从响应中解析 JSON")
    return None


def _extract_json_object(text: str) -> Optional[Dict[str, Any]]:
    """从文本中提取 JSON 对象（处理嵌套括号）

    Args:
        text: 输入文本

    Returns:
        Optional[Dict[str, Any]]: 解析后的字典，失败返回 None
    """
    # 找到第一个 {
    start = text.find("{")
    if start == -1:
        return None

    # 使用括号匹配找到完整的 JSON 对象
    brace_count = 0
    in_string = False
    escape_next = False

    for i in range(start, len(text)):
        char = text[i]

        if escape_next:
            escape_next = False
            continue

        if char == "\\":
            escape_next = True
            continue

        if char == '"' and not escape_next:
            in_string = not in_string
            continue

        if in_string:
            continue

        if char == "{":
            brace_count += 1
        elif char == "}":
            brace_count -= 1
            if brace_count == 0:
                # 找到匹配的闭合括号
                json_str = text[start : i + 1]
                try:
                    return json.loads(json_str)
                except json.JSONDecodeError:
                    return None

    return None
