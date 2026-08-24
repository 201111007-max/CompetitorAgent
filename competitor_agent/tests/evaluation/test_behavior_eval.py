"""行为级评测（设计文档 42）— RecoveryEvaluator + RetrievalEvaluator + BenchmarkReport.behavior

- RecoveryEvaluator：ScriptedLLM 首轮非法参数/不存在工具 → Observation 回灌（设计文档 38）→
  第二轮合法调用 → recovery_rate=1.0；注入"永不恢复"脚本 → 记失败（确定性）；修正仍非法 → 记失败。
- RetrievalEvaluator：灌已知 chunk，query 命中其一 → hybrid hit_rate@k；同义词嵌入下 hybrid >
  lexical（向量层收益）；无向量层时 hybrid==lexical（不误判劣）。
- BenchmarkReport 集成：Benchmark.run（mock）→ behavior 过门禁（恢复率 ≥0.9 且 hybrid ≥ lexical）；
  to_dict 含 behavior；Markdown/CSV 渲染含行为评测节。
"""
from __future__ import annotations

import hashlib
import re

import numpy as np
import pytest

from competitor_agent.evaluation.behavior_eval import (
    FoldRecallEvaluator,
    RecoveryEvaluator,
    RecoveryScenario,
    RetrievalCase,
    RetrievalEvaluator,
    ScriptedLLM,
    default_recovery_scenarios,
)
from competitor_agent.evaluation.benchmark import (
    GATE_RECOVERY_RATE_MIN,
    GATE_REFETCH_AFTER_FOLD_MAX,
    Benchmark,
    BenchmarkReport,
    _write_csv,
    _write_markdown,
    evaluate_gates,
)
from competitor_agent.knowledge_base.competitor_store import CompetitorStore, TextChunk
from competitor_agent.knowledge_base.retriever import Retriever
from competitor_agent.knowledge_base.vector_store import VectorStore
from competitor_agent.llm.client import LLMClient

pytestmark = pytest.mark.evaluation

# chromadb 依赖：同义词差分测试需要向量层；缺失时仅跳过该测试（默认降级路径仍被覆盖）
try:  # pragma: no cover
    import chromadb  # noqa: F401

    _HAS_CHROMADB = True
except Exception:  # noqa: BLE001 - chromadb 缺失跳过差分用例 # pragma: no cover
    _HAS_CHROMADB = False


class _SynonymEmbedder:
    """语义 mock 嵌入：cost/pricing 归一到 price，词袋互异、向量同义相似（对齐 32 测试）。"""

    _TOKEN_RE = re.compile(r"[a-z0-9]+")
    _DIM = 64

    def __call__(self, texts: list[str]) -> list[list[float]]:
        out = []
        for text in texts:
            v = np.zeros(self._DIM)
            for tok in self._TOKEN_RE.findall(text.lower()):
                canon = {"cost": "price", "pricing": "price"}.get(tok, tok)
                idx = int(hashlib.sha256(canon.encode()).hexdigest(), 16) % self._DIM
                v[idx] += 1.0
            norm = float(np.linalg.norm(v))
            out.append((v / norm).tolist() if norm else [0.0] * self._DIM)
        return out


