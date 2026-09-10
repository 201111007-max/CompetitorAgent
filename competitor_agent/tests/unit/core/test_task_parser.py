"""core/task_parser.py 单测（设计文档 47：仅 LLM 解析，无规则降级）"""
import json

import pytest

from competitor_agent.core.task_parser import ResolutionDecision, parse_task
from competitor_agent.interfaces.exceptions import LLMUnavailableError
from competitor_agent.llm.client import LLMClient


class TestParseTaskLLM:
    def test_llm_parses_struct(self):
        llm = LLMClient(
            call_func=lambda messages, model: json.dumps(
                {"resolution": "registry", "competitors": ["cursor"], "dimensions": ["pricing"], "custom_sources": {}}
            )
        )
        result = parse_task("分析 Cursor", llm=llm, use_llm=True)
        assert result.competitors == ["cursor"]
        assert result.dimensions == ["pricing"]
        assert result.raw_task == "分析 Cursor"

    def test_llm_garbage_raises_llm_unavailable(self):
        llm = LLMClient(call_func=lambda messages, model: "不是 JSON")
        with pytest.raises(LLMUnavailableError):
            parse_task("只分析 Cursor 定价", llm=llm, use_llm=True)

    def test_no_llm_raises(self):
        with pytest.raises(LLMUnavailableError):
            parse_task("对比 Cursor 和 Windsurf", llm=None, use_llm=True)

    def test_use_llm_false_raises(self):
        llm = LLMClient(call_func=lambda messages, model: "{}")
        with pytest.raises(LLMUnavailableError):
            parse_task("分析 Cursor", llm=llm, use_llm=False)

    def test_empty_competitors_returns_unknown_primary(self):
        llm = LLMClient(
            call_func=lambda messages, model: json.dumps(
                {"resolution": "discovery", "competitors": [], "dimensions": None, "custom_sources": {}}
            )
        )
        result = parse_task("帮我找所有 agent", llm=llm, use_llm=True)
        assert result.primary_competitor == "unknown"
        assert result.is_discovery

    def test_invalid_dimensions_filtered(self):
        """非法维度名被过滤；全部非法 → None（全部维度）。"""
        llm = LLMClient(
            call_func=lambda messages, model: json.dumps(
                {"competitors": ["cursor"], "dimensions": ["pricing", "bogus"], "custom_sources": {}}
            )
        )
        result = parse_task("分析 Cursor", llm=llm, use_llm=True)
        assert result.dimensions == ["pricing"]

    def test_llm_failure_propagates(self):
        class FailingLLM(LLMClient):
            def complete(self, messages, json_mode=False):
                raise RuntimeError("llm down")

        with pytest.raises(LLMUnavailableError):
            parse_task("分析 Cursor", llm=FailingLLM(), use_llm=True)


