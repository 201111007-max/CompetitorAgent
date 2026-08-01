"""PostMatchReview 分析工具 — 薄适配层

Thin adapters over PostMatchReviewAPI.  The MCP layer only imports
PostMatchReviewAPI — no internal analyzers — satisfying the
self-containment constraint.
"""

import asyncio
import json
import logging
from typing import Any, Dict, List, Optional

from dota_helper.mcp_server.server import mcp
from dota_helper.mcp_server.helpers.opendota import OpenDotaClient

logger = logging.getLogger(__name__)


def _get_review_api():
    """懒加载 PostMatchReviewAPI（避免循环导入）"""
    from dota_helper.facade.entrypoint import create_default_api
    return create_default_api()


# ---------------------------------------------------------------------------
# 1. analyze_ward_efficiency
# ---------------------------------------------------------------------------


@mcp.tool()
async def analyze_ward_efficiency(
    match_id: int,
    include_recommendations: bool = True,
) -> str:
    """分析指定比赛的视野效率

    调用 PostMatchReviewAPI 获取完整复盘报告，提取视野相关结果。

    Args:
        match_id: Dota 2 比赛ID
        include_recommendations: 是否包含改进建议，默认True

    Returns:
        视野效率分析结果，包括覆盖指标、放置时机分析、改进建议
    """
    logger.info("analyze_ward_efficiency called with: match_id=%s, include_recommendations=%s", match_id, include_recommendations)
    try:
        api = _get_review_api()
        logger.info("analyze_ward_efficiency: calling review API for match_id=%s", match_id)
        report = await api.review(str(match_id))
        logger.info("analyze_ward_efficiency: review API call succeeded")
    except Exception as exc:
        logger.error("analyze_ward_efficiency: failed: %s", exc, exc_info=True)
        return f"❌ 复盘分析失败: {exc}"

    # Extract vision-related phase results
    vision_phases = [
        pr for pr in report.phase_results
        if pr.phase == "vision"
    ]

    lines: List[str] = [
        f"# 视野效率分析 - 比赛 {match_id}",
        "",
        f"**总体评分**: {report.overall_score:.1f}/10",
        f"**置信度**: {report.overall_confidence:.1%}",
        "",
    ]

    if vision_phases:
        for vp in vision_phases:
            lines.append(f"## 阶段置信度: {vp.confidence:.1%}")
            lines.append(f"**迭代次数**: {vp.iterations_used}")
            lines.append("")
            if vp.conclusions:
                for idx, conclusion in enumerate(vp.conclusions, 1):
                    lines.append(f"### {idx}. {conclusion.title}")
                    lines.append(conclusion.content)
                    if conclusion.evidence:
                        lines.append("")
                        lines.append("**证据**:")
                        for ev in conclusion.evidence:
                            lines.append(f"  - {ev}")
                    if conclusion.suggestion:
                        lines.append(f"  **建议**: {conclusion.suggestion}")
                    lines.append("")
    else:
        # Fallback: scan key_findings for vision-related items
        vision_keywords = {"视野", "眼", "ward", "vision", "obs", "sentry", "假眼", "真眼"}
        vision_findings = [
            f for f in report.key_findings
            if any(kw in f.lower() for kw in vision_keywords)
        ]
        if vision_findings:
            lines.append("## 视野相关发现")
            for f in vision_findings:
                lines.append(f"- {f}")
        else:
            lines.append("未发现独立的视野分析阶段，以下为整体发现摘要：")
            for f in report.key_findings[:5]:
                lines.append(f"- {f}")
        lines.append("")

    if include_recommendations:
        vision_improvements = [
            area for area in report.improvement_areas
            if any(kw in area.lower() for kw in {"视野", "眼", "ward", "vision"})
        ]
        if vision_improvements:
            lines.append("## 改进建议")
            for area in vision_improvements:
                lines.append(f"- {area}")
        elif report.improvement_areas:
            lines.append("## 通用改进建议")
            for area in report.improvement_areas[:5]:
                lines.append(f"- {area}")

    logger.info("analyze_ward_efficiency: completed")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 2. analyze_roshan_timing
# ---------------------------------------------------------------------------


