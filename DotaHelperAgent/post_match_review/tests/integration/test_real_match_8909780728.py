"""用真实比赛数据跑完整复盘流程，验证层 B 重构后的输出格式"""
import asyncio
import json
import sys
from pathlib import Path

# 确保项目路径在 sys.path 中
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from post_match_review import create_default_api
from post_match_review.observability.logger import get_logger

logger = get_logger("test_real_match")


async def main() -> None:
    """主函数：用 match_id=8909780728 跑完整复盘"""
    match_id = "8909780728"
    logger.info("开始复盘: match_id=%s", match_id)

    # 创建 API 门面
    api = create_default_api()

    # 执行复盘
    try:
        report = await api.review(match_id)
        logger.info("复盘完成!")

        # 打印报告摘要
        print("\n" + "=" * 60)
        print(f"复盘报告 - 比赛 {match_id}")
        print("=" * 60)

        # 基本信息
        print(f"\n📊 总体评分: {report.overall_score:.1f}/10")
        print(f"📈 总体置信度: {report.overall_confidence:.1%}")
        print(f"🏁 终态: {report.terminal_state}")

        # 比赛摘要
        if report.match_summary:
            ms = report.match_summary
            print(f"\n🎮 比赛摘要:")
            print(f"  - 英雄: {ms.user_hero}")
            print(f"  - 时长: {ms.duration // 60}:{ms.duration % 60:02d}")
            print(f"  - 结果: {'胜利' if ms.user_team_win else '失败'}")
            print(f"  - 比分: {ms.radiant_score} - {ms.dire_score}")

        # 各阶段分析结果
        print(f"\n📋 各阶段分析结果:")
        for phase_result in report.phase_results:
            print(f"\n  ── {phase_result.phase} ──")
            print(f"  置信度: {phase_result.confidence:.1%}")
            print(f"  结论数: {len(phase_result.conclusions)}")
            for i, conclusion in enumerate(phase_result.conclusions[:3], 1):
                print(f"  {i}. [{conclusion.impact}] {conclusion.title}")
                print(f"     {conclusion.content[:80]}...")
                if conclusion.evidence:
                    print(f"     证据: {', '.join(conclusion.evidence[:2])}")

        # 关键发现
        if report.key_findings:
            print(f"\n🔑 关键发现:")
            for i, finding in enumerate(report.key_findings[:5], 1):
                print(f"  {i}. {finding}")

        # 改进建议
        if report.improvement_areas:
            print(f"\n💡 改进建议:")
            for i, area in enumerate(report.improvement_areas[:5], 1):
                print(f"  {i}. {area}")

        # Markdown 报告
        if report.markdown_report:
            print(f"\n📝 Markdown 报告:")
            print("-" * 40)
            # 只打印前 2000 字符
            md = report.markdown_report[:2000]
            print(md)
            if len(report.markdown_report) > 2000:
                print(f"\n... (已截断，共 {len(report.markdown_report)} 字符)")

        # 输出完整 JSON 格式（结构验证）
        print("\n" + "=" * 60)
        print("JSON 报告结构验证:")
        print("=" * 60)
        report_dict = report.to_dict()
        report_json = json.dumps(report_dict, ensure_ascii=False, indent=2, default=str)
        print(f"报告总长度: {len(report_json)} 字符")
        print(f"包含的阶段: {[pr['phase'] for pr in report_dict.get('phase_results', [])]}")
        # 验证各阶段有结论
        for pr in report_dict.get("phase_results", []):
            phase = pr["phase"]
            n_conclusions = len(pr.get("conclusions", []))
            confidence = pr.get("confidence", 0)
            print(f"  {phase}: {n_conclusions} 条结论, 置信度 {confidence:.2f}")

        print("\n✅ 复盘流程完成！输出格式正常。")

    except Exception as e:
        logger.error("复盘失败: %s", str(e), exc_info=True)
        print(f"\n❌ 复盘失败: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