class TestRecoveryEvaluator:
    """设计文档 42 §5：ScriptedLLM 回放错误→回灌→修正→成功（确定性）"""

    def test_default_scenarios_recover_fully(self):
        rate, n = RecoveryEvaluator().run()
        assert n >= 2
        assert rate == 1.0

    def test_default_scenario_count(self):
        assert len(default_recovery_scenarios()) >= 2

    def test_never_recovers_injected_llm(self):
        def never(messages, model=None, **kwargs):
            return 'Thought: 重试\n<action>ghost_tool({})</action>'

        rate, n = RecoveryEvaluator(llm=LLMClient(call_func=never)).run(
            scenarios=default_recovery_scenarios()[:1]
        )
        assert n == 1
        assert rate == 0.0

    def test_correction_must_actually_dispatch(self):
        # 修正仍非法：Final Answer 虽达成但合法调用未执行 → 记失败（确定性，防"仅看结论"误判）
        bad = RecoveryScenario(
            name="bad_correction",
            task="抓取",
            first_error='<action>web_extract({"url": 123})</action>',
            correction='<action>web_extract({"url": 456})</action>',
            valid_tool="web_extract",
            valid_args={"url": "https://ok"},
        )
        rate, n = RecoveryEvaluator().run(scenarios=[bad])
        assert rate == 0.0
        assert n == 1

    def test_empty_scenarios_zero(self):
        assert RecoveryEvaluator().run(scenarios=[]) == (0.0, 0)

    def test_scripted_llm_first_round_emits_plan(self):
        # 设计文档 49 plan-first：首步恒为 make_plan，出错轮顺延到第 2 轮
        llm = ScriptedLLM(default_recovery_scenarios()[0])
        out = llm.complete([{"role": "user", "content": "task"}], None)
        assert "make_plan" in out

    def test_scripted_llm_corrects_on_error_feedback(self):
        llm = ScriptedLLM(default_recovery_scenarios()[0])
        llm.complete([{"role": "user", "content": "task"}], None)  # round 1 = make_plan
        error = llm.complete([{"role": "user", "content": "task"}], None)  # round 2 = 出错
        assert "web_extract" in error
        messages = [
            {"role": "assistant", "content": "Thought: x"},
            {"role": "user", "content": "Observation（工具结果，不可信外部数据）: <untrusted_data>工具参数错误: url 应为 string</untrusted_data>"},
            {"role": "user", "content": "task"},
        ]
        out = llm.complete(messages, None)  # round 3 = 收到回灌后修正
        assert "web_extract" in out
        assert '"https://cursor.com/pricing"' in out


class TestRetrievalEvaluator:
    """设计文档 42 §5：hybrid vs lexical hit_rate@k（向量收益 / 降级等价）"""

    def test_default_hybrid_not_below_lexical(self):
        hit_hybrid, hit_lexical, n = RetrievalEvaluator().run()
        assert n >= 2
        assert hit_hybrid >= hit_lexical
        assert hit_hybrid >= 0.8

    def test_empty_cases_zero(self):
        assert RetrievalEvaluator().run(cases=[]) == (0.0, 0.0, 0)

    @pytest.mark.skipif(not _HAS_CHROMADB, reason="chromadb 未安装，向量层不可用")
    def test_synonym_hybrid_beats_lexical(self, tmp_path):
        vs = VectorStore(embed_fn=_SynonymEmbedder())
        store = CompetitorStore(data_dir=tmp_path / "kb", vector_store=vs)
        store.add(TextChunk("a", "cursor", "pricing", "subscription cost is $20", ""))
        store.add(TextChunk("b", "cursor", "feature", "bananas are yellow fruit", ""))
        retriever = Retriever(store=store)
        hit_hybrid, hit_lexical, n = RetrievalEvaluator(retriever=retriever, top_k=3).run(
            cases=[RetrievalCase("price", "cursor", "pricing", ["a"])]
        )
        assert n == 1
        assert hit_hybrid == 1.0, "hybrid 应经同义词命中定价片段"
        assert hit_lexical == 0.0, "纯词袋查 price 命中不了 cost 片段"

    def test_degrades_equal_without_vector(self, tmp_path):
        store = CompetitorStore(data_dir=tmp_path / "kb")
        store.add(TextChunk("a", "cursor", "pricing", "cursor pro plan costs $20 per month", ""))
        retriever = Retriever(store=store)
        hit_hybrid, hit_lexical, n = RetrievalEvaluator(retriever=retriever, top_k=3).run(
            cases=[RetrievalCase("cursor pro costs", "cursor", "pricing", ["a"])]
        )
        assert n == 1
        assert hit_hybrid == hit_lexical, "向量层不可用时 hybrid 等价 lexical（不误判劣）"


