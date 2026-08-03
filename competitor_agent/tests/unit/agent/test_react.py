"""agent 层单测：response_parser / tool_dispatcher / react_agent / react_loop"""
from competitor_agent.agent import (
    ReactAgent,
    ReactLoop,
    ResponseParser,
    StepType,
    ToolDispatcher,
)
from competitor_agent.domain_types.events import ProgressEvent
from competitor_agent.llm.client import LLMClient


class TestResponseParser:
    def test_parse_action_tag(self):
        out = 'Thought: 需要查定价\n<action>web_extract({"url": "https://x.com"})</action>'
        step = ResponseParser().parse(out)
        assert step.step_type == StepType.ACTION
        assert step.tool_name == "web_extract"
        assert step.tool_args["url"] == "https://x.com"

    def test_parse_action_line(self):
        out = "Thought: 查一下\nAction: web_extract\nArgs: {\"url\": \"https://y.com\"}"
        step = ResponseParser().parse(out)
        assert step.step_type == StepType.ACTION
        assert step.tool_name == "web_extract"
        assert step.tool_args["url"] == "https://y.com"

    def test_parse_final_answer_line(self):
        step = ResponseParser().parse("Thought: 完成\nFinal Answer: 定价 $20/mo")
        assert step.step_type == StepType.FINAL_ANSWER
        assert step.final_answer == "定价 $20/mo"

    def test_parse_final_answer_tag(self):
        step = ResponseParser().parse("分析完成\n<final_answer>结论</final_answer>")
        assert step.step_type == StepType.FINAL_ANSWER
        assert step.final_answer == "结论"

    def test_parse_pure_thought(self):
        step = ResponseParser().parse("我先想想需要什么数据")
        assert step.step_type == StepType.THOUGHT

    def test_action_line_without_args(self):
        step = ResponseParser().parse("Action: web_extract")
        assert step.step_type == StepType.ACTION
        assert step.tool_args == {}


class TestToolDispatcher:
    def test_register_and_dispatch(self):
        d = ToolDispatcher()
        d.register("add", lambda a, b: a + b)
        assert d.dispatch("add", {"a": 1, "b": 2}) == "3"

    def test_unknown_tool_raises(self):
        d = ToolDispatcher()
        try:
            d.dispatch("nope", {})
            assert False, "应抛 ValueError"
        except ValueError:
            pass

    def test_validate_tool(self):
        d = ToolDispatcher()
        d.register("x", lambda: "ok")
        assert d.validate_tool("x")
        assert not d.validate_tool("y")

    def test_descriptions(self):
        d = ToolDispatcher()
        d.register("web_extract", lambda url: "")
        desc = d.get_tool_descriptions()
        assert "web_extract" in desc

    def test_tool_count(self):
        d = ToolDispatcher({"a": lambda: "", "b": lambda: ""})
        assert d.tool_count == 2


class TestReactAgent:
    def _make_agent(self, responses, tools=None):
        calls = {"n": 0}

        def fake_llm(messages, model):
            r = responses[min(calls["n"], len(responses) - 1)]
            calls["n"] += 1
            return r

        return ReactAgent(
            llm=LLMClient(call_func=fake_llm),
            dispatcher=tools or ToolDispatcher({"web_extract": lambda url: "fetched"}),
        )

    def test_run_reaches_final_answer(self):
        agent = self._make_agent([
            'Thought: 先抓页面\n<action>web_extract({"url": "https://x.com"})</action>',
            "Final Answer: 页面已抓取",
        ])
        answer = agent.run(agent.build_system_prompt(), "分析定价")
        assert answer == "页面已抓取"

    def test_run_handles_unknown_tool(self):
        agent = self._make_agent([
            'Thought: 用不存在的工具\n<action>ghost_tool({})</action>',
            "Final Answer: 完成",
        ])
        answer = agent.run(agent.build_system_prompt(), "任务")
        assert answer == "完成"

    def test_run_max_steps_returns_warning(self):
        agent = self._make_agent([
            "Thought: 想想",
            "Thought: 再想想",
            "Thought: 继续想",
            "Thought: 还想",
            "Thought: 再想一下",
            "Thought: 不断想",
            "Thought: 一直想",
        ])
        answer = agent.run(agent.build_system_prompt(), "任务", max_steps=3)
        assert "最大推理步数" in answer

    def test_system_prompt_contains_tools(self):
        agent = self._make_agent(["Final Answer: x"])
        assert "web_extract" in agent.build_system_prompt()


class TestReactLoop:
    def test_emits_events_and_returns_answer(self):
        events = []

        def sink(e: ProgressEvent):
            events.append(e)

        agent = ReactAgent(
            llm=LLMClient(call_func=lambda messages, model: "Final Answer: 结论"),
            dispatcher=ToolDispatcher(),
        )
        loop = ReactLoop(agent, event_sink=sink)
        answer = loop.run("分析 cursor")
        assert answer == "结论"
        assert any(e.event == "phase_start" for e in events)
        assert any(e.event == "phase_complete" for e in events)