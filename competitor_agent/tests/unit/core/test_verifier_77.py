"""设计文档 77：NLI 事实校验器——三态判定 / superseded 链路 / 数值快路径 / 护栏继承。

snapshot（知识库检索，确定性）/ refetch（联网重抓，受 FetchPolicy 护栏）双模式；
矛盾 ≠ 幻觉：superseded（现实已变）不计幻觉率；数值冲突不过 LLM 直接 contradicted。
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from competitor_agent.collector.fetch_policy import FetchPolicy
from competitor_agent.config.loader import VerifierConfig
from competitor_agent.core.verifier import Claim, NLIVerifier, ReportVerification


def _chunk(text: str, url: str = "https://example.com/pricing") -> SimpleNamespace:
    return SimpleNamespace(text=text, source_url=url)


class _ScriptedLLM:
    """按 prompt 内嵌的来源文本路由判定结果（确定性脚本）。"""

    total_cost_usd = 0.0  # Benchmark._cost_now 读取（real 模式共享 LLM 契约）

    def __init__(self, mapping: dict[str, str] | None = None, default: str = "supported") -> None:
        # mapping: 来源文本子串 → result；default: 兜底 result
        self._mapping = mapping or {}
        self._default = default
        self.calls: list[str] = []

    def complete(self, messages: list[dict[str, str]], json_mode: bool = False, **kwargs: object) -> str:
        content = str(messages[-1].get("content", "")) if messages else ""
        self.calls.append(content[:60])
        if "原子事实断言" in content:
            return "not-json"  # 抽取 → 触发 fallback
        if "NLI" in content:
            for needle, result in self._mapping.items():
                if needle in content:
                    return json.dumps({"result": result, "reason": f"脚本判定 {result}"}, ensure_ascii=False)
            return json.dumps({"result": self._default, "reason": "脚本默认"}, ensure_ascii=False)
        return "not-json"


class _FakeRetriever:
    def __init__(self, chunks: list) -> None:
        self._chunks = chunks

    def retrieve(self, query: str, competitor: str, dimension: str = "", top_k: int = 5, strategy: str = "hybrid") -> list:
        return self._chunks[:top_k]


class _FakeTimeline:
    def __init__(self) -> None:
        self.events: list = []

    def append(self, event) -> None:
        self.events.append(event)


class _FakeAlertSink:
    def __init__(self) -> None:
        self.alerts: list = []

    def emit(self, alert) -> None:
        self.alerts.append(alert)


class _FakeIngester:
    def __init__(self) -> None:
        self.ingested: list[tuple] = []

    def ingest(self, competitor: str, dimension: str, text: str, source_url: str = "") -> int:
        self.ingested.append((competitor, dimension, text[:30], source_url))
        return 3


class TestSnapshotMode:
    def test_supported(self) -> None:
        llm = _ScriptedLLM(default="supported")
        v = NLIVerifier(llm, retriever=_FakeRetriever([_chunk("Cursor Pro 每月 20 美元")]))
        verdict = v.verify_claim(Claim(text="Cursor Pro 定价 $20/月", dimension="pricing"), "cursor")
        assert verdict.verdict == "supported"
        assert verdict.mode == "snapshot"
        assert verdict.evidence_url == "https://example.com/pricing"

    def test_contradicted(self) -> None:
        llm = _ScriptedLLM(default="contradicted")
        v = NLIVerifier(llm, retriever=_FakeRetriever([_chunk("来源文本")]))
        verdict = v.verify_claim(Claim(text="Cursor 完全免费"), "cursor")
        assert verdict.verdict == "contradicted"

    def test_no_source_unverifiable(self) -> None:
        llm = _ScriptedLLM()
        v = NLIVerifier(llm, retriever=_FakeRetriever([]))
        verdict = v.verify_claim(Claim(text="无来源断言一"), "cursor")
        assert verdict.verdict == "unverifiable"
        assert "不编造" in verdict.reason
        assert not llm.calls  # 无来源不调 LLM

    def test_numeric_fast_path_no_llm(self) -> None:
        """doc 77 §4.4：数值冲突直接 contradicted，不经 LLM。"""

        class _ExplodeLLM(_ScriptedLLM):
            def complete(self, *args: object, **kwargs: object) -> str:
                raise AssertionError("数值快路径不应调用 LLM")

        v = NLIVerifier(_ExplodeLLM(), retriever=_FakeRetriever([_chunk("免费档有次数限制")]))
        verdict = v.verify_claim(
            Claim(text="Pro 每月 20 美元", numeric={"monthly_price_usd": 20}), "cursor"
        )
        assert verdict.verdict == "contradicted"
        assert "数值" in verdict.reason


class TestRefetchMode:
    def _verifier(
        self,
        llm: _ScriptedLLM,
        snap_text: str = "Cursor Pro 每月 20 美元",
        fresh_text: str = "",
        policy: FetchPolicy | None = None,
        **kwargs: object,
    ) -> NLIVerifier:
        urls = {"https://example.com/pricing": fresh_text}

        def web_extract(url: str) -> str:
            return urls.get(url, "")

        return NLIVerifier(
            llm,
            retriever=_FakeRetriever([_chunk(snap_text)]),
            web_extract=web_extract,
            fetch_policy=policy or FetchPolicy(max_per_run=5),
            **kwargs,
        )

    def test_superseded_when_reality_changed(self) -> None:
        """快照支持、新原文矛盾 → superseded（现实已变，非幻觉）。"""
        llm = _ScriptedLLM(mapping={"每月 20 美元": "supported", "每月 30 美元": "contradicted"})
        v = self._verifier(llm, fresh_text="Cursor Pro 调价为每月 30 美元")
        verdict = v.verify_claim(
            Claim(text="Cursor Pro 定价 $20/月", dimension="pricing", source_urls=["https://example.com/pricing"]),
            "cursor",
            mode="refetch",
        )
        assert verdict.verdict == "superseded"

    def test_contradicted_when_snapshot_contradicts(self) -> None:
        """与快照就矛盾 → 真幻觉（与新原文无关）。"""
        llm = _ScriptedLLM(mapping={"每月 20 美元": "contradicted"})
        v = self._verifier(llm, fresh_text="任何新原文")
        verdict = v.verify_claim(
            Claim(text="Cursor 完全免费", source_urls=["https://example.com/pricing"]),
            "cursor",
            mode="refetch",
        )
        assert verdict.verdict == "contradicted"

    def test_numeric_superseded_no_llm(self) -> None:
        """数值：快照含 20、新原文只有 30 → superseded（数值三态快路径，不过 LLM）。"""

        class _ExplodeLLM(_ScriptedLLM):
            def complete(self, *args: object, **kwargs: object) -> str:
                raise AssertionError("数值三态快路径不应调用 LLM")

        v = self._verifier(_ExplodeLLM(), fresh_text="Cursor Pro 调价至 30 美元/月")
        verdict = v.verify_claim(
            Claim(
                text="Pro 定价 $20/月",
                dimension="pricing",
                source_urls=["https://example.com/pricing"],
                numeric={"monthly_price_usd": 20},
            ),
            "cursor",
            mode="refetch",
        )
        assert verdict.verdict == "superseded"

    def test_fetch_failed_falls_back_to_snapshot(self) -> None:
        llm = _ScriptedLLM(default="supported")
        v = self._verifier(llm, fresh_text="")  # 重抓失败
        verdict = v.verify_claim(
            Claim(text="Cursor Pro 定价 $20/月", source_urls=["https://example.com/pricing"]),
            "cursor",
            mode="refetch",
        )
        assert verdict.verdict == "supported"  # 回退快照判定

    def test_fetch_policy_limit_blocks(self) -> None:
        """doc 77 §4.5：refetch 走 FetchPolicy——超上限 URL 被拦截。"""
        llm = _ScriptedLLM(default="supported")
        policy = FetchPolicy(max_per_run=1)
        v = self._verifier(llm, fresh_text="最新原文", policy=policy)
        claim_a = Claim(text="断言甲" * 5, source_urls=["https://example.com/pricing"])
        claim_b = Claim(text="断言乙" * 5, source_urls=["https://example.com/other"])
        v.verify_claim(claim_a, "cursor", mode="refetch")
        verdict_b = v.verify_claim(claim_b, "cursor", mode="refetch")
        # 第二条 URL 超上限 → 无原文 → unverifiable（回退快照路径也拿不到新原文）
        assert verdict_b.verdict in ("supported", "unverifiable")
        assert policy.count == 1

    def test_fetch_policy_dedup_no_refetch(self) -> None:
        """doc 77 §4.5：同 URL 去重——本轮不重抓。"""
        calls: list[str] = []
        llm = _ScriptedLLM(default="supported")

        def web_extract(url: str) -> str:
            calls.append(url)
            return "最新原文内容"

        v = NLIVerifier(
            llm,
            retriever=_FakeRetriever([_chunk("快照原文内容")]),
            web_extract=web_extract,
            fetch_policy=FetchPolicy(max_per_run=5),
        )
        claim = Claim(text="同源断言重复校验一", source_urls=["https://example.com/pricing"])
        v.verify_claim(claim, "cursor", mode="refetch")
        v.verify_claim(claim, "cursor", mode="refetch")
        assert calls == ["https://example.com/pricing"]


class TestSupersededWiring:
    """doc 77 §4.2：superseded → TimelineMemory 事件 + alert sink 推送 + 知识库回灌。"""

    def _verifier(self, fresh_text: str) -> tuple[NLIVerifier, _FakeTimeline, _FakeAlertSink, _FakeIngester]:
        llm = _ScriptedLLM(mapping={"每月 20 美元": "supported", "每月 30 美元": "contradicted"})

        def complete(messages: list[dict[str, str]], json_mode: bool = False, **kwargs: object) -> str:
            content = str(messages[-1].get("content", ""))
            if "原子事实断言" in content:
                # 抽取带 dimension=pricing 的断言 → superseded 事件映射 price_change
                return json.dumps(
                    [{"text": "Cursor Pro 定价 $20/月", "dimension": "pricing",
                      "evidence_urls": ["https://example.com/pricing"], "numeric": {}}],
                    ensure_ascii=False,
                )
            if "NLI" in content:
                if "每月 20 美元" in content:
                    return '{"result": "supported", "reason": "快照支持"}'
                if "每月 30 美元" in content:
                    return '{"result": "contradicted", "reason": "新原文矛盾"}'
            return "not-json"

        llm.complete = complete  # type: ignore[method-assign]
        timeline = _FakeTimeline()
        sink = _FakeAlertSink()
        ingester = _FakeIngester()
        urls = {"https://example.com/pricing": fresh_text}

        def web_extract(url: str) -> str:
            return urls.get(url, "")

        v = NLIVerifier(
            llm,
            retriever=_FakeRetriever([_chunk("Cursor Pro 每月 20 美元")]),
            web_extract=web_extract,
            fetch_policy=FetchPolicy(max_per_run=5),
            timeline=timeline,
            alert_sink=sink,
            ingester=ingester,
        )
        return v, timeline, sink, ingester

    def test_event_alert_and_ingest(self) -> None:
        v, timeline, sink, ingester = self._verifier("Cursor Pro 调价为每月 30 美元")
        result = v.verify_report(
            "Cursor Pro 定价 $20/月。", "cursor", mode="refetch"
        )
        assert result.n_superseded >= 1
        assert len(timeline.events) >= 1
        assert timeline.events[0].competitor == "cursor"
        assert timeline.events[0].event_type == "price_change"  # pricing 维度映射
        assert len(sink.alerts) >= 1
        assert sink.alerts[0].competitor == "cursor"
        assert ingester.ingested and ingester.ingested[0][0] == "cursor"
        assert result.superseded_events and result.superseded_events[0]["event_type"] == "price_change"

    def test_no_side_effects_without_sink(self) -> None:
        """timeline/alert/ingester 缺省 None → 校验零副作用（评测侧确定性）。"""
        v, _timeline, _sink, ingester = self._verifier("Cursor Pro 调价为每月 30 美元")
        bare = NLIVerifier(
            v._llm,
            retriever=v._retriever,
            web_extract=v._web_extract,
            fetch_policy=FetchPolicy(max_per_run=5),
        )
        result = bare.verify_report("Cursor Pro 定价 $20/月。", "cursor", mode="refetch")
        assert result.n_superseded >= 1
        assert not ingester.ingested


class TestClaimExtraction:
    def test_llm_extraction_parsed(self) -> None:
        llm = _ScriptedLLM()

        def complete(messages, json_mode=False, **kwargs):
            content = str(messages[-1].get("content", ""))
            if "原子事实断言" in content:
                return json.dumps(
                    [
                        {"text": "Cursor 提供免费档", "dimension": "pricing",
                         "evidence_urls": ["https://x.com/a"], "numeric": {"monthly_price_usd": 0}},
                        {"text": "非法维度断言内容足够长", "dimension": "bad_dim", "numeric": {}},
                        {"text": "短", "dimension": "", "numeric": {}},
                        {"text": "数值断言价格二十", "dimension": "pricing", "numeric": {"score": 7.5}},
                    ],
                    ensure_ascii=False,
                )
            raise AssertionError("非抽取调用")

        llm.complete = complete  # type: ignore[method-assign]
        v = NLIVerifier(llm, retriever=None)
        claims = v.extract_claims("# 报告\n正文")
        assert len(claims) == 3  # 短文本被过滤
        assert claims[0].dimension == "pricing"
        assert claims[0].source_urls == ["https://x.com/a"]
        assert claims[0].numeric == {}  # 0 值被过滤（对齐 verification 非 0 纪律）
        assert claims[1].dimension == ""  # 非法维度归空
        assert claims[2].numeric == {"score": 7.5}

    def test_fallback_extraction_deterministic(self) -> None:
        text = "## 定价\n- Cursor Pro 定价 $20 每月，含 500 次补全。\n\n## 功能\n支持终端运行。"
        claims1 = NLIVerifier(None, retriever=None).extract_claims(text)
        claims2 = NLIVerifier(None, retriever=None).extract_claims(text)
        assert [c.text for c in claims1] == [c.text for c in claims2]
        assert any("20" in c.text for c in claims1)
        assert all(len(c.text) >= 8 for c in claims1)

    def test_max_claims_cap(self) -> None:
        llm = _ScriptedLLM()

        def complete(messages, json_mode=False, **kwargs):
            content = str(messages[-1].get("content", ""))
            if "原子事实断言" in content:
                return json.dumps(
                    [{"text": f"断言第 {i} 条内容足够长", "dimension": "", "numeric": {}} for i in range(50)],
                    ensure_ascii=False,
                )
            return "not-json"

        llm.complete = complete  # type: ignore[method-assign]
        v = NLIVerifier(llm, retriever=None, max_claims=5)
        assert len(v.extract_claims("正文")) == 5


class TestReportAggregate:
    def test_hallucination_rate_excludes_superseded_and_unverifiable(self) -> None:
        llm = _ScriptedLLM(mapping={"快照原文": "supported"})
        v = NLIVerifier(
            llm,
            retriever=_FakeRetriever([_chunk("快照原文内容一"), _chunk("快照原文内容二")]),
            web_extract=lambda url: "最新原文内容二",
            fetch_policy=FetchPolicy(max_per_run=5),
        )
        claims = [
            Claim(text="断言甲被来源支持内容一"),
            Claim(text="断言乙与来源矛盾内容二", source_urls=["https://example.com/pricing"]),
            Claim(text="断言丙无来源可查的内容"),
        ]
        result = v.verify_report("正文", "cursor", mode="refetch")
        _ = claims  # 用 verify_report 的 fallback 抽取路径（正文含数字/谓词句）
        assert isinstance(result, ReportVerification)
        # 幻觉率 = contradicted / (supported + contradicted)，superseded/unverifiable 不进分母
        judged = result.n_supported + result.n_contradicted
        if judged:
            assert result.hallucination_rate == round(result.n_contradicted / judged, 4)
        else:
            assert result.hallucination_rate == 0.0

    def test_empty_report_zero_rate(self) -> None:
        v = NLIVerifier(None, retriever=None)
        result = v.verify_report("", "cursor")
        assert result.hallucination_rate == 0.0
        assert result.total == 0


class TestVerifierConfig:
    def test_defaults(self) -> None:
        cfg = VerifierConfig()
        assert cfg.enabled is False
        assert cfg.mode == "snapshot"
        assert cfg.max_claims_per_report == 40
        assert cfg.auto_ingest_superseded is True

    def test_yaml_section_parsed(self, tmp_path: Path) -> None:
        yaml_text = (
            "verifier:\n"
            "  enabled: true\n"
            '  mode: "refetch"\n'
            "  max_claims_per_report: 10\n"
            "  auto_ingest_superseded: false\n"
        )
        path = tmp_path / "cfg.yaml"
        path.write_text(yaml_text, encoding="utf-8")
        from competitor_agent.config.loader import load_config

        cfg = load_config(path)
        assert cfg.verifier == VerifierConfig(
            enabled=True, mode="refetch", max_claims_per_report=10, auto_ingest_superseded=False
        )


class TestApprovalEnforcement:
    """doc 77 §2.3 产品挂点：contradicted → rejected；仅 superseded → note 提示。"""

    @pytest.fixture()
    def api(self, tmp_path: Path):
        from competitor_agent.config.loader import AppConfig
        from competitor_agent.facade.api import CompetitorAnalysisAPI

        cfg = AppConfig()
        cfg.report.output_dir = str(tmp_path)
        api = CompetitorAnalysisAPI(llm=None, use_llm=False, config=cfg, enable_rag=False)
        return api, tmp_path

    def _write_report(self, tmp_path: Path) -> None:
        md = tmp_path / "cursor.md"
        md.write_text("# Cursor 报告\n正文", encoding="utf-8")
        data = {"status": "approved", "markdown_report": "# Cursor 报告\n正文"}
        (tmp_path / "cursor.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    def test_contradicted_rejects(self, api, tmp_path: Path) -> None:
        from competitor_agent.core.approval_gate import report_status
        from competitor_agent.core.verifier import ReportVerification, Verdict

        a, _ = api
        self._write_report(tmp_path)
        claim = Claim(text="矛盾断言内容一")
        verification = ReportVerification(
            hallucination_rate=1.0,
            verdicts=[Verdict(claim=claim, verdict="contradicted", reason="与来源矛盾")],
        )
        a._apply_verification_to_approval("cursor", verification)
        assert report_status(tmp_path / "cursor.json") == "rejected"

    def test_superseded_only_keeps_status_with_note(self, api, tmp_path: Path) -> None:
        from competitor_agent.core.approval_gate import report_status
        from competitor_agent.core.verifier import ReportVerification, Verdict

        a, _ = api
        self._write_report(tmp_path)
        claim = Claim(text="过期断言内容一")
        verification = ReportVerification(
            hallucination_rate=0.0,
            verdicts=[Verdict(claim=claim, verdict="superseded")],
            superseded_events=[{"event_type": "price_change"}],
        )
        a._apply_verification_to_approval("cursor", verification)
        assert report_status(tmp_path / "cursor.json") == "approved"
        note = json.loads((tmp_path / "cursor.json").read_text(encoding="utf-8")).get("reviewer_note", "")
        assert "过期" in note

    def test_verify_report_uses_latest_archive(self, api, tmp_path: Path) -> None:
        a, _ = api
        self._write_report(tmp_path)
        text = a._latest_report_text("cursor")
        assert "Cursor 报告" in text


class TestBenchmarkVerificationWiring:
    """doc 77 §4.3：mock 模式 NLI 校验连跑确定性 + BenchmarkReport.verification 挂载。"""

    def _fixtures(self, tmp_path: Path) -> Path:
        fixtures = tmp_path / "fixtures"
        fixtures.mkdir()
        page = "Cursor Pro 定价每月 20 美元，含 500 次高级补全。支持终端与 MCP。"
        cases = [
            {
                "task": "只分析 cursor 的定价",
                "competitor": "cursor",
                "dimension": "pricing",
                "ground_truth": {"plans": [{"name": "Pro", "monthly_price_usd": 20}]},
                "case_id": "veri_cursor_pricing_77",
                "tags": ["normal"],
                "mode": "single",
                "page": page,
            }
        ]
        (fixtures / "accuracy_cases.json").write_text(
            json.dumps(cases, ensure_ascii=False), encoding="utf-8"
        )
        return fixtures

    def test_mock_deterministic_two_runs(self, tmp_path: Path) -> None:
        from competitor_agent.evaluation.benchmark import Benchmark

        fixtures = self._fixtures(tmp_path)

        def one_run() -> dict:
            report = Benchmark(
                llm_mode="mock",
                fixtures_dir=fixtures,
                golden_dir=tmp_path / "no_golden",
                use_golden_cache=False,
            ).run()
            return report.verification.to_dict()

        run1, run2 = one_run(), one_run()
        assert run1 == run2
        assert run1["n_verified_cases"] == 1
        assert run1["n_claims"] >= 1
        assert 0.0 <= run1["hallucination_rate"] <= 1.0

    def test_real_mode_verification_off_by_default(self, tmp_path: Path) -> None:
        from competitor_agent.evaluation.benchmark import Benchmark, BenchmarkMockLLM
        from competitor_agent.llm.client import LLMClient

        fixtures = self._fixtures(tmp_path)
        mock = BenchmarkMockLLM(competitor="cursor", dimension="pricing")
        report = Benchmark(
            llm_mode="real", llm=LLMClient(call_func=mock.complete), fixtures_dir=fixtures,
            golden_dir=tmp_path / "no_golden", use_golden_cache=False,
        ).run()
        assert report.verification.n_claims == 0  # real 默认关（成本护栏）
