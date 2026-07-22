"""真实比赛ID端到端测试（使用LLM驱动的分析器）"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import asyncio
import pytest
import os

from post_match_review.data_source.opendota_client import OpenDotaClient
from post_match_review.data_source.match_fetcher import MatchFetcher
from post_match_review.orchestrator.strategic_loop import StrategicLoop
from post_match_review.orchestrator.tactical_loop import TacticalLoop
from post_match_review.orchestrator.review_orchestrator import ReviewOrchestrator
from post_match_review.report.report_builder import ReportBuilder
from post_match_review.report.markdown_renderer import MarkdownRenderer
from post_match_review.engines.stop_verifier import StopVerifier
from post_match_review.analyzers.laning_analyzer import LaningAnalyzer
from post_match_review.analyzers.teamfight_analyzer import TeamfightAnalyzer
from post_match_review.analyzers.economy_analyzer import EconomyAnalyzer
from post_match_review.analyzers.decision_analyzer import DecisionAnalyzer
from post_match_review.analyzers.vision_analyzer import VisionAnalyzer
from post_match_review.llm.client import LLMClient
from post_match_review.domain_types.state import ReviewAgentState
from post_match_review.domain_types.match_data import MatchData
from post_match_review.interfaces.data_source import IMatchDataSource


class MatchFetcherAdapter:
    """适配器：将 MatchFetcher 适配为 IMatchDataSource"""

    def __init__(self, fetcher: MatchFetcher) -> None:
        self._fetcher = fetcher

    async def fetch_match(self, match_id: str) -> MatchData:
        return await self._fetcher.fetch_and_parse(match_id)


@pytest.mark.asyncio
async def test_real_match_with_llm() -> None:
    """使用真实比赛ID和LLM测试完整流程"""
    match_id = "8905359313"  # 验收测试指定的比赛ID

    print(f"\n{'='*60}")
    print(f"开始真实比赛端到端测试（LLM驱动）: match_id={match_id}")
    print(f"{'='*60}\n")

    # 检查环境变量
    api_key = os.getenv("DEEPSEEK_API_KEY") or os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("✗ 未设置 DEEPSEEK_API_KEY 或 OPENAI_API_KEY，无法运行LLM测试")
        print("请设置环境变量后重试")
        return
    print(f"✓ API Key 已设置")

    # 1. 创建真实数据源
    print("\n步骤 1: 创建 OpenDota 客户端...")
    opendota_client = OpenDotaClient(timeout=30.0, max_retries=3)
    match_fetcher = MatchFetcher(client=opendota_client)
    data_source = MatchFetcherAdapter(match_fetcher)

    # 2. 获取真实比赛数据
    print(f"步骤 2: 从 OpenDota API 获取比赛数据...")
    try:
        match_data = await data_source.fetch_match(match_id)
        print(f"✓ 数据获取成功:")
        print(f"  - 时长: {match_data.duration}秒 ({match_data.duration // 60}分钟)")
        print(f"  - 胜利方: {'天辉' if match_data.radiant_win else '夜魇'}")
        print(f"  - 比分: {match_data.radiant_score} - {match_data.dire_score}")
        print(f"  - 玩家数: {len(match_data.players)}")
    except Exception as e:
        print(f"✗ 数据获取失败: {e}")
        return

    # 3. 战略评估
    print(f"\n步骤 3: 战略评估...")
    config = {
        "max_iterations_per_phase": 2,
        "required_phases": ["laning", "teamfight", "economy", "decisions"],
        "min_confidence": 0.5,
        "default_budgets": {
            "laning": 2,
            "teamfight": 2,
            "economy": 2,
            "decisions": 2,
            "vision": 1,
        },
    }
    strategic_loop = StrategicLoop(config=config)
    strategy = strategic_loop.evaluate(match_data)
    print(f"✓ 战略评估完成:")
    print(f"  - 比赛类型: {strategy.match_type}")
    print(f"  - 分析阶段: {strategy.priority_phases}")

    # 4. 创建LLM客户端
    print(f"\n步骤 4: 创建 LLM 客户端...")
    llm_client = LLMClient(
        default_model="deepseek-v4-pro",  # DeepSeek 模型
        max_retries=2,
        timeout=60.0,
    )
    print(f"✓ LLM 客户端已创建")

    # 5. 创建分析器（使用LLM驱动的分析器）
    print(f"\n步骤 5: 创建 LLM 驱动的分析器...")

    def tactical_loop_factory(phase: str) -> TacticalLoop:
        if phase == "laning":
            analyzer = LaningAnalyzer(llm_client=llm_client)
        elif phase == "teamfight":
            analyzer = TeamfightAnalyzer(llm_client=llm_client)
        elif phase == "economy":
            analyzer = EconomyAnalyzer(llm_client=llm_client)
        elif phase == "decisions":
            analyzer = DecisionAnalyzer(llm_client=llm_client)
        elif phase == "vision":
            analyzer = VisionAnalyzer(llm_client=llm_client)
        else:
            # 默认使用对线分析器
            analyzer = LaningAnalyzer(llm_client=llm_client)
        return TacticalLoop(analyzer=analyzer, max_iterations=2)

    # 6. 创建停止验证器
    stop_verifier = StopVerifier(
        required_phases=["laning", "teamfight", "economy", "decisions"],
        min_confidence=0.5,
    )

    # 7. 创建报告组件
    report_builder = ReportBuilder()
    markdown_renderer = MarkdownRenderer()

    # 8. 创建状态和编排器
    state = ReviewAgentState(match_id=match_id)
    orchestrator = ReviewOrchestrator(
        data_source=data_source,
        strategic_loop=strategic_loop,
        tactical_loop_factory=tactical_loop_factory,
        stop_verifier=stop_verifier,
        report_builder=report_builder,
        state=state,
        markdown_renderer=markdown_renderer,
        max_verification_retries=1,
    )

    # 9. 执行完整复盘
    print(f"\n步骤 6: 执行完整复盘流程（LLM驱动）...")
    print("这可能需要几分钟时间，请耐心等待...\n")
    report = await orchestrator.review(match_id)

    # 10. 验证结果
    print(f"\n步骤 7: 验证结果...")
    print(f"✓ 报告生成成功:")
    print(f"  - 比赛ID: {report.match_id}")
    print(f"  - 终态: {report.terminal_state}")
    print(f"  - 整体评分: {report.overall_score:.1f}/10")
    print(f"  - 整体置信度: {report.overall_confidence:.2f}")
    print(f"  - 分析阶段数: {len(report.phase_results)}")
    print(f"  - 关键发现数: {len(report.key_findings)}")
    print(f"  - 改进建议数: {len(report.improvement_areas)}")
    print(f"  - Markdown报告长度: {len(report.markdown_report)}字符")

    # 11. 打印各阶段结果
    print(f"\n各阶段分析结果:")
    for result in report.phase_results:
        print(f"  [{result.phase}]")
        print(f"    - 置信度: {result.confidence:.2f}")
        print(f"    - 迭代次数: {result.iterations_used}")
        print(f"    - 结论数: {len(result.conclusions)}")
        for i, conclusion in enumerate(result.conclusions[:2], 1):
            print(f"      {i}. {conclusion.title}")
            print(f"         {conclusion.content[:80]}...")

    # 12. 打印关键发现
    if report.key_findings:
        print(f"\n关键发现:")
        for finding in report.key_findings[:5]:
            print(f"  - {finding}")

    # 13. 打印改进建议
    if report.improvement_areas:
        print(f"\n改进建议:")
        for area in report.improvement_areas[:3]:
            print(f"  - {area}")

    # 14. 保存Markdown报告
    output_file = f"reports/test_report_llm_{match_id}.md"
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(report.markdown_report)
    print(f"\n✓ Markdown报告已保存到: {output_file}")

    # 15. 验证验收标准
    print(f"\n{'='*60}")
    print("验收标准检查:")
    print(f"{'='*60}")

    checks = [
        ("包含必要分析阶段", all(
            phase in [r.phase for r in report.phase_results]
            for phase in ["laning", "teamfight", "economy", "decisions"]
        )),
        ("整体置信度 >= 0.6", report.overall_confidence >= 0.6),
        ("每条结论有证据支撑", all(
            c.has_evidence
            for r in report.phase_results
            for c in r.conclusions
        )),
        ("Markdown报告非空", len(report.markdown_report) > 0),
        ("报告包含摘要", "比赛摘要" in report.markdown_report),
        ("报告包含各阶段分析", "详细分析" in report.markdown_report),
        ("报告包含改进建议", "改进建议" in report.markdown_report),
    ]

    all_passed = True
    for check_name, passed in checks:
        status = "✓" if passed else "✗"
        print(f"  {status} {check_name}")
        if not passed:
            all_passed = False

    print(f"\n{'='*60}")
    if all_passed:
        print("✓ 所有验收标准通过！")
    else:
        print("✗ 部分验收标准未通过")
    print(f"{'='*60}\n")

    # 清理
    await llm_client.close()
    await opendota_client.close()


if __name__ == "__main__":
    asyncio.run(test_real_match_with_llm())
