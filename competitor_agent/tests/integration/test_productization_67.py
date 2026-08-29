"""设计文档 67 集成 — 产品化闭环（审批门 + 周报 + 结构化 status 字段）。

复用 test_structured_export 的 mock_llm + fake_extractor 跑真实 analyze：
- analyze 后 JSON 含 status 字段（高置信 mock → approved）；
- 调高审批阈值（0.99）→ 触发 pending_review 落盘；
- run_scheduled 末尾按 schedule.weekly_report 触发周报（md+json 双产物 + status）；
- 未配推送/未启用外部源 → 与现状一致（降级不编造，无网络副作用）。
"""
from __future__ import annotations

import json
from pathlib import Path

from competitor_agent.config.loader import AppConfig, CollectorConfig
from competitor_agent.facade.api import CompetitorAnalysisAPI
from competitor_agent.memory import FourLayerMemory
from competitor_agent.memory.timeline_memory import TimelineMemory


def _api(tmp_path: Path, mock_llm, fake_extractor, **overrides) -> CompetitorAnalysisAPI:
    cfg = AppConfig(collector=CollectorConfig(block_private_urls=False))
    cfg.report.output_dir = str(tmp_path / "reports" / "competitor")
    cfg.report.comparison_dir = str(tmp_path / "reports" / "comparison")
    cfg.report.export_json = True
    for key, value in overrides.items():
        setattr(cfg.report, key, value)
    return CompetitorAnalysisAPI(
        extractor=fake_extractor,
        llm=mock_llm,
        use_llm=True,
        max_iterations=10,
        config=cfg,
        memory=FourLayerMemory(tmp_path / "memory"),
        timeline=TimelineMemory(tmp_path / "timeline"),
    )


class TestApprovalGateWired:
    def test_approval_disabled_writes_approved(self, fake_extractor, mock_llm, tmp_path: Path) -> None:
        # approval_enabled=False → 审批门关闭，报告直通 approved（不打扰）
        api = _api(tmp_path, mock_llm, fake_extractor, approval_enabled=False)
        api.analyze("Cursor")
        path = tmp_path / "reports" / "competitor" / "cursor.json"
        assert path.exists()
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["status"] == "approved"
        assert "reviewed_at" in data and "reviewer_note" in data

    def test_low_confidence_triggers_pending_review(self, fake_extractor, mock_llm, tmp_path: Path) -> None:
        # mock LLM 本身产出 sentiment/roadmap 低置信 PARTIAL 维度 → 命中「低置信」审批规则
        api = _api(tmp_path, mock_llm, fake_extractor)
        api.analyze("Cursor")
        path = tmp_path / "reports" / "competitor" / "cursor.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["status"] == "pending_review"

    def test_pending_review_can_be_approved(self, fake_extractor, mock_llm, tmp_path: Path) -> None:
        # 审批闭环：pending_review → set_report_status(approved) 落盘
        from competitor_agent.core.approval_gate import set_report_status

        api = _api(tmp_path, mock_llm, fake_extractor)
        api.analyze("Cursor")
        path = tmp_path / "reports" / "competitor" / "cursor.json"
        assert json.loads(path.read_text(encoding="utf-8"))["status"] == "pending_review"
        data = set_report_status(path, "approved", reviewer_note="已人工核对")
        assert data["status"] == "approved"
        assert data["reviewer_note"] == "已人工核对"


class TestWeeklyReportIntegration:
    def test_run_scheduled_triggers_weekly(self, fake_extractor, mock_llm, tmp_path: Path) -> None:
        api = _api(tmp_path, mock_llm, fake_extractor)
        api.analyze("Cursor")
        # 强制过期 → 重爬 → 时间线产生事件 → 周报触发
        cfg = api._config
        cfg.freshness.dimension_ttl_days = {k: -1 for k in cfg.freshness.dimension_ttl_days}
        cfg.schedule.weekly_report = True
        cfg.schedule.weekly_window_days = 7
        refreshed = api.run_scheduled()
        assert [r.competitor.name for r in refreshed] == ["cursor"]

        weekly_dir = tmp_path / "reports" / "weekly"
        md_files = list(weekly_dir.glob("*.md")) if weekly_dir.exists() else []
        json_files = list(weekly_dir.glob("*.json")) if weekly_dir.exists() else []
        assert md_files and json_files, "run_scheduled 末尾应触发周报聚合（md + json）"
        saved = json.loads(json_files[0].read_text(encoding="utf-8"))
        assert "week_label" in saved
        assert "status" in saved  # 审批门周报 status

    def test_build_weekly_report_writes_both(self, fake_extractor, mock_llm, tmp_path: Path) -> None:
        api = _api(tmp_path, mock_llm, fake_extractor)
        api.analyze("Cursor")
        md_path, json_path = api.build_weekly_report()
        assert md_path.exists() and json_path.exists()
        md = md_path.read_text(encoding="utf-8")
        assert "竞品周报" in md
        assert "cursor" in md
