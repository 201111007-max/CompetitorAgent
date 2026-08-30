"""设计文档 56 M1②：Lead 摄入补齐（_lead_web_extract）

- 抓取成功后 _ingest_fetched 被调：plan 前（competitor 空串）摄入 dimension="web" 通用域；
  plan 后（competitor 回填）摄入竞品域
- 守卫拦截/抓取失败/空文本占位不摄入（沿用 _ingest_fetched 既有纪律）
- Lead dispatcher 的 web_extract 即摄入闭包（_react_loop 接线）
"""
from __future__ import annotations

from competitor_agent.config.loader import load_config
from competitor_agent.facade.api import CompetitorAnalysisAPI
from competitor_agent.knowledge_base.competitor_store import CompetitorStore


def _api(tmp_path) -> CompetitorAnalysisAPI:
    return CompetitorAnalysisAPI(
        llm=None,
        use_llm=False,
        enable_memory=False,
        rag_store=CompetitorStore(data_dir=tmp_path / "kb"),
        config=load_config(),
    )


class TestLeadWebExtractIngest:
    def test_ingest_before_plan_to_generic_web_dimension(self, tmp_path, monkeypatch):
        """plan 落地前：competitor 空串 + dimension="web" 通用域摄入。"""
        api = _api(tmp_path)
        calls: list[tuple] = []
        monkeypatch.setattr(api, "_react_web_extract", lambda url: "cursor pro $20 页面正文")
        monkeypatch.setattr(api, "_ingest_fetched", lambda *a: calls.append(a))
        extract = api._lead_web_extract(lambda: "")
        assert extract("https://cursor.com/pricing") == "cursor pro $20 页面正文"
        assert calls == [("", "web", "https://cursor.com/pricing", "cursor pro $20 页面正文")]

    def test_ingest_after_plan_bound_to_competitor(self, tmp_path, monkeypatch):
        """plan 落地后：competitor 懒绑定回填，摄入竞品域。"""
        api = _api(tmp_path)
        calls: list[tuple] = []
        monkeypatch.setattr(api, "_react_web_extract", lambda url: "正文")
        monkeypatch.setattr(api, "_ingest_fetched", lambda *a: calls.append(a))
        box = {"competitor": ""}
        extract = api._lead_web_extract(lambda: box["competitor"])
        extract("https://a.com/1")
        box["competitor"] = "cursor"  # 模拟 make_plan 落地回填
        extract("https://a.com/2")
        assert calls[0][0] == "" and calls[1][0] == "cursor"
        assert all(c[1] == "web" for c in calls)

    def test_placeholder_text_not_ingested(self, tmp_path, monkeypatch):
        """守卫拦截/抓取失败/空文本的占位文本不摄入（真实 ingester + 临时库验证）。"""
        api = _api(tmp_path)
        for placeholder in (
            "URL 被安全守卫拦截: 私网地址",
            "抓取失败: 连接超时",
            "（页面无文本内容）",
            "",
        ):
            monkeypatch.setattr(api, "_react_web_extract", lambda url, t=placeholder: t)
            api._lead_web_extract(lambda: "")("https://example.com")
        assert api._store.by_competitor("") == [], "占位文本不应落入知识库"

    def test_limit_placeholder_not_ingested(self, tmp_path, monkeypatch):
        """review 修复（P1，doc 71 §5.3）：单跑上限提示文本不摄入知识库（防 RAG 污染）。"""
        api = _api(tmp_path)
        monkeypatch.setattr(api, "_react_web_extract", lambda url: "正文")
        api._ingest_fetched("", "web", "https://example.com", "抓取次数已达上限（本任务 6 次）")
        assert api._store.by_competitor("") == [], "上限提示不应落入知识库"

    def test_real_ingest_lands_in_store(self, tmp_path, monkeypatch):
        """真实摄入闭环：抓取正文经 _ingest_fetched 落入知识库，可被检索。"""
        api = _api(tmp_path)
        monkeypatch.setattr(
            api, "_react_web_extract", lambda url: "cursor pro plan costs $20 per month"
        )
        api._lead_web_extract(lambda: "cursor")("https://cursor.com/pricing")
        chunks = api._store.by_competitor("cursor")
        assert chunks and chunks[0].dimension == "web"
        assert "costs $20" in chunks[0].text

    def test_react_loop_web_extract_is_ingesting_closure(self, tmp_path, monkeypatch):
        """_react_loop 接线：Lead dispatcher 的 web_extract 是摄入闭包（非裸 _react_web_extract）。"""
        api = _api(tmp_path)
        monkeypatch.setattr(api, "_react_web_extract", lambda url: "lead 页面正文 $20")
        loop = api._react_loop("分析 cursor 定价", None)
        dispatcher = loop._agent._dispatcher
        result = dispatcher._tools["web_extract"]("https://cursor.com/pricing")
        assert result == "lead 页面正文 $20"
        assert api._store.by_competitor(""), "plan 前摄入到空串通用域"