@mcp.tool()
async def analyze_roshan_timing(
    match_id: int,
    include_teamfight_context: bool = True,
) -> str:
    """分析指定比赛的肉山时机决策

    调用 PostMatchReviewAPI 获取完整复盘报告，提取决策/团战相关结果。

    Args:
        match_id: Dota 2 比赛ID
        include_teamfight_context: 是否包含团战上下文，默认True

    Returns:
        肉山时机分析结果
    """
    logger.info("analyze_roshan_timing called with: match_id=%s, include_teamfight_context=%s", match_id, include_teamfight_context)
    try:
        api = _get_review_api()
        logger.info("analyze_roshan_timing: calling review API for match_id=%s", match_id)
        report = await api.review(str(match_id))
        logger.info("analyze_roshan_timing: review API call succeeded")
    except Exception as exc:
        logger.error("analyze_roshan_timing: failed: %s", exc, exc_info=True)
        return f"❌ 复盘分析失败: {exc}"

    # Extract decision and teamfight phase results
    relevant_phases = [
        pr for pr in report.phase_results
        if pr.phase in ("decisions", "teamfight")
    ]

    lines: List[str] = [
        f"# 肉山时机分析 - 比赛 {match_id}",
        "",
        f"**总体评分**: {report.overall_score:.1f}/10",
        f"**置信度**: {report.overall_confidence:.1%}",
        "",
    ]

    # Scan conclusions for Roshan-related items
    roshan_keywords = {"roshan", "肉山", "aegis", "不朽盾", "rosh"}
    roshan_conclusions = []
    for pr in relevant_phases:
        for c in pr.conclusions:
            text = f"{c.title} {c.content}".lower()
            if any(kw in text for kw in roshan_keywords):
                roshan_conclusions.append((pr.phase, c))

    if roshan_conclusions:
        lines.append("## 肉山相关决策")
        for phase_name, conclusion in roshan_conclusions:
            lines.append(f"### [{phase_name}] {conclusion.title}")
            lines.append(conclusion.content)
            if conclusion.evidence:
                lines.append("")
                lines.append("**证据**:")
                for ev in conclusion.evidence:
                    lines.append(f"  - {ev}")
            if conclusion.suggestion:
                lines.append(f"  **建议**: {conclusion.suggestion}")
            lines.append("")
    else:
        # Fallback: check key_findings
        roshan_findings = [
            f for f in report.key_findings
            if any(kw in f.lower() for kw in roshan_keywords)
        ]
        if roshan_findings:
            lines.append("## 肉山相关发现")
            for f in roshan_findings:
                lines.append(f"- {f}")
        else:
            lines.append("未发现肉山相关的专门分析结论。")
            lines.append("")
            lines.append("## 整体关键发现")
            for f in report.key_findings[:5]:
                lines.append(f"- {f}")
        lines.append("")

    if include_teamfight_context:
        tf_phases = [pr for pr in relevant_phases if pr.phase == "teamfight"]
        if tf_phases:
            lines.append("## 团战上下文")
            for tf in tf_phases:
                lines.append(f"**置信度**: {tf.confidence:.1%}")
                for c in tf.conclusions[:3]:
                    lines.append(f"- {c.title}: {c.content}")
                lines.append("")

    logger.info("analyze_roshan_timing: completed")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 3. analyze_late_game_decisions
# ---------------------------------------------------------------------------


