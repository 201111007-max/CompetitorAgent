"""记忆摘要压缩与相关度召回单测（设计文档 35 §5）

- summarize/compress：高置信结论抽取、超限折叠保全文、get_history 无损
- recent_context 相关度召回：query 命中相关旧结论而非"最近 N 条"；注入内容较全文精简
- skill 语义化：method 沉淀/回传/prompt 注入；兼容旧字段（method 默认空）
- evolution 归纳：note_pattern/retrieve_patterns 往返；不污染成功率统计
- 主流程注入：memory_context 到达分析器 prompt
"""
from __future__ import annotations

from competitor_agent.agent.prompts.react_system import enrich_prompt
from competitor_agent.interfaces.context import AnalysisSession
from competitor_agent.llm.client import LLMClient, ToolCallReply
from competitor_agent.memory import (
    EvolutionMemory,
    FourLayerMemory,
    SessionArchive,
    SessionSummary,
    SkillStore,
    compress_archive,
    summarize_session,
)


def _raw(dimensions, pending=None, markdown="", competitor="cursor"):
    return {
        "markdown_report": markdown or "# cursor 报告\n正文内容若干行用于占位。",
        "terminal_state": "success",
        "dimension_count": len(dimensions),
        "competitor_name": competitor,
        "created_at": "2026-08-15T00:00:00Z",
        "dimensions": dimensions,
        "pending_gaps": pending or [],
    }


def _dim(dimension, summary, confidence):
    return {"dimension": dimension, "summary": summary, "confidence": confidence}


def _session_dict(
    session_id,
    competitor="cursor",
    dimensions=None,
    pending=None,
    markdown="",
    created_at="2026-08-15T00:00:00Z",
) -> dict:
    return {
        "task": "t",
        "competitor_name": competitor,
        "session_id": session_id,
        "created_at": created_at,
        "raw": _raw(dimensions or [], pending or [], markdown, competitor),
    }


def _session(session_id, competitor="cursor", dimensions=None, pending=None, markdown="", created_at="2026-08-15T00:00:00Z"):
    return AnalysisSession(
        task="t",
        competitor_name=competitor,
        session_id=session_id,
        created_at=created_at,
        raw=_raw(dimensions or [], pending or [], markdown, competitor),
    )


# ── 1. summarize_session（设计文档 35 §3.1 单测） ──────────────────────


class TestSummarize:
    def test_extracts_high_confidence_conclusions(self):
        s = summarize_session(
            _session_dict(
                "s1",
                dimensions=[
                    _dim("pricing", "Pro $20 per month", 0.9),
                    _dim("feature", "speculative guess", 0.3),
                    _dim("performance", "SWE-bench 45%", 0.0),
                ],
            )
        )
        assert s.dimensions == ["pricing", "feature", "performance"]
        assert s.key_conclusions == ["pricing: Pro $20 per month"], "仅高置信结论入摘要"
        assert s.competitor == "cursor"
        assert s.session_id == "s1"

    def test_pending_gaps_and_legacy_fallback(self):
        s = summarize_session(
            _session_dict("s2", dimensions=[], pending=["roadmap"], markdown="## 分析结果\n只有这一行正文")
        )
        assert s.pending_gaps == ["roadmap"]
        # 无结构化结论（历史归档）→ 回退 Markdown 首行，保证可检索
        assert s.key_conclusions and "分析结果" in s.key_conclusions[0]

    def test_max_conclusions_cap(self):
        dims = [_dim(f"d{i}", f"conclusion-{i}", 0.9) for i in range(8)]
        s = summarize_session(_session_dict("s3", dimensions=dims), max_conclusions=3)
        assert len(s.key_conclusions) == 3

    def test_to_dict_from_dict_roundtrip(self):
        s = summarize_session(_session_dict("s4", dimensions=[_dim("pricing", "x", 0.9)], pending=["roadmap"]))
        restored = SessionSummary.from_dict(s.to_dict())
        assert restored == s


# ── 2. compress_archive（设计文档 35 §3.1） ───────────────────────────


