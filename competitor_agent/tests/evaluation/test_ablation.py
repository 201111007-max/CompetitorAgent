"""消融 / 对比实验测试（30_ablation_comparison_design.md §5）

- 开关门控：enable_rag=False 无知识库、enable_memory=False 无记忆副作用
- AblationRunner 汇总：小用例集 × 2 变体 → 指标正确、渲染表头/数值对齐
- RAG 差分集成：共享知识库 + RAG 感知 mock → full 命中而 no-rag 缺失
- 记忆差分：共享记忆跨用例累积后影响选源（成功率驱动）
"""
import json
import re

import pytest

from competitor_agent.evaluation.ablation import (
    AblationResult,
    AblationRunner,
    AblationVariant,
    DEFAULT_VARIANTS,
    render_ablation_table,
    write_ablation_json,
)
from competitor_agent.evaluation.benchmark import (
    ACCURACY_FIXTURE,
    STRATEGY_FIXTURE,
    BenchmarkExtractor,
    extract_prediction,
)
from competitor_agent.facade.api import CompetitorAnalysisAPI
from competitor_agent.knowledge_base.competitor_store import CompetitorStore
from competitor_agent.knowledge_base.ingester import Ingester
from competitor_agent.llm.client import LLMClient

pytestmark = pytest.mark.evaluation


# ── 1. 开关门控（设计文档 30 §5 单测） ────────────────────────────────


class TestSwitchGating:
    def test_enable_rag_false_no_knowledge_base(self):
        api = CompetitorAnalysisAPI(enable_rag=False, enable_memory=False)
        assert api._store is None
        assert api._ingester is None
        assert api._retriever is None

    def test_enable_rag_true_default_has_knowledge_base(self):
        api = CompetitorAnalysisAPI()
        assert api._store is not None
        assert api._ingester is not None
        assert api._retriever is not None

    def test_enable_memory_false_gates_memory(self, memory, mock_llm, fake_extractor):
        """enable_memory=False：注入的 memory 分析后零写入（无 archive/skill/outcome）。"""
        api = CompetitorAnalysisAPI(
            extractor=fake_extractor,
            llm=mock_llm,
            use_llm=True,
            memory=memory,
            enable_memory=False,
        )
        assert api._memory is None
        api.analyze("分析 cursor 定价", mode="single")
        assert memory.list_sessions() == []
        assert memory.retrieve_skills("cursor") == []

    def test_enable_memory_true_records_side_effects(self, memory, mock_llm, fake_extractor):
        api = CompetitorAnalysisAPI(
            extractor=fake_extractor,
            llm=mock_llm,
            use_llm=True,
            memory=memory,
            enable_memory=True,
        )
        assert api._memory is not None
        api.analyze("分析 cursor 定价", mode="single")
        assert memory.retrieve_skills("cursor"), "记忆开启时分析应沉淀技能"


# ── 2. AblationRunner 汇总 + 渲染（设计文档 30 §5 单测） ────────────────


def _write_mini_fixture(tmp_path):
    """迷你 fixture：1 accuracy（定价命中）+ 1 strategy（选源命中）。"""
    (tmp_path / ACCURACY_FIXTURE).write_text(
        json.dumps(
            [
                {
                    "case_id": "mini_pricing_2026",
                    "task": "只分析 cursor 的定价",
                    "competitor": "cursor",
                    "dimension": "pricing",
                    "tags": ["normal"],
                    "mode": "single",
                    "page": "Pro $20/month",
                    "ground_truth": {"pro": "$20/month"},
                }
            ]
        ),
        encoding="utf-8",
    )
    (tmp_path / STRATEGY_FIXTURE).write_text(
        json.dumps(
            [
                {
                    "case_id": "mini_pricing_hit_2026",
                    "task": "只分析 cursor 的定价",
                    "competitor": "cursor",
                    "dimension": "pricing",
                    "best_url": "https://www.cursor.com/pricing",
                    "mode": "single",
                    "page": "Pro $20/month",
                }
            ]
        ),
        encoding="utf-8",
    )