@mcp.tool()
async def analyze_late_game_decisions(
    match_id: int,
    time_threshold_minutes: int = 30,
) -> str:
    """分析指定比赛的后期决策

    调用 PostMatchReviewAPI 获取完整复盘报告，提取决策分析中与后期相关的结果。

    Args:
        match_id: Dota 2 比赛ID
        time_threshold_minutes: 后期起始时间（分钟），默认30

    Returns:
        后期决策分析结果
    """
    logger.info("analyze_late_game_decisions called with: match_id=%s, time_threshold_minutes=%s", match_id, time_threshold_minutes)
    try:
        api = _get_review_api()
        logger.info("analyze_late_game_decisions: calling review API for match_id=%s", match_id)
        report = await api.review(str(match_id))
        logger.info("analyze_late_game_decisions: review API call succeeded")
    except Exception as exc:
        logger.error("analyze_late_game_decisions: failed: %s", exc, exc_info=True)
        return f"❌ 复盘分析失败: {exc}"

    # Extract decision phase results
    decision_phases = [
        pr for pr in report.phase_results
        if pr.phase == "decisions"
    ]

    lines: List[str] = [
        f"# 后期决策分析 - 比赛 {match_id}",
        "",
        f"**总体评分**: {report.overall_score:.1f}/10",
        f"**置信度**: {report.overall_confidence:.1%}",
        f"**后期阈值**: {time_threshold_minutes} 分钟",
        "",
    ]

    late_keywords = {
        "late", "后期", "late game", "决策", "decision",
        "push", "推进", "high ground", "高地", "buyback", "买活",
        "barrack", "兵营", "throne", "遗迹", "结束",
    }

    late_conclusions = []
    for pr in decision_phases:
        for c in pr.conclusions:
            text = f"{c.title} {c.content}".lower()
            if any(kw in text for kw in late_keywords):
                late_conclusions.append(c)

    if late_conclusions:
        lines.append("## 后期决策分析")
        for idx, conclusion in enumerate(late_conclusions, 1):
            lines.append(f"### {idx}. {conclusion.title}")
            lines.append(conclusion.content)
            if conclusion.evidence:
                lines.append("")
                lines.append("**证据**:")
                for ev in conclusion.evidence:
                    lines.append(f"  - {ev}")
            if conclusion.suggestion:
                lines.append(f"  **建议**: {conclusion.suggestion}")
            lines.append("")
    else:
        # Fallback: show all decision conclusions
        lines.append("未发现专门的后期决策分析结论，以下为全部决策分析摘要：")
        lines.append("")
        for pr in decision_phases:
            lines.append(f"**置信度**: {pr.confidence:.1%}")
            for c in pr.conclusions[:5]:
                lines.append(f"- {c.title}: {c.content}")
            lines.append("")

    # Late-game improvement areas
    late_improvements = [
        area for area in report.improvement_areas
        if any(kw in area.lower() for kw in late_keywords)
    ]
    if late_improvements:
        lines.append("## 后期改进建议")
        for area in late_improvements:
            lines.append(f"- {area}")

    logger.info("analyze_late_game_decisions: completed")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 4. generate_review_report
# ---------------------------------------------------------------------------


@mcp.tool()
async def generate_review_report(match_id: int) -> str:
    """生成完整复盘报告

    调用 PostMatchReviewAPI 生成完整赛后复盘报告，包括评分、关键发现和改进建议。

    Args:
        match_id: Dota 2 比赛ID

    Returns:
        完整复盘报告，包括评分、置信度、关键发现、改进建议
    """
    logger.info("generate_review_report called with: match_id=%s", match_id)
    try:
        api = _get_review_api()
        logger.info("generate_review_report: calling review API for match_id=%s", match_id)
        report = await api.review(str(match_id))
        logger.info("generate_review_report: review API call succeeded")
    except Exception as exc:
        logger.error("generate_review_report: failed: %s", exc, exc_info=True)
        return f"❌ 复盘分析失败: {exc}"

    lines: List[str] = [
        f"# 赛后复盘报告 - 比赛 {match_id}",
        "",
        "## 总体评分",
        f"- **评分**: {report.overall_score:.1f}/10",
        f"- **置信度**: {report.overall_confidence:.1%}",
        f"- **终态**: {report.terminal_state or 'N/A'}",
    ]

    # Match summary
    if report.match_summary:
        ms = report.match_summary
        lines.append("")
        lines.append("## 比赛摘要")
        lines.append(f"- **比赛ID**: {ms.match_id}")
        lines.append(f"- **时长**: {ms.duration // 60}:{ms.duration % 60:02d}")
        lines.append(f"- **结果**: {'天辉胜利' if ms.radiant_win else '夜魇胜利'}")
        lines.append(f"- **比分**: {ms.radiant_score} - {ms.dire_score}")
        lines.append(f"- **使用者英雄**: {ms.user_hero}")
        lines.append(f"- **使用者阵营**: {'胜利' if ms.user_team_win else '失败'}")

    # Phase results
    if report.phase_results:
        lines.append("")
        lines.append("## 各阶段分析")
        for pr in report.phase_results:
            lines.append(f"")
            lines.append(f"### {pr.phase}（置信度: {pr.confidence:.1%}）")
            if pr.conclusions:
                for c in pr.conclusions:
                    lines.append(f"- **{c.title}**: {c.content}")
                    if c.suggestion:
                        lines.append(f"  - 建议: {c.suggestion}")

    # Key findings
    if report.key_findings:
        lines.append("")
        lines.append("## 关键发现")
        for f in report.key_findings:
            lines.append(f"- {f}")

    # Improvement areas
    if report.improvement_areas:
        lines.append("")
        lines.append("## 改进建议")
        for area in report.improvement_areas:
            lines.append(f"- {area}")

    # Markdown report (if available and concise)
    if report.markdown_report and len(report.markdown_report) < 2000:
        lines.append("")
        lines.append("## 完整报告")
        lines.append(report.markdown_report)

    logger.info("generate_review_report: completed")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 5. search_player_trends
