"""设计文档 71 §8.4/8.5 — 两阶段任务适配 + 对比推理原则，单测。

覆盖：
① format_hint 枚举归一（normalize_format_hint：别名/枚举/非法→open）；
② build_report_phase2_section：按 plan.format_hint 选报告结构、按 resolution∈{compare,discovery}
   注入对比推理（comparison_reasoning）；open/缺失/N 型 → None；
③ make_plan 侧 lenient 归一（字段存在才归一，非法回退 open，旧 plan 不改）；
④ ReactAgent 注入：first_tool_sink 返回的 phase2 消息在 make_plan 工具回合末拼接进消息流；
⑤ ReactLoop._on_plan：解析 plan 并存 self.plan，命中时返回 phase2 注入段；
⑥ LangGraph report 节点：按 state.plan 注入（langgraph 为 optional extra，未装 skip）。
"""
from __future__ import annotations

import json

from competitor_agent.agent.make_plan import make_plan
from competitor_agent.agent.prompts.react_system import build_report_phase2_section
from competitor_agent.agent.react_agent import ReactAgent
from competitor_agent.agent.react_loop import ReactLoop
from competitor_agent.agent.react_schemas import normalize_format_hint
from competitor_agent.agent.tool_dispatcher import ToolDispatcher
from competitor_agent.llm.client import LLMClient, ToolCall, ToolCallReply

# ---- ① format_hint 归一 ----

class TestNormalizeFormatHint:
    def test_open_default_for_missing(self):
        assert normalize_format_hint(None) == "open"
        assert normalize_format_hint("") == "open"

    def test_enum_passthrough(self):
        assert normalize_format_hint("compare") == "compare"
        assert normalize_format_hint("open") == "open"

    def test_chinese_aliases(self):
        assert normalize_format_hint("对比型") == "compare"
        assert normalize_format_hint("对比") == "compare"
        assert normalize_format_hint("深度单体") == "deep_single"
        assert normalize_format_hint("变化追踪") == "trend_tracking"

    def test_unknown_falls_back_open(self):
        assert normalize_format_hint("随便写") == "open"
        assert normalize_format_hint(123) == "open"


# ---- ② build_report_phase2_section ----

class TestBuildReportPhase2Section:
    def test_none_plan_no_injection(self):
        assert build_report_phase2_section(None) is None

    def test_open_no_injection(self):
        assert build_report_phase2_section({"competitor": "cursor", "format_hint": "open"}) is None

    def test_compare_scaffold(self):
        s = build_report_phase2_section({"competitor": "cursor", "format_hint": "对比型", "resolution": "registry"})
        assert s is not None
        assert "报告结构（本任务类型：compare）" in s
        assert "维度 × 竞品" in s

    def test_compare_resolution_injects_comparison_reasoning(self):
        s = build_report_phase2_section({"competitor": "cursor", "format_hint": "compare", "resolution": "compare"})
        assert s is not None
        assert "对比推理原则" in s
        assert "best-per-dimension" in s

    def test_discovery_resolution_injects_reasoning_even_without_scaffold(self):
        s = build_report_phase2_section({"resolution": "discovery"})
        assert s is not None
        assert "对比推理原则" in s

    def test_deep_single_scaffold(self):
        s = build_report_phase2_section({"competitor": "cursor", "format_hint": "deep_single"})
        assert s and "单一竞品" in s

    def test_trend_scaffold(self):
        s = build_report_phase2_section({"competitor": "cursor", "format_hint": "trend_tracking"})
        assert s and "as_of" in s


# ---- ③ make_plan lenient 归一 ----

class TestMakePlanFormatHintNormalization:
    def test_normalizes_known_alias(self):
        result = make_plan(json.dumps({"competitor": "cursor", "format_hint": "对比型"}, ensure_ascii=False))
        assert json.loads(result)["format_hint"] == "compare"

    def test_unknown_falls_back_open(self):
        result = make_plan(json.dumps({"competitor": "cursor", "format_hint": "随便写"}, ensure_ascii=False))
        assert json.loads(result)["format_hint"] == "open"

    def test_old_plan_without_format_hint_unchanged(self):
        result = make_plan(json.dumps({"competitor": "cursor"}, ensure_ascii=False))
        assert "format_hint" not in json.loads(result)

    def test_non_string_format_hint_rejected_as_before(self):
        result = make_plan(json.dumps({"competitor": "cursor", "format_hint": 123}, ensure_ascii=False))
        assert result.startswith("make_plan 校验失败")


# ---- ④ ReactAgent 注入 ----

def _tool(name: str, args: dict) -> ToolCallReply:
    return ToolCallReply(tool_calls=[ToolCall(id="call_0", name=name, arguments=args)])


def _fin(text: str) -> ToolCallReply:
    return ToolCallReply(content=text)


def _scripted(responses, track=None):
    calls = {"n": 0}

    def fake_llm(messages, model, **kwargs):
        if track is not None:
            track.append(list(messages))
        r = responses[min(calls["n"], len(responses) - 1)]
        calls["n"] += 1
        return r

    return fake_llm