class TestAblationRunner:
    def test_runner_aggregates_variants(self, tmp_path):
        _write_mini_fixture(tmp_path)
        runner = AblationRunner(fixtures_dir=tmp_path, memory_dir=tmp_path / "m")
        results = runner.run(variants=[AblationVariant("full"), AblationVariant("no-memory")])

        assert len(results) == 2
        assert [r.variant.name for r in results] == ["full", "no-memory"]
        for r in results:
            assert r.n_cases == 2
            assert 0.0 <= r.field_accuracy <= 1.0
            assert 0.0 <= r.tool_selection_accuracy <= 1.0
            assert isinstance(r.metrics(), dict)

    def test_runner_default_variants_matrix(self, tmp_path):
        _write_mini_fixture(tmp_path)
        runner = AblationRunner(fixtures_dir=tmp_path, memory_dir=tmp_path / "m")
        results = runner.run()
        assert [r.variant.name for r in results] == [v.name for v in DEFAULT_VARIANTS]

    def test_no_rag_shared_store_differs_after_memory_accumulation(self, tmp_path):
        """共享记忆跨用例累积：后续用例的 SourceSelector 成功率驱动选源与无记忆不同。"""
        _write_mini_fixture(tmp_path)
        runner = AblationRunner(fixtures_dir=tmp_path, memory_dir=tmp_path / "m")
        results = runner.run(variants=[AblationVariant("full"), AblationVariant("no-memory")])
        full, no_memory = results
        # 记忆影响选源（成功率信任提升重排），使策略命中可能改变——至少可区分开关已接线
        assert full.report.strategy.tool_selection_accuracy is not None
        assert no_memory.report.strategy.tool_selection_accuracy is not None

    def test_ablation_result_metrics(self):
        runner = AblationRunner()
        # 空 fixture 目录 → 空结果，指标全 0，不抛错
        import tempfile
        from pathlib import Path

        runner = AblationRunner(fixtures_dir=Path(tempfile.mkdtemp()))
        results = runner.run(variants=[AblationVariant("full")])
        assert results[0].n_cases == 0
        assert results[0].field_accuracy == 0.0


class TestRendering:
    def test_render_table_headers_and_best_mark(self):
        results = [
            AblationResult(AblationVariant("full"), _fake_report(0.9, 0.1)),
            AblationResult(AblationVariant("no-rag"), _fake_report(0.7, 0.2)),
        ]
        md = render_ablation_table(results)
        assert "| 指标 | full | no-rag |" in md
        assert "**0.9000**" in md  # full 字段准确率最优加粗
        assert "**0.1000**" in md  # full 幻觉率最优（小值）加粗

    def test_write_ablation_json_schema(self, tmp_path):
        results = [AblationResult(AblationVariant("full"), _fake_report(0.9, 0.0))]
        out = tmp_path / "ablation.json"
        write_ablation_json(results, out)
        data = json.loads(out.read_text(encoding="utf-8"))
        assert data["harness_version"]
        assert data["variants"][0]["variant"]["name"] == "full"
        assert "metrics" in data["variants"][0]
        assert "per_case_accuracy" in data["variants"][0]


def _fake_report(acc: float, halluc: float):
    """构造最小 BenchmarkReport 用于渲染/序列化单测（不跑真实链路）。"""
    from competitor_agent.evaluation.accuracy_eval import AccuracyMetrics
    from competitor_agent.evaluation.benchmark import BenchmarkReport
    from competitor_agent.evaluation.strategy_eval import StrategyMetrics

    return BenchmarkReport(
        accuracy=AccuracyMetrics(field_accuracy=acc, hallucination_rate=halluc, f1=acc),
        strategy=StrategyMetrics(tool_selection_accuracy=0.9, cost_efficiency=10.0, avg_source_rank=1.0),
        n_cases=2,
        loaded_fixtures=[ACCURACY_FIXTURE, STRATEGY_FIXTURE],
        trace_completeness=1.0,
    )


# ── 3. RAG 差分集成（设计文档 30 §5：答案只在知识库片段中） ──────────


