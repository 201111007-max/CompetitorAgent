"""设计文档 56 M2：核验事实 pinning

- extract_verified_facts：只收 validate_facts/detect_conflict 核验通过结论，
  按 _VERIFY_NUMERIC_KEYS 键空间抽一行一条；失败/无关工具不抽取
- pinned 段：压缩后作为独立 user 消息固定在摘要块之后，永不折叠/滚出
- 封顶：行数（_PINNED_MAX_LINES）+ 单行字符（_PINNED_LINE_CHARS），超限只保最近核验
- 无核验事实时不插入空段
"""
from __future__ import annotations

import json

from competitor_agent.agent.react_agent import (
    _PINNED_LINE_CHARS,
    _PINNED_MAX_LINES,
    _PINNED_MSG_PREFIX,
    ReactAgent,
)
from competitor_agent.agent.review_tools import extract_verified_facts


def _rec(tool: str, args: dict, brief: str) -> dict:
    return {"tool": tool, "args": args, "result_brief": brief, "url": ""}


class TestExtractVerifiedFacts:
    def test_validate_facts_pass_extracts_numeric_keys(self):
        rec = _rec(
            "validate_facts",
            {"details_json": {"monthly_price_usd": 20, "stars": 12500, "note": "x"}},
            "真值核对通过：details 数值均可回溯到原文证据，无冲突。",
        )
        lines = extract_verified_facts(rec)
        assert "monthly_price_usd=20（validate_facts 核验通过）" in lines
        assert "stars=12500（validate_facts 核验通过）" in lines
        assert all("note" not in line for line in lines), "非键空间字段不抽取"

    def test_validate_facts_json_string_args(self):
        """文本协议下 args 可能是 JSON 字符串，同样可抽取。"""
        rec = _rec(
            "validate_facts",
            {"details_json": json.dumps({"score": 9.0})},
            "真值核对通过：details 数值均可回溯到原文证据，无冲突。",
        )
        assert extract_verified_facts(rec) == ["score=9（validate_facts 核验通过）"]

    def test_validate_facts_pass_without_numeric_keys_keeps_conclusion(self):
        rec = _rec(
            "validate_facts",
            {"details_json": {"note": "无数值"}},
            "真值核对通过：details 数值均可回溯到原文证据，无冲突。",
        )
        assert extract_verified_facts(rec) == ["details 数值均可回溯到原文证据（validate_facts 核验通过）"]

    def test_validate_facts_conflict_not_pinned(self):
        """核验未通过（有冲突）不是已核验事实，不 pin。"""
        rec = _rec(
            "validate_facts",
            {"details_json": {"monthly_price_usd": 20}},
            "真值核对发现 1 处数值与原文不符（声称自原文却找不到），请重新抓取核验或修正 details，勿保留未证实数值。",
        )
        assert extract_verified_facts(rec) == []

    def test_detect_conflict_pass(self):
        rec = _rec(
            "detect_conflict",
            {"dimensions_json": [{"dimension": "pricing", "monthly_price_usd": 20}]},
            "跨维度冲突检测通过：各维度引用的同源事实值一致。",
        )
        lines = extract_verified_facts(rec)
        assert "monthly_price_usd=20（detect_conflict 核验通过）" in lines

    def test_detect_conflict_pass_without_keys_keeps_conclusion(self):
        rec = _rec(
            "detect_conflict",
            {"dimensions_json": [{"dimension": "feature"}]},
            "跨维度冲突检测通过：各维度引用的同源事实值一致。",
        )
        assert extract_verified_facts(rec) == ["各维度引用的同源事实值一致（detect_conflict 核验通过）"]

    def test_unrelated_tool_not_extracted(self):
        rec = _rec("web_extract", {"url": "https://a.com"}, "页面正文")
        assert extract_verified_facts(rec) == []


def _steps_messages(n: int) -> list[dict]:
    """native turn 形状：assistant(tool_calls) + tool 角色消息（设计文档 60）。"""
    messages = [{"role": "system", "content": "sys"}, {"role": "user", "content": "任务"}]
    for i in range(n):
        messages.append(
            {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": f"call_{i}",
                        "type": "function",
                        "function": {"name": "echo", "arguments": json.dumps({"v": i})},
                    }
                ],
            }
        )
        messages.append(
            {
                "role": "tool",
                "tool_call_id": f"call_{i}",
                "content": f"<untrusted_data>\nres{i}\n</untrusted_data>",
            }
        )
    return messages


def _pinned_of(messages: list[dict]) -> str:
    return next(
        (m["content"] for m in messages
         if m["role"] == "user" and m["content"].startswith(_PINNED_MSG_PREFIX)),
        "",
    )


class TestPinnedSegment:
    def test_pinned_after_summary_and_survives_recompression(self):
        """pinned 段固定在摘要块后；再次压缩时不被折叠、不重复（重建而非累积）。"""
        pinned = ["monthly_price_usd=20（validate_facts 核验通过）"]
        out, lines = ReactAgent._compress_history(
            _steps_messages(6), max_history_steps=2, pinned_facts=pinned
        )
        pinned_text = _pinned_of(out)
        assert pinned_text and "monthly_price_usd=20" in pinned_text
        summary_idx = next(
            i for i, m in enumerate(out)
            if m["role"] == "user" and m["content"].startswith("已压缩的旧工具步摘要")
        )
        pinned_idx = next(
            i for i, m in enumerate(out)
            if m["role"] == "user" and m["content"].startswith(_PINNED_MSG_PREFIX)
        )
        assert pinned_idx == summary_idx + 1, "pinned 段固定在摘要块之后"
        # 再次压缩（更多步骤）：pinned 仍在且只有一份
        out2 = out + _steps_messages(2)[2:]
        out2, _ = ReactAgent._compress_history(
            out2, max_history_steps=2, summary_lines=lines, pinned_facts=pinned
        )
        pinned_msgs = [
            m for m in out2
            if m["role"] == "user" and m["content"].startswith(_PINNED_MSG_PREFIX)
        ]
        assert len(pinned_msgs) == 1
        assert "monthly_price_usd=20" in pinned_msgs[0]["content"]

    def test_pinned_caps_lines_and_chars(self):
        """行数封顶只保最近核验；单行字符封顶。"""
        pinned = [f"fact_{i} 核验通过" for i in range(10)]
        pinned.append("x" * 200)
        msg = ReactAgent._pinned_message(pinned)
        assert msg is not None
        body = msg["content"].splitlines()[1:]
        assert len(body) == _PINNED_MAX_LINES
        assert "fact_0" not in msg["content"] and "fact_2" not in msg["content"], "旧核验滚出"
        assert "fact_9" in msg["content"]
        assert all(len(line) <= 2 + _PINNED_LINE_CHARS for line in body), "单行截断（含 '- ' 前缀）"

    def test_no_pinned_message_without_facts(self):
        """无核验事实时不插入空段（None 与空列表同语义）。"""
        assert ReactAgent._pinned_message(None) is None
        assert ReactAgent._pinned_message([]) is None
        out, _ = ReactAgent._compress_history(
            _steps_messages(6), max_history_steps=2, pinned_facts=[]
        )
        assert not _pinned_of(out)
