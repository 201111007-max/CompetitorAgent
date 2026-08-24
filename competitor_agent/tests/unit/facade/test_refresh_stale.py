"""设计文档 26 §5 单测（refresh_stale）：过期会话重爬 / TTL 覆盖 / --all / 开关"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from competitor_agent.config.loader import AppConfig
from competitor_agent.domain_types.competitor import Competitor
from competitor_agent.facade.api import CompetitorAnalysisAPI

# 相对"现在"锚定，避免写死历史日期导致 created_at 回退判定漂移（stale_under_ttl 用真实 now）
_NOW = datetime.now(timezone.utc)


class _Session:
    def __init__(self, competitor_name: str, raw: dict | None = None, created_at: str = "") -> None:
        self.competitor_name = competitor_name
        self.session_id = f"s_{competitor_name}"
        self.raw = raw or {}
        self.created_at = created_at or _NOW.isoformat()


class _Mem:
    def __init__(self, sessions: list[_Session]) -> None:
        self._sessions = sessions

    def list_sessions(self, competitor: str | None = None):
        if competitor:
            return [s for s in self._sessions if s.competitor_name == competitor]
        return list(self._sessions)

    def source_success_rates(self) -> dict[str, float]:
        return {}


class _StubReport:
    def __init__(self, name: str) -> None:
        self.competitor = Competitor(name=name)
        self.terminal_state = "success"
        self.dimension_results = []


def _stale_raw(age_days: float = 99) -> dict:
    return {"freshness": {"analyzed_at": _NOW.isoformat(), "dimension_ages": {"pricing": age_days}}}


def _make_api(memory, cfg: AppConfig | None = None, calls: list | None = None) -> CompetitorAnalysisAPI:
    api = CompetitorAnalysisAPI(use_llm=False, memory=memory, config=cfg or AppConfig())
    log: list[str] = calls if calls is not None else []

    def _analyze(task: str, **kw) -> _StubReport:
        log.append(task)
        return _StubReport(task)

    api.analyze = _analyze  # type: ignore[method-assign]
    return api


class TestRefreshStale:
    def test_only_stale_competitor_reanalyzed(self) -> None:
        calls: list[str] = []
        mem = _Mem([
            _Session("cursor", _stale_raw(99)),
            _Session("windsurf", {"created_at": _NOW.isoformat()}),
        ])
        api = _make_api(mem, calls=calls)
        refreshed = api.refresh_stale()
        assert calls == ["cursor"]
        assert [r.competitor.name for r in refreshed] == ["cursor"]

    def test_ttl_override_makes_session_stale(self) -> None:
        calls: list[str] = []
        # pricing age=5：默认 TTL 7 不过期；覆盖为 3 后过期
        mem = _Mem([_Session("cursor", _stale_raw(5))])
        api = _make_api(mem, calls=calls)
        assert api.refresh_stale() == []
        api.refresh_stale(ttl_override={"pricing": 3})
        assert calls == ["cursor"]

    def test_recompute_all_reanalyzes_everything(self) -> None:
        calls: list[str] = []
        mem = _Mem([
            _Session("cursor", _stale_raw(99)),
            _Session("windsurf", {"created_at": _NOW.isoformat()}),
        ])
        api = _make_api(mem, calls=calls)
        refreshed = api.refresh_stale(recompute_all=True)
        assert sorted(calls) == ["cursor", "windsurf"]
        assert len(refreshed) == 2

    def test_refresh_check_disabled_returns_empty(self) -> None:
        cfg = AppConfig()
        cfg.freshness.refresh_check_enabled = False
        mem = _Mem([_Session("cursor", _stale_raw(99))])
        api = _make_api(mem, cfg)
        assert api.refresh_stale() == []
        # 强制 --all 仍可重爬
        assert len(api.refresh_stale(recompute_all=True)) == 1

    def test_skips_comparison_aggregate_sessions(self) -> None:
        calls: list[str] = []
        mem = _Mem([
            _Session("cursor / windsurf", _stale_raw(99)),
            _Session("cursor", _stale_raw(99)),
        ])
        api = _make_api(mem, calls=calls)
        api.refresh_stale()
        assert calls == ["cursor"]

    def test_no_memory_returns_empty(self) -> None:
        api = _make_api(None)
        assert api.refresh_stale() == []

    def test_old_created_at_without_freshness_falls_back_stale(self) -> None:
        calls: list[str] = []
        old = (_NOW - timedelta(days=400)).isoformat()
        mem = _Mem([_Session("cursor", {"created_at": old})])
        api = _make_api(mem, calls=calls)
        api.refresh_stale()
        assert calls == ["cursor"]