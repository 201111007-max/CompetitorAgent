"""LLM 客户端适配器

将 DotaHelperAgent 现有的同步 LLMClient 适配为评测系统 Judge 所需的统一接口。

设计目标：
- 复用现有 utils.llm_client.LLMClient，不修改其实现
- 统一接口：judge.generate(prompt) -> str
- 支持无 LLM 客户端的 Mock 模式（用于本地 dry-run）
"""

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class LLMJudgeAdapter:
    """Judge LLM 适配器

    将不同的 LLM 调用方式统一为：
        generate(prompt: str) -> str
    """

    def __init__(
        self,
        llm_client: Any = None,
        model: str = "default",
        temperature: float = 0.0,
    ):
        """
        Args:
            llm_client: 任何实现了 .chat(messages, ...) 或 .complete(prompt, ...) 的客户端
                        可以为 None（Mock 模式）
            model: 模型标识（用于日志）
            temperature: 默认采样温度
        """
        self.llm_client = llm_client
        self.model = model
        self.temperature = temperature
        self._has_chat = hasattr(llm_client, "chat") if llm_client else False
        self._has_complete = hasattr(llm_client, "complete") if llm_client else False

    def generate(self, prompt: str, temperature: Optional[float] = None) -> str:
        """生成文本（统一接口）

        Args:
            prompt: 输入 prompt
            temperature: 覆盖默认 temperature

        Returns:
            模型输出文本
        """
        if self.llm_client is None:
            return self._mock_generate(prompt)

        temp = temperature if temperature is not None else self.temperature

        # 优先使用 complete（prompt 模式）
        if self._has_complete:
            try:
                result = self.llm_client.complete(prompt, temperature=temp)
                return self._extract_text(result)
            except Exception as e:
                logger.error(f"LLM complete failed: {e}, fallback to mock")
                return self._mock_generate(prompt)

        # 回退到 chat（messages 模式）
        if self._has_chat:
            try:
                messages = [{"role": "user", "content": prompt}]
                result = self.llm_client.chat(messages, temperature=temp)
                return self._extract_text(result)
            except Exception as e:
                logger.error(f"LLM chat failed: {e}, fallback to mock")
                return self._mock_generate(prompt)

        # 都没有则 Mock
        return self._mock_generate(prompt)

    def _extract_text(self, result: Any) -> str:
        """从 LLMClient 返回值中提取文本

        现有 LLMClient.chat 返回 dict:
            {
                "id": "...",
                "choices": [{"message": {"content": "..."}}],
                ...
            }
        """
        if isinstance(result, str):
            return result

        if isinstance(result, dict):
            # OpenAI 格式
            choices = result.get("choices", [])
            if choices and isinstance(choices, list):
                first = choices[0]
                if isinstance(first, dict):
                    msg = first.get("message", {})
                    if isinstance(msg, dict):
                        return msg.get("content", "")

            # 直接 content 字段
            if "content" in result:
                return result["content"]

            # text 字段
            if "text" in result:
                return result["text"]

        return str(result)

    def _mock_generate(self, prompt: str) -> str:
        """Mock 生成（无 LLM 客户端时使用）"""
        logger.debug(f"[MockLLM] prompt length: {len(prompt)}")
        return self._mock_judge_response()

    def _mock_judge_response(self) -> str:
        """构造符合 7 维评分格式的 Mock 响应"""
        return """{
  "correctness": 4,
  "completeness": 4,
  "relevance": 4,
  "tool_selection": 4,
  "efficiency": 4,
  "robustness": 3,
  "personalization": 3,
  "total_score": 3.85,
  "reasoning": "Mock 评分（未配置真实 LLM 客户端）。请配置 LLMClient 以获得真实评估。"
}"""

    def is_mock(self) -> bool:
        """是否处于 Mock 模式"""
        return self.llm_client is None or (not self._has_chat and not self._has_complete)


def build_judge_adapter(
    llm_client: Any = None,
    model: str = "default",
    temperature: float = 0.0,
) -> LLMJudgeAdapter:
    """构建 Judge 适配器（工厂函数）

    Args:
        llm_client: 现有 LLMClient 实例（None 则使用 Mock）
        model: 模型名
        temperature: 采样温度

    Returns:
        LLMJudgeAdapter 实例
    """
    if llm_client is None:
        logger.info(
            "No LLM client provided, using Mock mode. "
            "Pass an LLMClient instance for real evaluation."
        )
    return LLMJudgeAdapter(
        llm_client=llm_client,
        model=model,
        temperature=temperature,
    )
