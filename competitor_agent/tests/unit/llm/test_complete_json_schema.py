"""LLMClient.complete_json 结构化补全单测（设计文档 34）

覆盖：schema 校验通过/失败、修复重试（错误回灌 prompt）、retries 耗尽抛错、
null 放行、嵌套数组 items 校验、enum 校验、boolean≠number、旧语义（无 schema）兼容。
"""
from __future__ import annotations

import json

import pytest
from competitor_agent.interfaces.exceptions import LLMUnavailableError
from competitor_agent.llm.client import LLMClient

_SCHEMA = {
    "type": "object",
    "required": ["summary", "details", "confidence"],
    "properties": {
        "summary": {"type": "string"},
        "confidence": {"type": "number"},
        "details": {"type": "object"},
    },
}


class _Scripted:
    """按调用次数返回脚本化的 call_func 输出（支持 callable 动态生成 + 记录 messages）"""

    def __init__(self, script):
        self._script = script
        self.calls = []
        self.n = 0

    def __call__(self, messages, model=None):
        self.n += 1
        self.calls.append(messages)
        if callable(self._script):
            return self._script(messages, self.n)
        out = self._script[min(self.n - 1, len(self._script) - 1)]
        if callable(out):
            return out(messages, self.n)
        return out


class TestCompleteJsonSchema:
    def test_valid_json_no_schema_keeps_old_semantics(self):
        s = _Scripted([json.dumps({"ok": True})])
        client = LLMClient(call_func=s)
        assert client.complete_json([{"role": "user", "content": "hi"}]) == {"ok": True}
        assert s.n == 1

    def test_valid_json_passes_schema(self):
        s = _Scripted([json.dumps({"summary": "s", "details": {}, "confidence": 0.9})])
        client = LLMClient(call_func=s)
        result = client.complete_json([{"role": "user", "content": "x"}], schema=_SCHEMA)
        assert result["confidence"] == 0.9
        assert s.n == 1

    def test_missing_required_retries_then_raises(self):
        bad = json.dumps({"summary": "s", "details": {}})  # 缺 confidence
        s = _Scripted([bad])
        client = LLMClient(call_func=s)
        with pytest.raises(LLMUnavailableError):
            client.complete_json([{"role": "user", "content": "x"}], schema=_SCHEMA)
        assert s.n == 3  # 1 次原始 + 2 次修复重试（retries=2）

    def test_repair_after_invalid_json(self):
        def script(messages, n):
            return (
                "not-json"
                if n == 1
                else json.dumps({"summary": "s", "details": {}, "confidence": 0.8})
            )

        s = _Scripted(script)
        client = LLMClient(call_func=s)
        result = client.complete_json([{"role": "user", "content": "x"}], schema=_SCHEMA)
        assert result["summary"] == "s"
        assert s.n == 2

    def test_repair_prompt_carries_schema_error(self):
        def script(messages, n):
            return (
                json.dumps({"summary": "s", "details": {}, "confidence": "high"})  # 类型错
                if n == 1
                else json.dumps({"summary": "s", "details": {}, "confidence": 0.8})
            )

        s = _Scripted(script)
        client = LLMClient(call_func=s)
        result = client.complete_json([{"role": "user", "content": "x"}], schema=_SCHEMA)
        assert result["confidence"] == 0.8
        assert s.n == 2
        repair = s.calls[1][-1]
        assert repair["role"] == "user"
        assert "confidence" in repair["content"]  # 错误信息已回灌
        assert "$.confidence" in repair["content"]

    def test_enum_validation_fails(self):
        schema = {
            "type": "object",
            "properties": {"polarity": {"type": "string", "enum": ["pos", "neg", "neu"]}},
        }
        s = _Scripted([json.dumps({"polarity": "great"})])
        client = LLMClient(call_func=s)
        with pytest.raises(LLMUnavailableError):
            client.complete_json([{"role": "user", "content": "x"}], schema=schema)

    def test_null_passes_any_type(self):
        schema = {"type": "object", "properties": {"monthly_price_usd": {"type": "number"}}}
        s = _Scripted([json.dumps({"monthly_price_usd": None})])
        client = LLMClient(call_func=s)
        assert client.complete_json([{"role": "user", "content": "x"}], schema=schema) == {
            "monthly_price_usd": None
        }

    def test_array_items_type_validation(self):
        schema = {
            "type": "object",
            "properties": {"features": {"type": "array", "items": {"type": "string"}}},
        }
        s = _Scripted([json.dumps({"features": ["a", 42]})])
        client = LLMClient(call_func=s)
        with pytest.raises(LLMUnavailableError):
            client.complete_json([{"role": "user", "content": "x"}], schema=schema)

    def test_boolean_is_not_number(self):
        schema = {"type": "object", "properties": {"confidence": {"type": "number"}}}
        s = _Scripted([json.dumps({"confidence": True})])
        client = LLMClient(call_func=s)
        with pytest.raises(LLMUnavailableError):
            client.complete_json([{"role": "user", "content": "x"}], schema=schema)

    def test_retries_zero_fails_on_first_bad(self):
        s = _Scripted([json.dumps({"nope": 1})])
        client = LLMClient(call_func=s)
        with pytest.raises(LLMUnavailableError):
            client.complete_json(
                [{"role": "user", "content": "x"}], schema=_SCHEMA, retries=0
            )
        assert s.n == 1

    def test_retries_greater_than_zero_recover(self):
        # 第 1、2 次都坏，第 3 次好 → retries=2 时（共 3 次尝试）恢复
        def script(messages, n):
            if n < 3:
                return json.dumps({"summary": "s", "details": {}})
            return json.dumps({"summary": "s", "details": {}, "confidence": 0.5})

        s = _Scripted(script)
        client = LLMClient(call_func=s)
        result = client.complete_json([{"role": "user", "content": "x"}], schema=_SCHEMA)
        assert result["confidence"] == 0.5
        assert s.n == 3
