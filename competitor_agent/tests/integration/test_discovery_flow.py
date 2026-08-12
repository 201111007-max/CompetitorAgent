"""集成测试 — 设计文档 20：N 向对比 + 市场普查/发现 完整链路

- compare(*competitors) 产出品类格局矩阵（维度 × 竞品）
- discover() 从 web_tool 枚举候选 → 逐个分析 → 合并为格局报告
- 普查任务不再产出假竞品"ai-coding-agent"，也不 0 维度
"""

from __future__ import annotations

import pytest

from competitor_agent.facade.api import CompetitorAnalysisAPI

pytestmark = pytest.mark.integration


class TestCompareIntegration:
    def test_compare_nway_market_matrix(self, fake_extractor) -> None:
        api = CompetitorAnalysisAPI(extractor=fake_extractor, use_llm=False, max_iterations=10)
        result = api.compare("Cursor", "Windsurf", "Copilot")

        assert len(result.reports) == 3
        md = result.markdown_report
        assert "品类格局矩阵" in md
        assert "cursor" in md and "windsurf" in md and "copilot" in md
        # 矩阵表头含维度列 + 竞品列
        assert md.startswith("# cursor vs windsurf vs copilot 竞品格局对比报告")

    def test_compare_combined_task(self, fake_extractor) -> None:
        api = CompetitorAnalysisAPI(extractor=fake_extractor, use_llm=False, max_iterations=10)
        result = api.compare("对比 Cursor 和 Windsurf")
        assert len(result.reports) == 2


class TestDiscoveryIntegration:
    def test_discovery_produces_real_candidates_not_fake(self, fake_extractor) -> None:
        """web_tool 返回候选 → discover 逐个分析 → 矩阵报告；不产出假竞品。"""

        def web_tool(task: str) -> list[dict]:
            return [
                {"name": "cursor", "home": "https://www.cursor.com", "pricing": "https://www.cursor.com/pricing"},
                {"name": "windsurf", "home": "https://windsurf.com", "pricing": "https://windsurf.com/pricing"},
            ]

        api = CompetitorAnalysisAPI(
            extractor=fake_extractor, use_llm=False, max_iterations=10, web_tool=web_tool
        )
        result = api.discover("帮我寻找市场上所有 AI coding agent")

        assert len(result.reports) >= 2
        names = [r.competitor.name for r in result.reports]
        assert "cursor" in names and "windsurf" in names
        md = result.markdown_report
        assert "ai-coding-agent" not in md, "不应再产出整句拼成的假竞品"
        assert "品类格局矩阵" in md
        # 发现出的竞品带官方链接，至少产出维度结论（不 0 维度）
        assert any(r.dimension_results for r in result.reports)

    def test_discovery_fallback_list_still_analyzes(self, fake_extractor) -> None:
        """无 web_tool：内置兜底清单，报告非空且不再 0 维度。"""
        api = CompetitorAnalysisAPI(extractor=fake_extractor, use_llm=False, max_iterations=10)
        result = api.discover("市场上所有 AI coding agent")

        assert len(result.reports) >= 2
        assert any(r.dimension_results for r in result.reports)
        assert "品类格局矩阵" in result.markdown_report

    def test_full_analyze_discovery_task_via_cli_path(self, fake_extractor, capsys) -> None:
        """普查任务经 analyze 路由：真实产出矩阵而非 0 维度（问题 20 主诉求）。"""
        from competitor_agent.cli import _run_analyze

        api = CompetitorAnalysisAPI(extractor=fake_extractor, use_llm=False, max_iterations=10)
        _run_analyze(api, "帮我寻找现在市场上所有的 ai coding agent 并进行分析")
        captured = capsys.readouterr()
        assert "竞品格局对比报告" in captured.out
        assert "品类格局矩阵" in captured.out
        assert "ai-coding-agent" not in captured.out
