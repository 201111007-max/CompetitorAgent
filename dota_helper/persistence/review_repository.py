"""复盘报告持久化仓库

将 ReviewReport 序列化为 JSON 并存储到 ~/.dota_helper/data/reviews/。
支持保存、加载、检查存在、列出报告摘要等操作。
"""
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

from dota_helper.data_path_manager import DataPathManager
from dota_helper.domain_types.report import ReviewReport, MatchSummary
from dota_helper.domain_types.analysis import AnalysisResult, Conclusion
from dota_helper.observability.logger import get_logger

logger = get_logger("persistence.review_repository")


class ReviewRepository:
    """复盘报告持久化仓库

    将 ReviewReport 序列化为 JSON 并存储到 DataPathManager.reviews_dir。
    每次复盘的报告保存为 {match_id}.json。

    Args:
        path_manager: 统一数据路径管理器
    """

    def __init__(self, path_manager: DataPathManager) -> None:
        """初始化报告仓库

        Args:
            path_manager: 统一数据路径管理器
        """
        self._path_manager = path_manager

    async def save(self, report: ReviewReport) -> Path:
        """保存复盘报告

        Args:
            report: 完整复盘报告

        Returns:
            Path: 保存的文件路径
        """
        path = self._path_manager.get_review_path(report.match_id)
        path.parent.mkdir(parents=True, exist_ok=True)

        try:
            data = report.to_dict()
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2, default=str)
            logger.info("报告保存成功: match_id=%s, path=%s", report.match_id, path)
            return path
        except Exception as e:
            logger.error("报告保存失败: match_id=%s, error=%s", report.match_id, str(e))
            raise

    async def load(self, match_id: str) -> Optional[ReviewReport]:
        """加载复盘报告

        Args:
            match_id: 比赛 ID

        Returns:
            Optional[ReviewReport]: 报告实例，不存在时返回 None
        """
        path = self._path_manager.get_review_path(match_id)
        if not path.exists():
            logger.debug("报告不存在: match_id=%s", match_id)
            return None

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            report = self._dict_to_report(data)
            logger.info("报告加载成功: match_id=%s", match_id)
            return report
        except Exception as e:
            logger.error("报告加载失败: match_id=%s, error=%s", match_id, str(e))
            return None

    async def exists(self, match_id: str) -> bool:
        """检查报告是否存在

        Args:
            match_id: 比赛 ID

        Returns:
            bool: 报告是否存在
        """
        return self._path_manager.get_review_path(match_id).exists()

    async def list_reviews(self, limit: int = 50) -> List[Dict[str, Any]]:
        """列出最近复盘报告摘要

        按修改时间倒序排列，返回每个报告的 match_id、overall_score、
        overall_confidence、created_at 等摘要信息。

4
        Args:
            limit: 最大返回数量

        Returns:
            List[Dict[str, Any]]: 报告摘要列表
        """
        reviews_dir = self._path_manager.reviews_dir
        if not reviews_dir.exists():
            return []

        summaries: List[Dict[str, Any]] = []
        json_files = sorted(
            reviews_dir.glob("*.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )

        for path in json_files[:limit]:
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                summaries.append({
                    "match_id": data.get("match_id", path.stem),
                    "overall_score": data.get("overall_score", 0.0),
                    "overall_confidence": data.get("overall_confidence", 0.0),
                    "terminal_state": data.get("terminal_state", ""),
                    "created_at": data.get("created_at", ""),
                    "key_findings_count": len(data.get("key_findings", [])),
                })
            except Exception as e:
                logger.warning("读取报告摘要失败: path=%s, error=%s", path, str(e))

        return summaries

    def _dict_to_report(self, data: Dict[str, Any]) -> ReviewReport:
        """将字典反序列化为 ReviewReport

        Args:
            data: JSON 字典

        Returns:
            ReviewReport: 报告实例
        """
        summary_data = data.get("match_summary", {})
        match_summary = MatchSummary(
            match_id=summary_data.get("match_id", ""),
            duration=summary_data.get("duration", 0),
            radiant_win=summary_data.get("radiant_win", False),
            radiant_score=summary_data.get("radiant_score", 0),
            dire_score=summary_data.get("dire_score", 0),
            user_hero=summary_data.get("user_hero", "Unknown"),
            user_team_win=summary_data.get("user_team_win", False),
            key_events=summary_data.get("key_events", []),
        )

        # 反序列化 phase_results
        phase_results: List[AnalysisResult] = []
        for pr_data in data.get("phase_results", []):
            conclusions: List[Conclusion] = []
            for c_data in pr_data.get("conclusions", []):
                conclusions.append(Conclusion(
                    title=c_data.get("title", ""),
                    content=c_data.get("content", ""),
                    evidence=c_data.get("evidence", []),
                    has_evidence=c_data.get("has_evidence", False),
                    impact=c_data.get("impact", "medium"),
                ))
            phase_results.append(AnalysisResult(
                phase=pr_data.get("phase", ""),
                conclusions=conclusions,
                confidence=pr_data.get("confidence", 0.0),
                iterations_used=pr_data.get("iterations_used", 0),
                tokens_consumed=pr_data.get("tokens_consumed", 0),
                analysis_text=pr_data.get("analysis_text", ""),
            ))

        return ReviewReport(
            match_id=data.get("match_id", ""),
            match_summary=match_summary,
            phase_results=phase_results,
            overall_score=data.get("overall_score", 0.0),
            overall_confidence=data.get("overall_confidence", 0.0),
            key_findings=data.get("key_findings", []),
            improvement_areas=data.get("improvement_areas", []),
            markdown_report=data.get("markdown_report", ""),
            terminal_state=data.get("terminal_state", ""),
            created_at=data.get("created_at", ""),
        )
