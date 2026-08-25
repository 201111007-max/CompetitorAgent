"""设计文档 56 M1①：kb_recall 循环内知识库取回工具

- 闭包检索返回片段拼接 / 空库与未装配的可读信息（工具面稳定不缺口）
- competitor 懒绑定（plan 前空串全局检索、plan 后同竞品优先）
- 子 Agent 按 (competitor, dimension) 绑定（维度匹配前置）
- 结果截断到 collector.max_content_chars
- 回灌路径 wrap_untrusted 包裹（复用既有机制，零新增暴露面）
- 走 extra_tools：不进 TOOLS/TOOL_SPECS（MCP 工具面零变化）
"""
from __future__ import annotations

import competitor_agent.mcp_server.tools as mcp_tools
from competitor_agent.agent.react_agent import ReactAgent
from competitor_agent.agent.tool_dispatcher import ToolDispatcher
from competitor_agent.config.loader import load_config
from competitor_agent.facade.api import CompetitorAnalysisAPI
from competitor_agent.knowledge_base.competitor_store import CompetitorStore, TextChunk
from competitor_agent.llm.client import LLMClient, ToolCall, ToolCallReply


def _api(tmp_path, *, enable_rag: bool = True, max_content_chars: int | None = None) -> CompetitorAnalysisAPI:
    cfg = load_config()
    if max_content_chars is not None:
        cfg.collector.max_content_chars = max_content_chars
    store = CompetitorStore(data_dir=tmp_path / "kb") if enable_rag else None
    return CompetitorAnalysisAPI(
        llm=None,
        use_llm=False,
        enable_memory=False,
        enable_rag=enable_rag,
        rag_store=store,
        config=cfg,
    )


def _seed(api: CompetitorAnalysisAPI) -> None:
    for chunk in (
        TextChunk("c1", "cursor", "pricing", "cursor pro plan costs $20 per month", "https://cursor.com/pricing"),
        TextChunk("c2", "claude", "pricing", "claude pro plan costs $20 per month", ""),
        TextChunk("c3", "cursor", "feature", "cursor supports ai autocomplete", ""),
    ):
        api._store.add(chunk)


class TestKbRecallClosure:
    def test_returns_joined_snippets(self, tmp_path):
        api = _api(tmp_path)
        _seed(api)
        kb = api._build_kb_recall(lambda: "")
        out = kb.func("cursor pro plan")
        assert "[cursor/pricing]" in out
        assert "（来源: https://cursor.com/pricing）" in out
        assert "costs $20 per month" in out

    def test_empty_store_readable_message(self, tmp_path):
        api = _api(tmp_path)
        kb = api._build_kb_recall(lambda: "")
        assert kb.func("anything") == "知识库暂无可检索内容。"

    def test_retriever_not_assembled_readable_message(self, tmp_path):
        api = _api(tmp_path, enable_rag=False)
        kb = api._build_kb_recall(lambda: "")
        assert "知识库暂无可检索内容" in kb.func("anything")

    def test_competitor_lazy_binding(self, tmp_path):
        """plan 前（空串）全局检索；plan 后同竞品片段前置。"""
        api = _api(tmp_path)
        _seed(api)
        box = {"competitor": ""}
        kb = api._build_kb_recall(lambda: box["competitor"])
        before = kb.func("pro plan costs $20")
        assert before  # 全局检索：两条 pro plan 都可达
        box["competitor"] = "cursor"  # 模拟 make_plan 落地后回填
        after = kb.func("pro plan costs $20")
        assert after.splitlines()[0].startswith("- [cursor/"), "同竞品片段应前置"

    def test_dimension_binding_prefers_matching_dimension(self, tmp_path):
        """子 Agent 按 (competitor, dimension) 绑定：维度匹配片段前置。"""
        api = _api(tmp_path)
        _seed(api)
        kb = api._build_kb_recall(lambda: "cursor", "pricing")
        out = kb.func("cursor")
        assert out.splitlines()[0].startswith("- [cursor/pricing]")

    def test_result_truncated_to_max_content_chars(self, tmp_path):
        api = _api(tmp_path, max_content_chars=50)
        _seed(api)
        kb = api._build_kb_recall(lambda: "")
        assert len(kb.func("cursor pro plan")) <= 50

    def test_tool_spec_contract(self, tmp_path):
        """描述含使用纪律；schema 要求 query（供 build_openai_tools 下发）。"""
        api = _api(tmp_path)
        spec = api._build_kb_recall(lambda: "")
        assert spec.name == "kb_recall"
        assert "仅当需要回溯" in spec.description
        assert spec.params_schema["required"] == ["query"]

    def test_not_in_mcp_tools(self):
        """kb_recall 不进 TOOLS/TOOL_SPECS（MCP 工具面零变化，设计文档 56 §2.4）。"""
        assert "kb_recall" not in mcp_tools.TOOLS
        assert "kb_recall" not in mcp_tools.TOOL_SPECS


class TestKbRecallUntrustedWrap:
    def test_recall_result_wrapped_as_untrusted(self, tmp_path):
        """kb_recall 结果回灌时经 wrap_untrusted 包裹（知识库内容源自外部页面）。"""
        api = _api(tmp_path)
        _seed(api)
        spec = api._build_kb_recall(lambda: "")
        dispatcher = ToolDispatcher()
        dispatcher.register("kb_recall", spec.func, spec=spec)
        calls: list[list[dict]] = []

        def scripted(messages, model=None, **kwargs):
            calls.append([dict(m) for m in messages])
            if len(calls) == 1:
                return ToolCallReply(tool_calls=[ToolCall(
                    id="call_0", name="kb_recall", arguments={"query": "pro plan"}
                )])
            return ToolCallReply(content="完成")

        agent = ReactAgent(
            llm=LLMClient(call_func=scripted), dispatcher=dispatcher
        )
        agent.run(agent.build_system_prompt(), "任务")
        tool_msgs = [m["content"] for m in calls[-1] if m["role"] == "tool"]
        assert tool_msgs, "kb_recall 结果应以 tool 角色消息回灌"
        assert "<untrusted_data" in tool_msgs[0]
        assert "costs $20 per month" in tool_msgs[0]


class TestLeadWiring:
    def test_react_loop_registers_kb_recall(self, tmp_path):
        """Lead dispatcher 工具面含 kb_recall（extra_tools 注入，描述可见）。"""
        api = _api(tmp_path)
        loop = api._react_loop("分析 cursor 定价", None)
        dispatcher = loop._agent._dispatcher
        assert dispatcher.validate_tool("kb_recall")
        assert "kb_recall" in dispatcher.get_tool_descriptions()

    def test_react_loop_max_history_steps_from_config(self, tmp_path):
        """Lead max_history_steps 配置化注入（设计文档 62 §3.8）：lead.max_history_steps → Lead ReactLoop。"""
        api = _api(tmp_path)
        api._config.lead.max_history_steps = 3
        loop = api._react_loop("分析 cursor 定价", None)
        assert loop._max_history_steps == 3
