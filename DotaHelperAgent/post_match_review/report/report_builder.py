"""复盘报告构建器"""
from typing import List
from datetime import datetime

from post_match_review.domain_types.analysis import AnalysisResult
from post_match_review.domain_types.match_data import MatchData
from post_match_review.domain_types.report import ReviewReport, MatchSummary
from post_match_review.interfaces.report import IReportBuilder
from post_match_review.observability.logger import get_logger

logger = get_logger("pmr.report.builder")


class ReportBuilder(IReportBuilder):
    """复盘报告构建器"""

    def build(
        self,
        match_data: MatchData,
        phase_results: List[AnalysisResult],
        terminal_state: str,
    ) -> ReviewReport:
        """聚合分析结果生成报告

        Args:
            match_data: 结构化比赛数据
            phase_results: 各阶段分析结果
            terminal_state: 终态类型

        Returns:
            ReviewReport: 完整报告
        """
        logger.info("开始构建复盘报告: match_id=%s", match_data.match_id)

        # 1. 构建比赛摘要
        match_summary = self._build_match_summary(match_data)

        # 2. 计算整体评分
        overall_score = self._calculate_overall_score(phase_results)

        # 3. 计算整体置信度
        overall_confidence = self._calculate_overall_confidence(phase_results)

        # 4. 提取关键发现
        key_findings = self._extract_key_findings(phase_results)

        # 5. 提取改进方向
        improvement_areas = self._extract_improvement_areas(phase_results)

        # 6. 交叉验证
        cross_validation_notes = self.cross_validate(phase_results)
        if cross_validation_notes:
            key_findings.extend(cross_validation_notes)

        report = ReviewReport(
            match_id=match_data.match_id,
            match_summary=match_summary,
            phase_results=phase_results,
            overall_score=overall_score,
            overall_confidence=overall_confidence,
            key_findings=key_findings,
            improvement_areas=improvement_areas,
            terminal_state=terminal_state,
            created_at=datetime.now().isoformat(),
        )

        logger.info(
            "报告构建完成: score=%.1f, confidence=%.2f, findings=%d",
            overall_score,
            overall_confidence,
            len(key_findings),
        )

        return report

    def cross_validate(
        self,
        phase_results: List[AnalysisResult],
    ) -> List[str]:
        """交叉验证各阶段结论一致性

        Args:
            phase_results: 各阶段分析结果

        Returns:
            List[str]: 发现的矛盾或补充建议
        """
        notes: List[str] = []

        # 检查不同阶段的置信度差异
        if len(phase_results) >= 2:
            confidences = [r.confidence for r in phase_results]
            max_conf = max(confidences)
            min_conf = min(confidences)

            if max_conf - min_conf > 0.3:
                low_phases = [
                    r.phase for r in phase_results if r.confidence == min_conf
                ]
                notes.append(
                    f"阶段置信度差异较大 ({max_conf:.2f} vs {min_conf:.2f})，"
                    f"低置信度阶段: {', '.join(low_phases)}"
                )

        # 检查结论数量是否均衡
        conclusion_counts = [len(r.conclusions) for r in phase_results]
        if conclusion_counts:
            avg_count = sum(conclusion_counts) / len(conclusion_counts)
            for result in phase_results:
                if len(result.conclusions) < avg_count * 0.5:
                    notes.append(
                        f"阶段 {result.phase} 结论数量偏少 "
                        f"({len(result.conclusions)} < 平均 {avg_count:.0f})"
                    )

        return notes

    def _build_match_summary(self, match_data: MatchData) -> MatchSummary:
        """构建比赛摘要

        Args:
            match_data: 结构化比赛数据

        Returns:
            MatchSummary: 比赛摘要
        """
        # 找到用户英雄
        user_hero = "Unknown"
        user_team_win = False
        for player in match_data.players:
            if player.is_user:
                user_hero = player.hero_name
                user_team_win = (
                    match_data.radiant_win if player.is_radiant
                    else not match_data.radiant_win
                )
                break

        # 提取关键事件
        key_events: List[str] = []
        if match_data.raw_metadata.get("objectives"):
            for obj in match_data.raw_metadata["objectives"][:5]:
                obj_type = obj.get("type", "unknown")
                time_min = obj.get("time", 0) // 60
                key_events.append(f"{time_min}分钟: {obj_type}")

        return MatchSummary(
            match_id=match_data.match_id,
            duration=match_data.duration,
            radiant_win=match_data.radiant_win,
            radiant_score=match_data.radiant_score,
            dire_score=match_data.dire_score,
            user_hero=user_hero,
            user_team_win=user_team_win,
            key_events=key_events,
        )

    def _calculate_overall_score(
        self,
        phase_results: List[AnalysisResult],
    ) -> float:
        """计算整体评分（1-10）

        Args:
            phase_results: 各阶段分析结果

        Returns:
            float: 整体评分
        """
        if not phase_results:
            return 5.0

        # 基于置信度和结论质量计算
        total_score = 0.0
        for result in phase_results:
            # 基础分 = 置信度 * 10
            phase_score = result.confidence * 10

            # 结论数量加成
            conclusion_bonus = min(len(result.conclusions) * 0.2, 1.0)
            phase_score += conclusion_bonus

            # 证据支撑加成
            evidence_count = sum(1 for c in result.conclusions if c.has_evidence)
            evidence_bonus = min(evidence_count * 0.1, 1.0)
            phase_score += evidence_bonus

            total_score += min(phase_score, 10.0)

        return total_score / len(phase_results)

    def _calculate_overall_confidence(
        self,
        phase_results: List[AnalysisResult],
    ) -> float:
        """计算整体置信度

        Args:
            phase_results: 各阶段分析结果

        Returns:
            float: 整体置信度
        """
        if not phase_results:
            return 0.0

        # 加权平均（基于迭代次数）
        total_weight = 0.0
        weighted_sum = 0.0

        for result in phase_results:
            weight = max(result.iterations_used, 1)
            weighted_sum += result.confidence * weight
            total_weight += weight

        return weighted_sum / total_weight if total_weight > 0 else 0.0

    def _extract_key_findings(
        self,
        phase_results: List[AnalysisResult],
    ) -> List[str]:
        """提取关键发现

        Args:
            phase_results: 各阶段分析结果

        Returns:
            List[str]: 关键发现列表
        """
        findings: List[str] = []

        for result in phase_results:
            for conclusion in result.conclusions:
                if conclusion.impact == "high" or conclusion.has_evidence:
                    findings.append(f"[{result.phase}] {conclusion.title}")

        return findings[:10]  # 限制数量

    def _extract_improvement_areas(
        self,
        phase_results: List[AnalysisResult],
    ) -> List[str]:
        """提取改进方向

        Args:
            phase_results: 各阶段分析结果

        Returns:
            List[str]: 改进方向列表
        """
        areas: List[str] = []

        for result in phase_results:
            for conclusion in result.conclusions:
                if conclusion.suggestion:
                    areas.append(f"[{result.phase}] {conclusion.suggestion}")

        return areas[:5]  # 限制数量
