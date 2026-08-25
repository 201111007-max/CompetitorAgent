"""设计文档 62 M1 — delegate 通用委派契约扩展单测。

覆盖：``delegate(dimensions, task, parallel, reason)`` 的新契约——
- parallel=True（默认）：批量 spawn 后台并发，结果合并回填（保持 doc 49 行为）；
- parallel=False：逐个 spawn+await 串行，同样正确合并；
- reason：Lead 调度意图，仅可观测（日志），不影响结果；
- 未注册维度被过滤（registry 校验），全部未命中给出可读错误。
"""
from __future__ import annotations

import pytest

from competitor_agent.agent.delegate_tool import (
    DelegateRunner,
    SubagentRuntime,
    make_delegate_tool,
)


class _FakeRegistry:
    """最小 registry 替身：维度可委派 + competitor 命名空间兜底（make_delegate_tool 依赖 resolve/get/names）。"""

    _COMPETITOR = object()

    def __init__(self) -> None:
        self._dims = {"pricing": object(), "feature": object(), "performance": object()}

    def get(self, name: str) -> object:
        return self._dims.get(name)

    def resolve(self, name: str) -> object:
        return self._dims.get(name) or self._COMPETITOR

    def names(self) -> list[str]:
        return list(self._dims)


@pytest.fixture
def runner() -> DelegateRunner:
    def runtime_factory(name: str) -> SubagentRuntime:
        return SubagentRuntime(name=name, run=lambda task: f"<result {name}>")

    return DelegateRunner(runtime_factory, max_concurrent=2)


@pytest.fixture
def delegate(runner: DelegateRunner) -> object:
    tool = make_delegate_tool(runner, registry=_FakeRegistry())
    return tool


def test_delegate_parallel_merges_all_results(runner: DelegateRunner, delegate: object) -> None:
    """parallel=True（默认）：批量并发 spawn，全部结果合并回填。"""
    text = delegate(dimensions=["pricing", "feature", "performance"], task="分析 X")
    assert "[维度子 Agent 结果: pricing | 状态: 完成]" in text
    assert "<result pricing>" in text
    assert "<result feature>" in text
    assert "<result performance>" in text


def test_delegate_serial_merges_all_results(runner: DelegateRunner, delegate: object) -> None:
    """parallel=False：逐个 spawn+await 串行，同样正确合并。"""
    text = delegate(
        dimensions=["pricing", "feature"],
        task="分析 X",
        parallel=False,
        reason="预算有限，串行委派",
    )
    assert "<result pricing>" in text
    assert "<result feature>" in text


def test_delegate_parallel_true_explicit(
    runner: DelegateRunner, delegate: object
) -> None:
    """parallel=True 显式传入，与默认一致。"""
    text = delegate(
        dimensions=["pricing"], task="分析 X", parallel=True, reason="候选多需并行"
    )
    assert "<result pricing>" in text


def test_delegate_candidate_names_delegate_via_competitor(
    runner: DelegateRunner, delegate: object
) -> None:
    """设计文档 62 §3.2：未注册维度名（候选竞品）经 competitor 命名空间可委派。"""
    text = delegate(dimensions=["cursor", "cline"], task="分析这些候选")
    assert "<result cursor>" in text
    assert "<result cline>" in text

def test_delegate_candidate_parallel_false(
    runner: DelegateRunner, delegate: object
) -> None:
    """候选委派同样支持串行走法。"""
    text = delegate(dimensions=["cursor"], task="分析 X", parallel=False)
    assert "<result cursor>" in text


def test_delegate_mixed_empty_error(runner: DelegateRunner, delegate: object) -> None:
    """空清单返回可读错误。"""
    text = delegate(dimensions=[], task="分析 X")
    assert "未指定可委派目标" in text


def test_delegate_runner_concurrency_cap(runner: DelegateRunner) -> None:
    """并发细节不暴露给 Lead，由 DelegateRunner 默认上限收敛（对齐 budget.max_parallel）。"""
    assert runner._max_concurrent == 2