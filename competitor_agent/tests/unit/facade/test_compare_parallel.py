"""§13 增强：compare 并行分析（execution.mode=parallel）

N 向对比在 parallel 模式下用 ThreadPoolExecutor 并行分析多个竞品：
- 结果按输入顺序稳定返回，语义与串行一致（矩阵/竞品顺序相同）
- 发出 compare.phase_start 并行埋点
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
    cfg = AppConfig(execution=ExecutionConfig(mode="parallel", max_parallel_subagents=4))
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
        cfg_serial = AppConfig(execution=ExecutionConfig(mode="single", max_parallel_subagents=4))
        serial = CompetitorAnalysisAPI(extractor=FakeExtractor(), llm=mock_llm, use_llm=True, config=cfg_serial)
        parallel = _parallel_api(llm=mock_llm)
        r_serial = serial.compare("Cursor", "Windsurf")
        r_parallel = parallel.compare("Cursor", "Windsurf")
        assert [r.competitor.name for r in r_serial.reports] == [
            r.competitor.name for r in r_parallel.reports
        ]
        assert _strip_ts(r_serial.markdown_report) == _strip_ts(r_parallel.markdown_report)

    def test_parallel_compare_emits_parallel_phase_event(self, mock_llm):
        events = []
        api = _parallel_api(llm=mock_llm, event_sink=events.append)
        api.compare("Cursor", "Windsurf")
        msgs = [e.message for e in events if e.event == "phase_start"]
        assert any("并行" in m for m in msgs)
