"""L1 记忆召回向量化测试（52_rag_depth_design.md §3.2 / M1）

- 注入可用向量层：recent_context 走向量语义召回（词面不重叠的语义相关条目被召回）
- 向量不可用（无模型缓存且未注入 embed_fn）/ 向量层抛异常 → 回退词袋，结果与不注入逐位一致
- 重复 archive 幂等：同 session_id 覆盖，向量条数不增
- TTL 老化：_age_out 剔除的条目同步从向量集合删除
- 竞品隔离：chromadb metadata where 过滤，跨竞品条目不串扰
"""
from __future__ import annotations

import pytest
from competitor_agent.interfaces.context import AnalysisSession
from competitor_agent.knowledge_base.vector_store import VectorStore
from competitor_agent.memory.four_layer_memory import FourLayerMemory
from competitor_agent.memory.session_archive import SessionArchive

# chromadb 依赖：本环境已装；若 CI 环境缺失则整体 skip（与 test_vector_retrieval 同约定）
try:  # pragma: no cover
    import chromadb  # noqa: F401

    _HAS_CHROMADB = True
except Exception:  # noqa: BLE001 - chromadb 缺失则整体跳过 # pragma: no cover
    _HAS_CHROMADB = False

pytestmark = pytest.mark.skipif(not _HAS_CHROMADB, reason="chromadb 未安装，向量层不可用")


class _PricingEmbedder:
    """确定性 mock 嵌入：含「定价」语义的文本映射到 [1,0]，否则 [0,1]。

    「收费模式」与「定价」词面不重叠（词袋召回不到）、向量空间同向（语义召回），
    复现设计文档 52 §1.2 的语义盲场景。
    """

    def __call__(self, texts: list[str]) -> list[list[float]]:
        out = []
        for t in texts:
            if "pricing_sem" in t:
                out.append([1.0, 0.0])
            else:
                out.append([0.0, 1.0])
        return out


def _vector_store(tmp_path, embed_fn=None) -> VectorStore:
    return VectorStore(
        collection_name="test_session_summaries",
        embed_fn=embed_fn if embed_fn is not None else _PricingEmbedder(),
        data_dir=tmp_path / "vs",
    )


def _session(
    session_id: str,
    created_at: str,
    summary: str,
    competitor: str = "cursor",
    confidence: float = 0.9,
) -> AnalysisSession:
    return AnalysisSession(
        task=f"分析 {competitor}",
        competitor_name=competitor,
        session_id=session_id,
        created_at=created_at,
        raw={
            "dimensions": [
                {"dimension": "pricing", "summary": summary, "confidence": confidence}
            ]
        },
    )


# 旧会话（pricing_sem 标记 → 向量 [1,0]），新会话（无标记 → [0,1]）
_OLD = _session("s_old", "2026-08-01T00:00:00Z", "pricing_sem 收费模式：订阅制分层")
_NEW = _session("s_new", "2026-08-10T00:00:00Z", "社区口碑与生态插件丰富")


class TestVectorRecall:
    def test_vector_recall_semantic_hit(self, tmp_path):
        """语义相关但词面不重叠的旧条目被向量召回顶到首位（词袋做不到）。"""
        archive = SessionArchive(tmp_path, vector_store=_vector_store(tmp_path))
        archive.archive(_OLD)
        archive.archive(_NEW)
        # 条目视图按时间倒序：[新, 旧]；query 含 pricing_sem → 向量 [1,0] 命中旧条目
        ctx = archive.recent_context("cursor", top_k=2, query="pricing_sem 收费模式调研")
        assert len(ctx) == 2
        assert "收费模式：订阅制分层" in ctx[0]
        assert "社区口碑与生态插件丰富" in ctx[1]

    def test_vector_recall_without_query_unchanged(self, tmp_path):
        """query 为空时不走向量（取最近 top_k），与现状一致。"""
        archive = SessionArchive(tmp_path, vector_store=_vector_store(tmp_path))
        archive.archive(_OLD)
        archive.archive(_NEW)
        ctx = archive.recent_context("cursor", top_k=2)
        assert "社区口碑与生态插件丰富" in ctx[0]

    def test_competitor_isolation(self, tmp_path):
        """向量集合按竞品 metadata 过滤：同集合内其他竞品条目不串扰。"""
        vs = _vector_store(tmp_path)
        archive = SessionArchive(tmp_path, vector_store=vs)
        archive.archive(_OLD)
        archive.archive(_session("s_w", "2026-08-05T00:00:00Z", "pricing_sem windsurf 收费", competitor="windsurf"))
        ctx = archive.recent_context("cursor", top_k=5, query="pricing_sem 收费")
        assert any("订阅制分层" in line for line in ctx)
        assert not any("windsurf" in line for line in ctx)

    def test_unsynced_entries_appended_in_order(self, tmp_path):
        """向量集合未覆盖的条目（构造前已归档的老摘要）按原序追加兜底，条数不缩水。"""
        archive = SessionArchive(tmp_path)
        archive.archive(_OLD)
        archive.archive(_NEW)
        # 构造后才注入向量层：集合为空 → search 无命中 → 回退词袋
        vs = _vector_store(tmp_path)
        archive.attach_vector_store(vs)
        ctx_fallback = archive.recent_context("cursor", top_k=2, query="pricing_sem")
        assert len(ctx_fallback) == 2
        # 触发一次 rebuild 同步向量后：旧条目惰性 upsert，向量召回生效
        archive.compress()
        ctx = archive.recent_context("cursor", top_k=2, query="pricing_sem 收费")
        assert "收费模式：订阅制分层" in ctx[0]