class TestReactAgentPhase2Injection:
    def test_first_tool_sink_return_spliced_into_messages(self):
        track = []
        seen = {}

        def plan_sink(plan_text):
            seen["plan"] = plan_text
            return [{"role": "system", "content": "## 报告结构（本任务类型：compare）\nscaffold"}]

        dispatcher = ToolDispatcher({
            # 真实 make_plan 工具参数键为 plan_json（dispatch 以 **argument 调用）
            "make_plan": lambda plan_json: json.dumps(
                {"competitor": "cursor", "format_hint": "对比型", "resolution": "compare"}, ensure_ascii=False
            ),
        })
        agent = ReactAgent(
            llm=LLMClient(call_func=_scripted(
                [_tool("make_plan", {"plan_json": '{"competitor": "cursor"}'}), _fin("最终报告")], track
            )),
            dispatcher=dispatcher,
        )
        answer = agent.run(
            agent.build_system_prompt(),
            "对比 Cursor 和 Windsurf",
            mandatory_first_tool="make_plan",
            first_tool_sink=plan_sink,
        )
        assert answer == "最终报告"
        assert "cursor" in seen["plan"]  # plan_sink 收到 make_plan 结果（含竞品名）
        # 第二次 LLM 调用前，消息流应已拼接 phase2 system 消息
        assert any(
            m.get("role") == "system" and "报告结构" in m.get("content", "")
            for m in track[1]
        )
        # 顺序：system, user(任务), assistant(make_plan), tool, system(phase2)——phase2 在末位
        roles = [m["role"] for m in track[1]]
        assert roles[-1] == "system"

    def test_no_injection_when_sink_returns_none(self):
        track = []
        agent = ReactAgent(
            llm=LLMClient(call_func=_scripted([_tool("make_plan", {"plan_json": '{"competitor": "cursor"}'}), _fin("ok")], track)),
            dispatcher=ToolDispatcher({"make_plan": lambda plan_json: json.dumps({"competitor": "cursor"})}),
        )
        agent.run(
            agent.build_system_prompt(),
            "分析 Cursor",
            mandatory_first_tool="make_plan",
            first_tool_sink=lambda _: None,
        )
        assert not any(m.get("role") == "system" and "报告结构" in m.get("content", "") for m in track[1])


# ---- ⑤ ReactLoop._on_plan ----

class TestReactLoopOnPlan:
    def _loop(self):
        return ReactLoop(
            agent=ReactAgent(
                llm=LLMClient(call_func=_scripted([_fin("ok")])),
                dispatcher=ToolDispatcher(),
            )
        )

    def test_valid_plan_sets_self_plan_and_returns_section(self):
        loop = self._loop()
        msgs = loop._on_plan(json.dumps({"competitor": "cursor", "format_hint": "compare", "resolution": "compare"}))
        assert loop.plan["competitor"] == "cursor"
        assert msgs is not None
        assert "报告结构（本任务类型：compare）" in msgs[0]["content"]
        assert "对比推理原则" in msgs[0]["content"]
        assert msgs[0]["role"] == "system"

    def test_open_format_returns_none(self):
        loop = self._loop()
        msgs = loop._on_plan(json.dumps({"competitor": "cursor", "format_hint": "open"}))
        assert loop.plan is not None
        assert msgs is None

    def test_invalid_plan_keeps_none_and_returns_none(self):
        loop = self._loop()
        assert loop._on_plan("not json") is None
        assert loop.plan is None
        assert loop._on_plan(json.dumps({"foo": "bar"})) is None
        assert loop.plan is None


# ---- ⑥ LangGraph report 节点（langgraph 可选依赖，未装 skip） ----

class TestLangGraphReportPhase2:
    def test_report_nodes_injects_section_from_plan(self):
        pytest = __import__("pytest")
        pytest.importorskip("langgraph", reason="langgraph 为 optional extra")
        from competitor_agent.agent.langgraph_engine.nodes import make_report_node

        captured = {}

        class _CapLLM:
            def complete(self, messages):
                captured["messages"] = list(messages)
                return "Final Answer: done"

        report_node = make_report_node(_CapLLM(), system_prompt="你是分析报告 Agent")
        report_node({
            "plan": {"competitor": "cursor", "format_hint": "compare", "resolution": "compare"},
            "merged_results": "维度结果",
            "task": "对比 Cursor 和 Windsurf",
        })
        msgs = captured["messages"]
        assert any(
            m.get("role") == "system" and "对比推理原则" in m.get("content", "")
            for m in msgs
        )

    def test_report_node_no_injection_when_open(self):
        pytest = __import__("pytest")
        pytest.importorskip("langgraph", reason="langgraph 为 optional extra")
        from competitor_agent.agent.langgraph_engine.nodes import make_report_node

        captured = {}

        class _CapLLM:
            def complete(self, messages):
                captured["messages"] = list(messages)
                return "done"

        report_node = make_report_node(_CapLLM(), system_prompt="sys")
        report_node({"plan": {"competitor": "cursor", "format_hint": "open"}, "merged_results": "x", "task": "t"})
        assert not any("对比推理原则" in m.get("content", "") for m in captured["messages"])