"""设计文档 87 —— error_kind 结构化信号（§1.3）与 evidence_urls 归一（§1.4-C1）单测。

- ReactRunResult.error_kind：unavailable / max_steps / stopped 三态由 react_loop 在
  终止分支打标（生产侧），不再靠组装侧中文字符串包含判定；
- react_report.assemble 兜底路径按 error_kind 定置信度（非空 → 0.1，空 → 0.4）；
- _dimension_from_item 的 evidence_urls 经 coerce_str_list 归一：单个字符串 URL
  按整体一项，不被按字符迭代。
"""

from __future__ import annotations

import json
from typing import Any

from competitor_agent.agent.react_agent import MAX_STEPS_ANSWER
from competitor_agent.agent.react_loop import ReactLoop
from competitor_agent.domain_types.competitor import Competitor
from competitor_agent.facade import react_report
from competitor_agent.interfaces.exceptions import LLMUnavailableError


class _FakeAgent:
    """ReactLoop 依赖最小面：build_system_prompt + run。"""

    def __init__(self, answer: str = "", exc: Exception | None = None) -> None:
        self._answer = answer
        self._exc = exc

    def build_system_prompt(self, **kwargs: Any) -> str:
        return "sys"

    def run(self, *args: Any, **kwargs: Any) -> str:
        if self._exc is not None:
            raise self._exc
        return self._answer


class TestErrorKindProduction:
    """生产侧（react_loop）：三类非正常终止打出结构化 error_kind。"""

    def test_llm_unavailable_marks_unavailable(self) -> None:
        loop = ReactLoop(agent=_FakeAgent(exc=LLMUnavailableError("no key")))  # type: ignore[arg-type]
        result = loop.run_with_result("任务")
        assert result.error_kind == "unavailable"
        assert "LLM 服务不可用" in result.answer

    def test_max_steps_answer_marks_max_steps(self) -> None:
        loop = ReactLoop(agent=_FakeAgent(answer=MAX_STEPS_ANSWER))  # type: ignore[arg-type]
        result = loop.run_with_result("任务")
        assert result.error_kind == "max_steps"

    def test_normal_answer_no_error_kind(self) -> None:
        loop = ReactLoop(agent=_FakeAgent(answer='{"competitor": "x", "dimensions": []}'))  # type: ignore[arg-type]
        result = loop.run_with_result("任务")
        assert result.error_kind == ""


class TestErrorKindConsumption:
    """消费侧（react_report.assemble 兜底）：error_kind 驱动置信度，无字符串匹配残留。"""

    @staticmethod
    def _assemble(error_kind: str, answer: str = "纯散文，没有任何 JSON。"):
        return react_report.assemble(
            lead_answer=answer,
            competitor=Competitor(name="x"),
            loop_plan=None,
            error_kind=error_kind,
        )

    def test_unavailable_confidence_01(self) -> None:
        report = self._assemble("unavailable", answer="LLM 服务不可用，跳过 ReAct 推理。")
        assert report.dimension_results[0].confidence == 0.1

    def test_max_steps_confidence_01(self) -> None:
        report = self._assemble("max_steps", answer=MAX_STEPS_ANSWER)
        assert report.dimension_results[0].confidence == 0.1

    def test_stopped_confidence_01(self) -> None:
        """取消/预算耗尽（stopped）同样按非正常终止降置信（原中文判定不覆盖"推理已取消"，
        本次结构化后一并收敛——有意行为修正）。"""
        report = self._assemble("stopped", answer="推理已取消（会话被中断）。")
        assert report.dimension_results[0].confidence == 0.1

    def test_no_error_kind_confidence_04(self) -> None:
        report = self._assemble("")
        assert report.dimension_results[0].confidence == 0.4

    def test_sentinel_text_alone_no_longer_downgrades(self) -> None:
        """文案不再当协议：error_kind 缺省时，即使文本逐字含旧哨兵句也不降置信
        （旧实现会因 "推理已停止" 子串误判 0.1）。"""
        report = self._assemble("", answer="推理已停止（预算耗尽）。")
        assert report.dimension_results[0].confidence == 0.4


class TestEvidenceUrlsCoercion:
    """§1.4-C1：evidence_urls 字符串形态按整体一项归一（不按字符迭代）。"""

    def test_str_evidence_url_single_item(self) -> None:
        answer = json.dumps(
            {
                "competitor": "x",
                "dimensions": [
                    {
                        "dimension": "pricing",
                        "summary": "有证据的定价结论",
                        "details": {},
                        "confidence": 0.8,
                        "evidence_urls": "https://example.com/pricing",
                    }
                ],
            }
        )
        report = react_report.assemble(
            lead_answer=answer,
            competitor=Competitor(name="x"),
            loop_plan=None,
        )
        dim = report.dimension_results[0]
        assert [e.url for e in dim.evidence] == ["https://example.com/pricing"]
        assert dim.evidence_hashes == ["https://example.com/pricing"]