class TestFallbackIdentical:
    def test_unavailable_falls_back_lexical(self, tmp_path):
        """embed_fn=None 且无模型缓存 → is_available()=False → 词袋结果与无注入逐位一致。"""
        sessions = [_OLD, _NEW]
        plain = SessionArchive(tmp_path / "plain")
        degraded = SessionArchive(
            tmp_path / "degraded",
            vector_store=VectorStore(
                collection_name="test_session_summaries",
                # 未缓存的模型名：_semantic_embedder_cached 探测不触网 → 确定性不可用
                model_name="BAAI/not-cached-model-for-test",
                embed_fn=None,
                data_dir=tmp_path / "vs_none",
            ),
        )
        for s in sessions:
            plain.archive(s)
            degraded.archive(s)
        query = "pricing_sem 收费模式"
        assert degraded.recent_context("cursor", top_k=2, query=query) == plain.recent_context(
            "cursor", top_k=2, query=query
        )

    def test_exception_falls_back_lexical(self, tmp_path):
        """向量层抛异常 → 回退词袋，结果与无注入逐位一致。"""

        class _BrokenStore:
            def is_available(self) -> bool:
                return True

            def embed(self, texts):
                raise RuntimeError("embed boom")

            def search(self, *a, **kw):
                raise RuntimeError("search boom")

            def get_existing(self, ids):
                raise RuntimeError("sync boom")

            def upsert(self, *a, **kw):
                raise RuntimeError("sync boom")

            def list_ids(self, where=None):
                raise RuntimeError("sync boom")

            def delete(self, ids):
                raise RuntimeError("sync boom")

        plain = SessionArchive(tmp_path / "plain")
        broken = SessionArchive(tmp_path / "broken", vector_store=_BrokenStore())
        for s in (_OLD, _NEW):
            plain.archive(s)  # 同步异常不应阻断归档
            broken.archive(s)
        query = "收费模式"
        assert broken.recent_context("cursor", top_k=2, query=query) == plain.recent_context(
            "cursor", top_k=2, query=query
        )


class TestVectorSync:
    def test_rearchive_idempotent(self, tmp_path):
        """同 session_id 重复归档：条目覆盖不增，向量条数不增。"""
        vs = _vector_store(tmp_path)
        archive = SessionArchive(tmp_path, vector_store=vs)
        archive.archive(_OLD)
        archive.archive(_OLD)
        entries = archive.recent_context("cursor", top_k=10)
        assert len(entries) == 1
        assert vs.count() == 1

    def test_ttl_aging_removes_vectors(self, tmp_path):
        """TTL 老化：超龄会话归档时即被 _age_out 剔除，不进入向量集合也不被召回。"""
        vs = _vector_store(tmp_path)
        archive = SessionArchive(tmp_path, ttl_days=30, vector_store=vs)
        expired = _session("s_expired", "2026-01-01T00:00:00Z", "pricing_sem 过期会话结论")
        archive.archive(expired)  # 距今 > 30 天：_rebuild_context 的 _age_out 直接剔除
        assert "cursor:s_expired" not in vs.list_ids(where={"competitor": "cursor"})
        archive.archive(_NEW)
        ids = vs.list_ids(where={"competitor": "cursor"})
        assert ids == {"cursor:s_new"}
        ctx = archive.recent_context("cursor", top_k=5, query="pricing_sem 过期")
        assert not any("过期会话结论" in line for line in ctx)

    def test_compress_truncation_removes_vectors(self, tmp_path):
        """压缩截断剔除的条目同步从向量集合删除（stale delete 路径）。"""
        vs = _vector_store(tmp_path)
        archive = SessionArchive(tmp_path, vector_store=vs)
        archive.archive(_OLD)
        archive.archive(_NEW)
        assert vs.count() == 2
        archive.compress(max_entries=1, keep_full=1)  # 只留最新一条 → 旧条目向量剔除
        assert vs.list_ids(where={"competitor": "cursor"}) == {"cursor:s_new"}


class TestFourLayerMemoryWiring:
    def test_passthrough_and_attach(self, tmp_path):
        """FourLayerMemory 透传 vector_store + attach_vector_store 构造后注入均生效。"""
        vs = _vector_store(tmp_path)
        memory = FourLayerMemory(tmp_path / "m1", vector_store=vs)
        memory.archive_session(_OLD)
        memory.archive_session(_NEW)
        ctx = memory.recent_context("cursor", top_k=2, query="pricing_sem 收费")
        assert "收费模式：订阅制分层" in ctx[0]

        memory2 = FourLayerMemory(tmp_path / "m2")
        memory2.attach_vector_store(_vector_store(tmp_path / "m2"))
        memory2.archive_session(_OLD)
        memory2.archive_session(_NEW)
        ctx2 = memory2.recent_context("cursor", top_k=2, query="pricing_sem 收费")
        assert "收费模式：订阅制分层" in ctx2[0]

    def test_data_dir_property(self, tmp_path):
        """data_dir 属性暴露构造根目录（facade 注入同根向量层用）；None → get_data_dir()。"""
        memory = FourLayerMemory(tmp_path / "m")
        assert memory.data_dir == tmp_path / "m"

    def test_no_injection_unchanged(self, tmp_path):
        """不注入向量层：归档/召回与现状一致（词袋路径回归网）。"""
        memory = FourLayerMemory(tmp_path / "m")
        memory.archive_session(_OLD)
        memory.archive_session(_NEW)
        ctx = memory.recent_context("cursor", top_k=2, query="收费模式")
        assert len(ctx) == 2
