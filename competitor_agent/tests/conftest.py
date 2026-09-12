"""pytest 配置 - 确保 competitor_agent 作为顶级包可导入

并共享集成/端到端测试基础设施（11_integration_test_design.md §3.3）：
- fake_extractor：固定网页内容的可控采集器（不依赖真实网络）
- mock_llm：确定性 mock LLM（复用 benchmark 的 BenchmarkMockLLM，CI 无 Key 可复现）
- memory：临时数据目录的四层记忆（tmp_path 隔离，测试后自动清理）
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from competitor_agent.domain_types.observation import Observation, SourceEvidence
from competitor_agent.evaluation.benchmark import BenchmarkMockLLM
from competitor_agent.interfaces.context import SourceContext
from competitor_agent.llm.client import LLMClient
from competitor_agent.memory import FourLayerMemory

_pkg_root = Path(__file__).parent.parent
if str(_pkg_root) not in sys.path:
    sys.path.insert(0, str(_pkg_root))

CURSOR_PRICING = "Pro $20/month\nTeams $40/month\nUltra $60/month"


class FakeExtractor:
    """固定网页内容采集器：按 URL 关键字返回定价/文档/通用文本，可复现、不依赖网络。"""

    source_name = "web_extractor"

    def fetch(self, gap: object, context: SourceContext) -> Observation:
        url = str(context.kwargs.get("url"))
        if str(getattr(gap, "field", "")) == "sentiment":
            text = (
                "Cursor is an AI code editor. Developers love the fast completions "
                "and call it great, recommend it, but some find it slow."
            )
        elif "pricing" in url:
            text = CURSOR_PRICING
        elif "docs" in url or "cursor.com" in url:
            text = "Cursor supports MCP integration, agent mode, and Codex-style reviews."
        else:
            text = "Cursor is an AI code editor."
        evidence = SourceEvidence(
            source_name=self.source_name,
            url=url,
            content_hash=str(hash(url)),
            trust_level=0.9,
        )
        return Observation(
            gap_field=str(getattr(gap, "field", "")),
            source=self.source_name,
            raw_text=text,
            evidence=evidence,
        )


@pytest.fixture
def fake_extractor() -> FakeExtractor:
    return FakeExtractor()


@pytest.fixture
def mock_llm() -> LLMClient:
    """确定性 mock LLM：按分析器 prompt 维度抽取规范化 JSON（无 Key、无网络）。"""
    return LLMClient(call_func=BenchmarkMockLLM().complete)


@pytest.fixture(autouse=True)
def _isolate_llm_env():
    """确保单测不触发真实 LLM 调用：清除 API Key 环境变量"""
    import os

    for key in ("OPENAI_API_KEY", "DEEPSEEK_API_KEY", "LLM_API_KEY"):
        os.environ.pop(key, None)


@pytest.fixture
def memory(tmp_path: Path) -> FourLayerMemory:
    return FourLayerMemory(tmp_path / "memory")


_network_available: bool | None = None


def _probe_network() -> bool:
    """轻量网络探测（设计文档 89 §2）：真实 DNS 解析 example.com，会话级缓存。

    当前 network 标记家族的共同依赖是 url_guard 的**直接 DNS 解析**
    （SSRF 防护，不经过 http 代理）——所以探针测 DNS 而非 HTTP：本机类
    代理环境 HTTP 经代理可用但 DNS 不直连，用例仍会失败，必须 skip。
    """
    global _network_available
    if _network_available is None:
        import socket

        try:
            socket.getaddrinfo("example.com", 443)
            _network_available = True
        except OSError:
            _network_available = False
    return _network_available


def pytest_runtest_setup(item: pytest.Item) -> None:
    if item.get_closest_marker("network") is not None and not _probe_network():
        pytest.skip("无网络环境（network 标记用例自动跳过）")