class TestCompressArchive:
    def _entries(self, n, keep_full=2, summarize_rest=True):
        entries = [_session_dict(f"s{i}") for i in range(n)]
        return compress_archive(entries, keep_full=keep_full, summarize_rest=summarize_rest)

    def test_keeps_recent_full_folds_older(self):
        ctx = self._entries(8, keep_full=2)
        assert len(ctx) == 8
        assert [e["type"] for e in ctx[:2]] == ["session", "session"]
        assert all(e["type"] == "summary" for e in ctx[2:])
        assert all(e["summary"]["session_id"] == f"s{i}" for i, e in enumerate(ctx))

    def test_summarize_rest_false_drops_older(self):
        ctx = self._entries(8, keep_full=2, summarize_rest=False)
        assert len(ctx) == 2
        assert all(e["type"] == "session" for e in ctx)

    def test_all_older_than_keep_full_become_summary(self):
        ctx = self._entries(6, keep_full=6)
        assert all(e["type"] == "session" for e in ctx)


# ── 3. SessionArchive.compress / recent_context（设计文档 35 §3.2） ─────


class TestSessionArchiveCompression:
    def test_compress_folds_and_limits_without_losing_get_history(self, tmp_path):
        arch = SessionArchive(tmp_path / "mem")
        for i in range(25):
            arch.archive(_session(f"s{i}", dimensions=[_dim("feature", f"feat-{i}", 0.9)]))
        arch.compress(max_entries=20, keep_full=5)
        # 压缩只影响注入路径：get_history/recent_sessions 仍返回全文（无损）
        sessions = arch.recent_sessions()
        assert len(sessions) == 25
        assert all("markdown_report" in s.raw for s in sessions)
        # 注入路径：封顶 max_entries，最近 keep_full 条为 session 类型
        context = arch._summary_store.get("cursor", [])
        assert len(context) == 20
        assert [e["type"] for e in context[:5]] == ["session"] * 5
        assert [e["type"] for e in context[5:]] == ["summary"] * 15

    def test_recent_context_empty_query_recent_first(self, tmp_path):
        arch = SessionArchive(tmp_path / "mem")
        arch.archive(_session("old", dimensions=[_dim("feature", "feature old", 0.9)], created_at="2026-08-01T00:00:00Z"))
        arch.archive(_session("new", dimensions=[_dim("feature", "feature new", 0.9)], created_at="2026-08-10T00:00:00Z"))
        out = arch.recent_context("cursor", top_k=5)
        assert "feature new" in out[0], "无 query 时取最近会话"
        assert "feature old" in out[1]

    def test_recent_context_relevance_recall_beats_recency(self, tmp_path):
        """相关度召回而非"最近 N 条"：更旧的 pricing 结论应排在更新的 feature 结论前。"""
        arch = SessionArchive(tmp_path / "mem")
        arch.archive(_session("recent-feature", dimensions=[_dim("feature", "Cursor has an AI editor", 0.9)], created_at="2026-08-10T00:00:00Z"))
        arch.archive(_session("old-pricing", dimensions=[_dim("pricing", "Pro is $20 per month", 0.9)], created_at="2026-08-01T00:00:00Z"))
        out = arch.recent_context("cursor", top_k=5, query="pricing")
        assert out and "Pro is $20" in out[0], "query 相关度应压倒新旧排序"
        assert "AI editor" not in out[0]

    def test_recent_context_more_compact_than_full(self, tmp_path):
        full_md = "# cursor\n\n" + "正文 " * 500
        arch = SessionArchive(tmp_path / "mem")
        arch.archive(_session("s", dimensions=[_dim("pricing", "Pro is $20", 0.9)], markdown=full_md))
        out = "\n".join(arch.recent_context("cursor", top_k=5))
        assert len(out) < len(full_md), "注入内容应较全文精简"

    def test_recent_context_unknown_competitor(self, tmp_path):
        arch = SessionArchive(tmp_path / "mem")
        assert arch.recent_context("nobody") == []


# ── 4. Skill 语义化（设计文档 35 §3.3） ───────────────────────────────


class TestSkillMethod:
    def test_method_roundtrip_and_prompt_injection(self, tmp_path):
        store = SkillStore(tmp_path / "mem")
        store.record_success("cursor", "pricing", "benchmark", method="官网抓不到 → 降级榜单源")
        skill = store.retrieve_skills("cursor")[0]
        assert skill.method == "官网抓不到 → 降级榜单源"
        prompt = enrich_prompt("base", skills=[skill])
        assert "做法: 官网抓不到 → 降级榜单源" in prompt

    def test_default_method_empty_compat(self, tmp_path):
        store = SkillStore(tmp_path / "mem")
        store.record_success("cursor", "pricing", "official_pricing")
        skill = store.retrieve_skills("cursor")[0]
        assert skill.method == ""
        prompt = enrich_prompt("base", skills=[skill])
        assert "做法" not in prompt, "无 method 时保持旧格式"

    def test_merge_keeps_latest_method(self, tmp_path):
        store = SkillStore(tmp_path / "mem")
        store.record_success("cursor", "pricing", "docs")
        store.record_success("cursor", "pricing", "docs", method="docs 抓不到 → 用 pricing 页")
        skills = store.retrieve_skills("cursor")
        assert len(skills) == 1  # 合并
        assert skills[0].method == "docs 抓不到 → 用 pricing 页"

    def test_method_persists_across_reload(self, tmp_path):
        d = tmp_path / "mem"
        SkillStore(d).record_success("cursor", "pricing", "docs", method="直接命中")
        assert SkillStore(d).retrieve_skills("cursor")[0].method == "直接命中"