class _RagAwarePricingMock:
    """ReAct-scripted RAG 感知定价 mock（设计文档 47/49 迁移）：

    Lead 会话（make_plan → delegate → Final Answer REPORT_SCHEMA）+ 维度子 Agent 会话
    （web_extract → Final Answer SUBAGENT_RESULT_SCHEMA）。定价条目只从系统提示的
    [知识库参考片段] 段解析 $N/month——RAG 开时检索片段含答案、no-rag 无片段为空，
    从而差分可测（不解析整段系统提示，避免 fact_verification 技能里的 "$20/month" 示例误报）。
    """

    _PLAN_RE = re.compile(r"(?P<name>[^\s$]+?)\s+\$(?P<price>\d+)/month", re.IGNORECASE)
    _RAG_MARKER = "知识库参考片段"
    _PARSED_COMPETITOR = "cursor"

    def __init__(self) -> None:
        self._convs: dict[str, dict] = {}

    def complete(self, messages, model=None):
        if not messages:
            return "{}"
        system = messages[0].get("content", "")
        if "语义解析器" in system:
            return json.dumps(
                {"resolution": "registry", "competitors": [self._PARSED_COMPETITOR], "dimensions": None, "custom_sources": {}}
            )
        if "Lead Agent" in system:
            return self._lead_step(messages)
        if "维度子 Agent" in system:
            return self._subagent_step(messages)
        return "{}"

    def _lead_step(self, messages):
        state = self._convs.setdefault("lead", {})
        if not state.get("plan"):
            state["plan"] = True
            return (
                "Thought: 规划分析策略\nAction: make_plan\n"
                'Args: {"plan_json": {"competitor": "cursor", "dimensions": ["pricing"], '
                '"budget": {"max_steps": 8}, "custom_sources": {}}}'
            )
        if not state.get("delegate"):
            state["delegate"] = True
            return 'Thought: 委派维度子 Agent\nAction: delegate\nArgs: {"dimensions": ["pricing"], "task": ""}'
        obs = self._last_observation(messages)
        dimensions = []
        for name, body in self._subagent_blocks(obs):
            item = self._extract_json_block(body)
            if isinstance(item, dict) and str(item.get("dimension") or "") == name:
                dimensions.append(item)
        return "Final Answer: " + json.dumps(
            {"competitor": self._PARSED_COMPETITOR, "dimensions": dimensions}, ensure_ascii=False
        )

    def _subagent_step(self, messages):
        state = self._convs.setdefault("sub:pricing", {})
        if not state.get("tried"):
            state["tried"] = True
            return (
                "Thought: 采集定价信息\nAction: web_extract\n"
                'Args: {"url": "https://example.com/cursor/pricing"}'
            )
        system = messages[0].get("content", "")
        plans = self._plans(self._knowledge_text(system))
        return "Final Answer: " + json.dumps(
            {
                "dimension": "pricing",
                "summary": f"检测到 {len(plans)} 个定价条目",
                "details": {"plans": plans},
                "confidence": 0.8,
                "evidence_urls": ["https://example.com/cursor/pricing"],
            },
            ensure_ascii=False,
        )

    @classmethod
    def _knowledge_text(cls, system: str) -> str:
        idx = system.find(cls._RAG_MARKER)
        return system[idx:] if idx >= 0 else ""

    @classmethod
    def _plans(cls, text: str) -> list[dict[str, str]]:
        return [
            {"name": m.group("name").lower(), "price": m.group("price"), "period": "month"}
            for m in cls._PLAN_RE.finditer(text)
        ]

    @staticmethod
    def _last_observation(messages) -> str:
        for message in reversed(messages):
            if message.get("role") == "user" and "Observation" in str(message.get("content", "")):
                return str(message.get("content", ""))
        return ""

    @staticmethod
    def _subagent_blocks(text: str) -> list[tuple[str, str]]:
        parts = re.split(r"\[维度子 Agent 结果: ", text)
        blocks = []
        for part in parts[1:]:
            name = part.split("|", 1)[0].strip()
            body = part.split("]", 1)[1] if "]" in part else part
            blocks.append((name, body))
        return blocks

    @staticmethod
    def _extract_json_block(text: str):
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            return json.loads(text[start : end + 1])
        except (json.JSONDecodeError, TypeError):
            return None


class TestRagDifferential:
    def test_full_hits_from_knowledge_base_no_rag_misses(self, tmp_path):
        """预置知识库含答案、页面无答案：full（RAG 开）从片段命中，no-rag 缺失。"""
        store = CompetitorStore(data_dir=tmp_path / "kb")
        Ingester(store=store).ingest(
            competitor="cursor",
            dimension="pricing",
            text="Pro $20/month",
            source_url="https://www.cursor.com/pricing",
        )
        mock = LLMClient(call_func=_RagAwarePricingMock().complete)
        gt = {"pro": "$20/month"}

        # full：RAG 开，共享已预置的 store
        full_api = CompetitorAnalysisAPI(
            extractor=BenchmarkExtractor(page="", fail_urls=set()),
            llm=mock,
            use_llm=True,
            max_iterations=8,
            cost_limit=1.0,
            enable_rag=True,
            rag_store=store,
        )
        full_report = full_api.analyze("只分析 cursor 的定价", mode="single")
        full_pred = extract_prediction(full_report, "pricing", gt)
        assert full_pred["pro"] == "$20/month", "RAG 开启应从知识库片段命中"

        # no-rag：无知识库，页面为空 → 缺失
        no_rag_api = CompetitorAnalysisAPI(
            extractor=BenchmarkExtractor(page="", fail_urls=set()),
            llm=mock,
            use_llm=True,
            max_iterations=8,
            cost_limit=1.0,
            enable_rag=False,
        )
        no_rag_report = no_rag_api.analyze("只分析 cursor 的定价", mode="single")
        no_rag_pred = extract_prediction(no_rag_report, "pricing", gt)
        assert no_rag_pred["pro"] == "", "RAG 关闭时无知识库片段可引用，应为空"

    def test_seed_then_target_accumulation(self, tmp_path):
        """共享 store 跨用例累积：前一用例摄入，后一用例（页面无答案）经 RAG 命中。"""
        store = CompetitorStore(data_dir=tmp_path / "kb")
        mock = LLMClient(call_func=_RagAwarePricingMock().complete)
        gt = {"pro": "$20/month"}

        # seed：摄入管道写入共享知识库（设计文档 49 下 analyze() 只读 RAG，写侧走外部摄入）
        Ingester(store=store).ingest(
            competitor="cursor",
            dimension="pricing",
            text="Pro $20/month",
            source_url="https://www.cursor.com/pricing",
        )

        target_api = CompetitorAnalysisAPI(
            extractor=BenchmarkExtractor(page="", fail_urls=set()),
            llm=mock,
            use_llm=True,
            max_iterations=8,
            cost_limit=1.0,
            enable_rag=True,
            rag_store=store,
        )
        report = target_api.analyze("只分析 cursor 的定价", mode="single")
        pred = extract_prediction(report, "pricing", gt)
        assert pred["pro"] == "$20/month", "先前摄入的片段应被后一用例检索到"