# ---------------------------------------------------------------------------


@mcp.tool()
async def search_player_trends(
    account_id: int,
    recent_matches: int = 20,
) -> str:
    """搜索玩家近期趋势

    使用 OpenDota API 获取玩家近期比赛数据，聚合胜率、英雄池等统计。

    Args:
        account_id: 玩家账号ID（Steam32 ID）
        recent_matches: 近期比赛数量，默认20

    Returns:
        玩家趋势统计，包括胜率、英雄池分布等
    """
    logger.info("search_player_trends called with: account_id=%s, recent_matches=%s", account_id, recent_matches)

    client = OpenDotaClient.get_instance()
    if client is None:
        return "❌ OpenDota 客户端未初始化"

    try:
        matches = await client.get(
            f"players/{account_id}/matches",
            params={"limit": recent_matches},
        )
        logger.info("search_player_trends: fetched player matches successfully")
    except Exception as exc:
        logger.error("search_player_trends: failed: %s", exc, exc_info=True)
        return f"❌ 获取玩家比赛数据失败: {exc}"

    if not isinstance(matches, list) or not matches:
        logger.warning("search_player_trends: unexpected data type=%s or empty", type(matches).__name__)
        return f"❌ 未找到玩家 {account_id} 的比赛数据"

    # Aggregate statistics
    total = len(matches)
    wins = sum(1 for m in matches if m.get("radiant_win") is not None and (
        (m.get("player_slot", 128) < 128) == m.get("radiant_win", False)
    ))
    losses = total - wins
    win_rate = wins / total if total > 0 else 0.0
    logger.info("search_player_trends: aggregated player trends - total=%d, wins=%d, losses=%d, win_rate=%.3f", total, wins, losses, win_rate)

    # Hero pool
    hero_pool: Dict[int, int] = {}
    hero_wins: Dict[int, int] = {}
    for m in matches:
        hero_id = m.get("hero_id")
        if hero_id is not None:
            hero_pool[hero_id] = hero_pool.get(hero_id, 0) + 1
            is_win = (m.get("player_slot", 128) < 128) == m.get("radiant_win", False)
            if is_win:
                hero_wins[hero_id] = hero_wins.get(hero_id, 0) + 1

    # Sort by play count
    top_heroes = sorted(hero_pool.items(), key=lambda x: x[1], reverse=True)[:10]

    # Game mode distribution
    mode_counts: Dict[int, int] = {}
    for m in matches:
        mode = m.get("game_mode", 0)
        mode_counts[mode] = mode_counts.get(mode, 0) + 1

    lines: List[str] = [
        f"# 玩家趋势 - 账号 {account_id}",
        "",
        "## 概览",
        f"- **近期比赛数**: {total}",
        f"- **胜/负**: {wins} / {losses}",
        f"- **胜率**: {win_rate:.1%}",
        "",
        "## 英雄池",
        "| 英雄ID | 场次 | 胜场 | 胜率 |",
        "|--------|------|------|------|",
    ]

    for hero_id, count in top_heroes:
        hw = hero_wins.get(hero_id, 0)
        hr = hw / count if count > 0 else 0.0
        lines.append(f"| {hero_id} | {count} | {hw} | {hr:.0%} |")

    # Average stats
    avg_kills = sum(m.get("kills", 0) for m in matches) / total if total else 0
    avg_deaths = sum(m.get("deaths", 0) for m in matches) / total if total else 0
    avg_assists = sum(m.get("assists", 0) for m in matches) / total if total else 0

    lines.extend([
        "",
        "## 平均数据",
        f"- **KDA**: {avg_kills:.1f} / {avg_deaths:.1f} / {avg_assists:.1f}",
    ])

    logger.info("search_player_trends: completed")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 6. compare_match_performance