# ── 5. Evolution 归纳（设计文档 35 §3.4） ─────────────────────────────


class TestEvolutionPatterns:
    def test_note_retrieve_patterns_roundtrip(self, tmp_path):
        evo = EvolutionMemory(tmp_path / "mem")
        evo.note_pattern("cursor", "performance", "榜单源缺失 → 回退页面抽取", outcome="degraded")
        evo.note_pattern("cursor", "performance", "命中 SWE-bench 榜单", outcome="success")
        evo.note_pattern("cursor", "roadmap", "无关维度模式", outcome="success")
        got = evo.retrieve_patterns("cursor", "performance")
        assert set(got) == {"榜单源缺失 → 回退页面抽取", "命中 SWE-bench 榜单"}, "按维度过滤"
        assert evo.retrieve_patterns("cursor", "roadmap") == ["无关维度模式"]

    def test_patterns_do_not_pollute_success_rates(self, tmp_path):
        evo = EvolutionMemory(tmp_path / "mem")
        evo.record_outcome("official_pricing", True)
        evo.note_pattern("cursor", "pricing", "某经验", outcome="success")
        rates = evo.source_success_rates()
        assert set(rates) == {"official_pricing"}, "模式存独立存储，不污染成功率统计"

    def test_patterns_dedupe_same_entry(self, tmp_path):
        evo = EvolutionMemory(tmp_path / "mem")
        evo.note_pattern("cursor", "pricing", "同一经验", outcome="success")
        evo.note_pattern("cursor", "pricing", "同一经验", outcome="success")
        assert len(evo.retrieve_patterns("cursor", "pricing")) == 1


# ── 6. FourLayerMemory 委托 + 主流程注入 ─────────────────────────────


class TestFourLayerMemoryDelegation:
    def test_recent_context_and_patterns_via_four_layer(self, tmp_path):
        mem = FourLayerMemory(tmp_path / "mem")
        mem.archive_session(_session("s1", dimensions=[_dim("pricing", "Pro is $20", 0.9)]))
        assert mem.recent_context("cursor", query="pricing") and "Pro is $20" in mem.recent_context("cursor", query="pricing")[0]
        mem.note_pattern("cursor", "pricing", "经验A", outcome="success")
        assert mem.retrieve_patterns("cursor", "pricing") == ["经验A"]

    def test_record_success_with_method_via_four_layer(self, tmp_path):
        mem = FourLayerMemory(tmp_path / "mem")
        mem.record_success("cursor", "pricing", "benchmark", method="降级到榜单源")
        assert mem.retrieve_skills("cursor")[0].method == "降级到榜单源"


class TestMemoryContextInjection:
    """设计文档 49 迁移：记忆召回经 ReactLoop.memory_context_fn 注入 ReAct 系统提示。"""

    @staticmethod
    def _run_loop(memory_text: str) -> str:
        from competitor_agent.agent.react_agent import ReactAgent
        from competitor_agent.agent.react_loop import ReactLoop
        from competitor_agent.agent.tool_dispatcher import ToolDispatcher

        captured: dict = {}

        def fake_llm(messages, model, **kwargs):
            captured["system"] = messages[0].get("content", "") if messages else ""
            return ToolCallReply(content="分析完成")

        agent = ReactAgent(
            llm=LLMClient(call_func=fake_llm),
            dispatcher=ToolDispatcher(tools={}),
        )
        loop = ReactLoop(
            agent,
            max_steps=3,
            memory_context_fn=lambda task: memory_text,
        )
        loop.run("分析 cursor")
        return captured["system"]

    def test_memory_context_reaches_react_system_prompt(self):
        system = self._run_loop("pricing: Pro is $20（过往结论）")
        assert "历史教训/笔记" in system
        assert "pricing: Pro is $20" in system

    def test_no_memory_context_no_injection(self):
        system = self._run_loop("")
        assert "历史教训/笔记" not in system