class TestResolutionDecision:
    """设计文档 20：LLM 输出 resolution 决策（REGISTRY / DISCOVERY / COMPARE）"""

    @staticmethod
    def _llm(payload: dict) -> LLMClient:
        return LLMClient(call_func=lambda messages, model: json.dumps(payload))

    def test_llm_discovery_sets_is_discovery(self):
        result = parse_task(
            "帮我找市场上所有 AI coding agent",
            llm=self._llm({"resolution": "discovery", "competitors": [], "dimensions": None, "custom_sources": {}}),
            use_llm=True,
        )
        assert result.resolution == ResolutionDecision.DISCOVERY
        assert result.is_discovery

    def test_llm_registry_sets_not_discovery(self):
        result = parse_task(
            "分析 Cursor",
            llm=self._llm({"resolution": "registry", "competitors": ["cursor"], "dimensions": None, "custom_sources": {}}),
            use_llm=True,
        )
        assert result.resolution == ResolutionDecision.REGISTRY
        assert not result.is_discovery

    def test_llm_compare_three_names(self):
        result = parse_task(
            "对比 Cursor 和 Windsurf 和 Copilot",
            llm=self._llm(
                {"resolution": "compare", "competitors": ["cursor", "windsurf", "copilot"], "dimensions": None, "custom_sources": {}}
            ),
            use_llm=True,
        )
        assert result.resolution == ResolutionDecision.COMPARE
        assert len(result.competitors) == 3
        assert result.is_compare

    def test_llm_bad_resolution_defaults_chat(self):
        """设计文档 64 §5.4：畸形 resolution → 默认 CHAT（分类失败缺省落在对话式分支，
        宁可普通回答也不强造空报告；与 doc 20 的 REGISTRY 默认方向相反）。"""
        result = parse_task(
            "分析 Cursor",
            llm=self._llm({"resolution": "totally-wrong", "competitors": ["cursor"], "dimensions": None, "custom_sources": {}}),
            use_llm=True,
        )
        assert result.resolution == ResolutionDecision.CHAT

    def test_llm_chat_sets_is_chat(self):
        result = parse_task(
            "今天天气怎么样",
            llm=self._llm({"resolution": "chat", "competitors": [], "dimensions": None, "custom_sources": {}}),
            use_llm=True,
        )
        assert result.resolution == ResolutionDecision.CHAT
        assert result.is_chat
        assert result.competitors == []

    def test_llm_null_custom_sources_no_crash(self):
        """真实 LLM 常返回 custom_sources: null → 不应崩溃（解析为无用户指定来源）。"""
        result = parse_task(
            "分析 Cursor",
            llm=self._llm({"resolution": "registry", "competitors": ["cursor"], "dimensions": None, "custom_sources": None}),
            use_llm=True,
        )
        assert result.custom_sources == {}
        assert result.resolution == ResolutionDecision.REGISTRY

    def test_llm_custom_sources_filters_empty(self):
        """custom_sources 含空键/空值 → 过滤，不产出空串条目。"""
        result = parse_task(
            "分析 Cursor",
            llm=self._llm({"resolution": "registry", "competitors": ["cursor"], "dimensions": None,
                           "custom_sources": {"home": "https://cursor.com", "": "https://x.com", "pricing": ""}}),
            use_llm=True,
        )
        assert result.custom_sources == {"home": "https://cursor.com"}


class TestParsingRobustness87:
    """设计文档 87 §1.1：task_parser 复用共享 extract/coerce 基建（P0 修复）"""

    @staticmethod
    def _llm_raw(text: str) -> LLMClient:
        return LLMClient(call_func=lambda messages, model: text)

    _PAYLOAD = json.dumps(
        {"resolution": "registry", "competitors": ["cursor"], "dimensions": ["pricing"], "custom_sources": {}}
    )

    def test_fenced_json_parsed(self):
        """§1.1A：```json 围栏输出不再抛 LLMUnavailableError。"""
        llm = self._llm_raw(f"```json\n{self._PAYLOAD}\n```")
        result = parse_task("分析 Cursor", llm=llm, use_llm=True)
        assert result.competitors == ["cursor"]
        assert result.dimensions == ["pricing"]

    def test_prose_prefix_parsed(self):
        """§1.1A：散文前缀（"好的，解析结果如下："）不再抛 LLMUnavailableError。"""
        llm = self._llm_raw(f"好的，解析结果如下：\n{self._PAYLOAD}")
        result = parse_task("分析 Cursor", llm=llm, use_llm=True)
        assert result.competitors == ["cursor"]

    def test_garbage_still_raises(self):
        """完全无 JSON → 仍响亮失败（兜底响亮语义不变）。"""
        llm = self._llm_raw("完全无法解析的内容")
        with pytest.raises(LLMUnavailableError):
            parse_task("分析 Cursor", llm=llm, use_llm=True)

    def test_competitors_str_not_char_iterated(self):
        """§1.1B：competitors 返回字符串 → 整体一项，不按字符迭代成静默垃圾。"""
        llm = self._llm_raw(
            '{"resolution": "registry", "competitors": "Claude Code", "dimensions": null}'
        )
        result = parse_task("分析 Claude Code", llm=llm, use_llm=True)
        assert result.competitors == ["Claude Code"]

    def test_competitors_none_to_empty(self):
        """§1.1B：competitors 返回 null → 空列表（不抛 TypeError）。"""
        llm = self._llm_raw('{"resolution": "chat", "competitors": null, "dimensions": null}')
        result = parse_task("你好", llm=llm, use_llm=True)
        assert result.competitors == []

    def test_competitors_mixed_list_filters_non_str(self):
        """§1.1B：混合 list → 只留非空字符串项。"""
        llm = self._llm_raw(
            '{"resolution": "compare", "competitors": ["cursor", 30, "", "windsurf"], "dimensions": null}'
        )
        result = parse_task("对比", llm=llm, use_llm=True)
        assert result.competitors == ["cursor", "windsurf"]
