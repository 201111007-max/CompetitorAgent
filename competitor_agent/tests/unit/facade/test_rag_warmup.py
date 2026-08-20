"""rag-warmup CLI + 启动状态日志单测（设计文档 52 §2.2 / M2）

- warmup_status 三态：已缓存 / 未缓存触发下载 / 下载失败
  （下载路径用假 sentence_transformers 模块注入 sys.modules，零网络）
- cli rag-warmup 子命令：状态输出 + 退出码（available=0 / degraded=1）
- api enable_rag 启动状态日志：available/degraded 各打一行，消除静默降级
"""
from __future__ import annotations

import logging
import sys
import types

from competitor_agent import cli
from competitor_agent.facade.api import CompetitorAnalysisAPI
from competitor_agent.knowledge_base import vector_store as vs_mod
from competitor_agent.knowledge_base.vector_store import VectorStore, warmup_status

try:  # pragma: no cover
    import chromadb  # noqa: F401

    _HAS_CHROMADB = True
except Exception:  # noqa: BLE001 - chromadb 缺失时跳过版本断言 # pragma: no cover
    _HAS_CHROMADB = False


def _fake_st_module(exc: Exception | None = None) -> tuple[types.ModuleType, list[str]]:
    """假 sentence_transformers 模块：记录构造入参；exc 非空时构造抛错。"""
    mod = types.ModuleType("sentence_transformers")
    calls: list[str] = []

    class _FakeST:
        def __init__(self, model_name: str) -> None:
            if exc is not None:
                raise exc
            calls.append(model_name)

    mod.SentenceTransformer = _FakeST  # type: ignore[attr-defined]
    return mod, calls


def _status(**overrides):
    base = {
        "model_name": "BAAI/bge-small-zh-v1.5",
        "available": False,
        "downloaded": False,
        "model_path": None,
        "chromadb_version": "1.5.9",
        "error": None,
    }
    base.update(overrides)
    return base


class TestWarmupStatus:
    def test_already_cached_no_download(self, monkeypatch):
        monkeypatch.setattr(vs_mod, "_semantic_embedder_cached", lambda name: True)
        monkeypatch.setattr(vs_mod, "_cached_weight_path", lambda name: "/cache/model.safetensors")
        status = warmup_status()
        assert status["available"] is True
        assert status["downloaded"] is False
        assert status["model_path"] == "/cache/model.safetensors"
        assert status["error"] is None
        if _HAS_CHROMADB:
            assert status["chromadb_version"]
        else:
            assert status["chromadb_version"] is None

    def test_downloads_when_missing(self, monkeypatch):
        """未缓存 → 触网下载（仅此显式路径）→ 复检缓存 → available。"""
        states = iter([False, True])  # 下载前探测 False，下载后复检 True
        monkeypatch.setattr(vs_mod, "_semantic_embedder_cached", lambda name: next(states))
        monkeypatch.setattr(vs_mod, "_cached_weight_path", lambda name: "/cache/model.safetensors")
        mod, calls = _fake_st_module()
        monkeypatch.setitem(sys.modules, "sentence_transformers", mod)
        status = warmup_status()
        assert calls == ["BAAI/bge-small-zh-v1.5"]
        assert status["downloaded"] is True
        assert status["available"] is True
        assert status["model_path"] == "/cache/model.safetensors"

    def test_download_failure_reported(self, monkeypatch):
        monkeypatch.setattr(vs_mod, "_semantic_embedder_cached", lambda name: False)
        mod, _ = _fake_st_module(exc=RuntimeError("net down"))
        monkeypatch.setitem(sys.modules, "sentence_transformers", mod)
        status = warmup_status()
        assert status["available"] is False
        assert status["downloaded"] is False
        assert "net down" in status["error"]


class TestRagWarmupCommand:
    def test_parser(self):
        assert cli.build_parser().parse_args(["rag-warmup"]).command == "rag-warmup"

    def _run_main(self, monkeypatch, status):
        monkeypatch.setattr(vs_mod, "warmup_status", lambda: status)
        monkeypatch.setattr(cli, "setup_logging", lambda **kw: None)
        monkeypatch.setattr(
            cli,
            "load_config",
            lambda: types.SimpleNamespace(
                observability=types.SimpleNamespace(log_level="WARNING")
            ),
        )
        return cli.main(["rag-warmup"])

    def test_available_exit_0(self, monkeypatch, capsys):
        code = self._run_main(monkeypatch, _status(available=True, model_path="/cache/m.safetensors"))
        out = capsys.readouterr().out
        assert code == 0
        assert "BAAI/bge-small-zh-v1.5" in out
        assert "模型缓存: /cache/m.safetensors" in out
        assert "向量层状态: available" in out

    def test_degraded_exit_1(self, monkeypatch, capsys):
        code = self._run_main(monkeypatch, _status(error="net down"))
        out = capsys.readouterr().out
        assert code == 1
        assert "向量层状态: degraded" in out
        assert "模型下载失败: net down" in out

    def test_no_api_construction(self, monkeypatch):
        """rag-warmup 不构造 API（无需 LLM Key），在 _make_api 之前短路。"""
        monkeypatch.setattr(vs_mod, "warmup_status", lambda: _status(available=True))
        monkeypatch.setattr(cli, "setup_logging", lambda **kw: None)
        monkeypatch.setattr(
            cli,
            "load_config",
            lambda: types.SimpleNamespace(
                observability=types.SimpleNamespace(log_level="WARNING")
            ),
        )

        def _boom(**kw):
            raise AssertionError("rag-warmup 不应构造 API")

        monkeypatch.setattr(cli, "_make_api", _boom)
        assert cli.main(["rag-warmup"]) == 0


class TestStartupStatusLog:
    """api __init__ enable_rag 时打一行向量层状态（设计文档 52 §2.2）。"""

    def _construct(self, vs, caplog):
        with caplog.at_level(logging.INFO, logger="competitor_agent.facade.api"):
            CompetitorAnalysisAPI(extractor=None, use_llm=False, enable_rag=True, vector_store=vs)

    def test_log_available(self, tmp_path, caplog):
        vs = VectorStore(embed_fn=lambda texts: [[0.0]] * len(texts), data_dir=tmp_path / "vs")
        self._construct(vs, caplog)
        messages = [r.getMessage() for r in caplog.records]
        assert any("向量层状态: available(BAAI/bge-small-zh-v1.5)" in m for m in messages)

    def test_log_degraded(self, tmp_path, caplog):
        vs = VectorStore(
            model_name="BAAI/not-cached-model-for-test", embed_fn=None, data_dir=tmp_path / "vs"
        )
        self._construct(vs, caplog)
        messages = [r.getMessage() for r in caplog.records]
        assert any(
            "向量层状态: degraded(模型 BAAI/not-cached-model-for-test 未缓存，降级词袋)" in m
            for m in messages
        )
