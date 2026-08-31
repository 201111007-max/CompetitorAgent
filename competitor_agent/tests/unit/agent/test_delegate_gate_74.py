"""设计文档 74 §3.2 + E4 — 子 Agent 结果「最小成功校验」gate 单测。

覆盖：空/退化结果 → 标 empty（不冒泡成功、不收集）；重试 1 次仍空 → empty；
重试成功 → done；合法 REPORT_SCHEMA → done + 收集；过短自由文本 → empty。
"""

from __future__ import annotations

import json

from competitor_agent.agent.delegate_tool import (
    DelegateRunner,
    SubagentRuntime,
    make_delegate_tool,
)


class _FakeRegistry:
    _COMPETITOR = object()

    def __init__(self) -> None:
        self._dims = {"pricing": object(), "feature": object()}

    def get(self, name: str) -> object:
        return self._dims.get(name)

    def resolve(self, name: str) -> object:
        return self._dims.get(name) or self._COMPETITOR

    def names(self) -> list[str]:
        return list(self._dims)


def _runner_with(script: list[str]) -> tuple[DelegateRunner, list[int]]:
    calls: list[int] = []

    def runtime_factory(name: str) -> SubagentRuntime:
        def run(task: str) -> str:
            calls.append(1)
            idx = len(calls) - 1
            return script[min(idx, len(script) - 1)] if script else ""

        return SubagentRuntime(name=name, run=run)

    return DelegateRunner(runtime_factory, max_concurrent=2), calls


def test_empty_result_flagged_and_not_collected() -> None:
    runner, _calls = _runner_with([""])
    collector: dict[str, dict] = {}
    tool = make_delegate_tool(runner, registry=_FakeRegistry(), collector=collector)
    text = tool(dimensions=["pricing"], task="分析 X")
    assert "状态: 空结果" in text
    assert collector == {}
    assert runner.running_count() == 0


def test_retry_once_then_success() -> None:
    runner, calls = _runner_with(["", "<result ok 足够长的有效输出，超过十六个字符阈值>"])
    tool = make_delegate_tool(runner, registry=_FakeRegistry())
    text = tool(dimensions=["pricing"], task="分析 X")
    assert "状态: 完成" in text
    assert "<result ok" in text
    assert len(calls) == 2, "空结果应重试 1 次"


def test_retry_once_still_empty() -> None:
    runner, calls = _runner_with(["", ""])
    collector: dict[str, dict] = {}
    tool = make_delegate_tool(runner, registry=_FakeRegistry(), collector=collector)
    text = tool(dimensions=["pricing"], task="分析 X")
    assert "状态: 空结果" in text
    assert collector == {}
    assert len(calls) == 2, "重试恰好 1 次后仍空"


def test_degenerate_schema_empty_dimensions_flagged() -> None:
    empty_schema = json.dumps({"competitor": "cursor", "dimensions": []})
    runner, calls = _runner_with([empty_schema, empty_schema])
    collector: dict[str, dict] = {}
    tool = make_delegate_tool(runner, registry=_FakeRegistry(), collector=collector)
    text = tool(dimensions=["cursor"], task="分析 X")
    assert "状态: 空结果" in text
    assert collector == {}
    assert len(calls) == 2


def test_valid_schema_collected() -> None:
    valid = json.dumps(
        {
            "competitor": "cursor",
            "dimensions": [
                {
                    "dimension": "pricing",
                    "summary": "Cursor Pro 订阅 $20/月，长度远大于 16 字符阈值。",
                    "details": {},
                    "confidence": 0.8,
                    "evidence_urls": ["https://cursor.com/pricing"],
                }
            ],
        }
    )
    runner, calls = _runner_with([valid])
    collector: dict[str, dict] = {}
    tool = make_delegate_tool(runner, registry=_FakeRegistry(), collector=collector)
    text = tool(dimensions=["cursor"], task="分析 X")
    assert "状态: 完成" in text
    assert collector["cursor"]["dimensions"][0]["dimension"] == "pricing"
    assert len(calls) == 1, "合法结果不重试"


def test_short_free_text_flagged_empty() -> None:
    runner, calls = _runner_with(["ok", "ok"])
    tool = make_delegate_tool(runner, registry=_FakeRegistry())
    text = tool(dimensions=["pricing"], task="分析 X")
    assert "状态: 空结果" in text
    assert len(calls) == 2


def test_error_json_flagged_empty() -> None:
    """复查修复：错误形态 JSON（{"error": ...}）判退化（空结果），避免"完成"却静默不收集。"""
    err = '{"error": "rate limited, please retry later"}'
    runner, calls = _runner_with([err, err])
    collector: dict[str, dict] = {}
    tool = make_delegate_tool(runner, registry=_FakeRegistry(), collector=collector)
    text = tool(dimensions=["cursor"], task="分析 X")
    assert "状态: 空结果" in text
    assert collector == {}
    assert len(calls) == 2