# ---------------------------------------------------------------------------


@mcp.tool()
async def compare_match_performance(
    match_id_1: int,
    match_id_2: int,
) -> str:
    """对比两场比赛的复盘表现

    并行调用 PostMatchReviewAPI 对两场比赛生成复盘报告，然后对比评分、
    关键发现和改进建议。

    Args:
        match_id_1: 第一场比赛ID
        match_id_2: 第二场比赛ID

    Returns:
        两场比赛的对比分析
    """
    logger.info("compare_match_performance called with: match_id_1=%s, match_id_2=%s", match_id_1, match_id_2)
    try:
        api = _get_review_api()
        logger.info("compare_match_performance: calling review API in parallel for match_id_1=%s and match_id_2=%s", match_id_1, match_id_2)
        report1, report2 = await asyncio.gather(
            api.review(str(match_id_1)),
            api.review(str(match_id_2)),
        )
        logger.info("compare_match_performance: parallel review API calls succeeded")
    except Exception as exc:
        logger.error("compare_match_performance: failed: %s", exc, exc_info=True)
        return f"❌ 复盘分析失败: {exc}"

    lines: List[str] = [
        f"# 比赛对比 - {match_id_1} vs {match_id_2}",
        "",
        "## 评分对比",
        f"| 指标 | 比赛 {match_id_1} | 比赛 {match_id_2} |",
        f"|------|--------------|--------------|",
        f"| 总体评分 | {report1.overall_score:.1f}/10 | {report2.overall_score:.1f}/10 |",
        f"| 置信度 | {report1.overall_confidence:.1%} | {report2.overall_confidence:.1%} |",
        f"| 关键发现数 | {len(report1.key_findings)} | {len(report2.key_findings)} |",
        f"| 改进建议数 | {len(report1.improvement_areas)} | {len(report2.improvement_areas)} |",
    ]

    # Phase comparison
    phases1 = {pr.phase: pr for pr in report1.phase_results}
    phases2 = {pr.phase: pr for pr in report2.phase_results}
    all_phases = sorted(set(phases1.keys()) | set(phases2.keys()))

    if all_phases:
        lines.append("")
        lines.append("## 阶段置信度对比")
        lines.append("| 阶段 | 比赛 1 置信度 | 比赛 2 置信度 |")
        lines.append("|------|-------------|-------------|")
        for phase in all_phases:
            c1 = phases1[phase].confidence if phase in phases1 else None
            c2 = phases2[phase].confidence if phase in phases2 else None
            c1_str = f"{c1:.1%}" if c1 is not None else "-"
            c2_str = f"{c2:.1%}" if c2 is not None else "-"
            lines.append(f"| {phase} | {c1_str} | {c2_str} |")

    # Key findings side by side
    lines.append("")
    lines.append(f"## 比赛 {match_id_1} 关键发现")
    for f in report1.key_findings[:8]:
        lines.append(f"- {f}")

    lines.append("")
    lines.append(f"## 比赛 {match_id_2} 关键发现")
    for f in report2.key_findings[:8]:
        lines.append(f"- {f}")

    # Improvement areas
    lines.append("")
    lines.append(f"## 比赛 {match_id_1} 改进建议")
    for area in report1.improvement_areas[:5]:
        lines.append(f"- {area}")

    lines.append("")
    lines.append(f"## 比赛 {match_id_2} 改进建议")
    for area in report2.improvement_areas[:5]:
        lines.append(f"- {area}")

    # Summary comparison
    score_diff = report1.overall_score - report2.overall_score
    if abs(score_diff) < 0.5:
        verdict = "两场比赛表现相当"
    elif score_diff > 0:
        verdict = f"比赛 {match_id_1} 表现更好（评分差 {score_diff:.1f}）"
    else:
        verdict = f"比赛 {match_id_2} 表现更好（评分差 {-score_diff:.1f}）"

    lines.append("")
    lines.append(f"## 总结")
    lines.append(f"- {verdict}")

    logger.info("compare_match_performance: completed")
    return "\n".join(lines)