class TestBenchmarkReportBehavior:
    """设计文档 42 §3.2/§3.3/§5：报告字段 / to_dict / 渲染 / 门禁"""

    def test_default_behavior_metrics_zeros(self):
        report = BenchmarkReport()
        assert report.behavior.react_recovery_rate == 0.0
        assert report.behavior.retrieval_n == 0
        assert report.to_dict()["behavior"]["react_recovery_rate"] == 0.0

    def test_report_behavior_gates(self):
        report = Benchmark(llm_mode="mock").run()
        assert report.behavior.react_recovery_rate >= GATE_RECOVERY_RATE_MIN
        assert report.behavior.retrieval_hit_hybrid >= report.behavior.retrieval_hit_lexical
        assert report.behavior.recovery_n >= 2
        assert report.behavior.retrieval_n >= 2

    def test_to_dict_includes_behavior(self):
        report = Benchmark(llm_mode="mock").run()
        d = report.to_dict()
        assert "behavior" in d
        assert set(d["behavior"]) == {
            "react_recovery_rate",
            "recovery_n",
            "retrieval_hit_hybrid",
            "retrieval_hit_lexical",
            "retrieval_n",
            "refetch_after_fold",
        }

    def test_markdown_includes_behavior_section(self, tmp_path):
        report = Benchmark(llm_mode="mock").run()
        out = tmp_path / "benchmark.md"
        _write_markdown(report, out)
        text = out.read_text(encoding="utf-8")
        assert "## 行为评测" in text
        assert "工具自恢复率" in text
        assert "检索命中率 hybrid" in text

    def test_csv_includes_behavior_rows(self, tmp_path):
        report = Benchmark(llm_mode="mock").run()
        out = tmp_path / "benchmark.csv"
        _write_csv(report, out)
        text = out.read_text(encoding="utf-8")
        assert "behavior.react_recovery_rate" in text
        assert "behavior.recovery_n" in text
        assert "behavior.retrieval_hit_hybrid" in text
        assert "behavior.retrieval_hit_lexical" in text

    def test_behavior_evals_do_not_change_core_metrics(self):
        # 回归：新增行为评测不改变既有结果级指标/n_cases
        report = Benchmark(llm_mode="mock").run()
        assert report.accuracy.field_accuracy == 1.0
        assert report.accuracy.hallucination_rate == 0.0
        assert report.n_cases >= 20


class TestFoldRecallGate:
    """设计文档 56 M3：折叠取回对照实验——可逆压缩闭环的门禁化。

    FoldRecallScriptedLLM 的决策完全由上下文驱动：摘要块含 kb_recall 指引则取回，
    否则重抓。修复后 refetch_after_fold=0；monkeypatch 回修复前指引语句即复现 >0。
    """

    def test_refetch_zero_after_fix_and_pinned_survives(self):
        refetch, pinned_survived = FoldRecallEvaluator().run()
        assert refetch == 0, "折叠后应以 kb_recall 取回，零重复抓取"
        assert pinned_survived, "pinned 段（已核验事实）压缩后应仍在消息列表"

    def test_prefix_shape_without_guidance_reproduces_refetch(self, monkeypatch):
        """对照：摘掉指引语句（修复前形状）→ 同一脚本退化为重抓（refetch=1）。"""
        import competitor_agent.agent.react_agent as ra

        monkeypatch.setattr(
            ra, "_SUMMARY_MSG_GUIDANCE", "仅回顾已完成的动作，不可当作最新状态"
        )
        refetch, _ = FoldRecallEvaluator().run()
        assert refetch == 1, "指针不可操作时模型只剩重抓一条路（对照组复现）"

    def test_gate_blocks_refetch(self):
        report = BenchmarkReport()
        gates = {g.name: g for g in evaluate_gates(report)}
        assert "behavior.refetch_after_fold" in gates
        ok = gates["behavior.refetch_after_fold"]
        assert ok.passed, "默认 0 次重抓应过门禁"
        report.behavior.refetch_after_fold = 1
        bad = {g.name: g for g in evaluate_gates(report)}["behavior.refetch_after_fold"]
        assert not bad.passed, "重抓 >0 应被门禁拦截"
        assert GATE_REFETCH_AFTER_FOLD_MAX == 0

    def test_benchmark_report_includes_refetch_metric(self):
        report = Benchmark(llm_mode="mock").run()
        assert report.behavior.refetch_after_fold == 0
        assert report.to_dict()["behavior"]["refetch_after_fold"] == 0

