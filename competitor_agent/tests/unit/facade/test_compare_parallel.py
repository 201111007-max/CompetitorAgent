"""§13 增强：compare 多竞品（设计文档 62 §3.5：单 Lead loop，并行归 Lead delegate 决策）

compare 不再有代码并行的 ThreadPoolExecutor 相位——N 向对比同走单 Lead loop，
并行由 Lead 的 delegate(parallel=true) 表达（DelegateRunner 后台并发，代码只守
execution.max_parallel_subagents 硬上限）。断言迁移到新装配：
- 结果按输入顺序稳定返回（矩阵/竞品顺序相同）
- 单 Lead loop 信号（Lead 编排 phase_start + 完成 report 事件）
"""
from competitor_agent.config.loader import AppConfig, ExecutionConfig
from competitor_agent.domain_types.report import ComparisonReport
from competitor_agent.facade.api import CompetitorAnalysisAPI


class FakeExtractor:
    def fetch(self, gap, context):
        from competitor_agent.domain_types import Observation, SourceEvidence

        url = str(context.kwargs.get("url"))
        if "pricing" in url:
            text = "Pro $20/month\nTeams $40/month\nUltra $60/month"
        elif "docs" in url:
            text = "supports MCP integration and agent mode."
        else:
            text = "is an AI code editor."
        ev = SourceEvidence(source_name="web_extractor", url=url, content_hash=str(hash(url)), trust_level=0.9)
        return Observation(gap_field=gap.field, source="web_extractor", raw_text=text, evidence=ev)


def _parallel_api(llm=None, **kwargs) -> CompetitorAnalysisAPI:
    # 设计文档 62 §3.8：不再有 execution.mode 决策开关；compare 多竞品默认并行（硬上限）
    cfg = AppConfig(execution=ExecutionConfig(max_parallel_subagents=4))
    kwargs.setdefault("extractor", FakeExtractor())
    kwargs.setdefault("llm", llm)
    kwargs.setdefault("use_llm", True)
    return CompetitorAnalysisAPI(config=cfg, **kwargs)


def _strip_ts(md: str) -> str:
    """去掉生成时间行（并行/串行 created_at 不同，其余内容应一致）。"""
    return "\n".join(l for l in md.splitlines() if not l.startswith("> 生成时间"))


class TestCompareParallel:
    def test_parallel_compare_returns_comparison_in_input_order(self, mock_llm):
        api = _parallel_api(llm=mock_llm)
        result = api.compare("Cursor", "Windsurf", "Copilot")
        assert isinstance(result, ComparisonReport)
        assert [r.competitor.name for r in result.reports] == ["cursor", "windsurf", "copilot"]
        md = result.markdown_report
        assert "品类格局矩阵" in md
        for n in ("cursor", "windsurf", "copilot"):
            assert n in md

    def test_parallel_compare_same_semantics_as_serial(self, mock_llm):
        # 语义一致：多次 compare（默认并行）竞品顺序与矩阵内容稳定
        a = _parallel_api(llm=mock_llm)
        b = _parallel_api(llm=mock_llm)
        r_serial = a.compare("Cursor", "Windsurf")
        r_parallel = b.compare("Cursor", "Windsurf")
        assert [r.competitor.name for r in r_serial.reports] == [
            r.competitor.name for r in r_parallel.reports
        ]
        assert _strip_ts(r_serial.markdown_report) == _strip_ts(r_parallel.markdown_report)

    def test_compare_emits_single_lead_loop_signal(self, mock_llm):
        """设计文档 62 §3.5：compare 走单 Lead loop（parallel 由 Lead delegate 决策，不再有代码并行相位）。"""
        events = []
        api = _parallel_api(llm=mock_llm, event_sink=events.append)
        result = api.compare("Cursor", "Windsurf")
        assert isinstance(result, ComparisonReport)
        assert [r.competitor.name for r in result.reports] == ["cursor", "windsurf"]
        # 单 Lead loop 信号：编排 phase_start + 完成 report 事件
        assert any("Lead 编排" in (e.message or "") for e in events if e.event == "phase_start")
        assert any(e.event == "report" for e in events)
