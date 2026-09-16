"""pytest 配置 - 确保 competitor_agent 作为顶级包可导入

并共享集成/端到端测试基础设施（11_integration_test_design.md §3.3）：
- fake_extractor：固定网页内容的可控采集器（不依赖真实网络）
- mock_llm：确定性 mock LLM（复用 benchmark 的 BenchmarkMockLLM，CI 无 Key 可复现）
- memory：临时数据目录的四层记忆（tmp_path 隔离，测试后自动清理）
"""

from __future__ import annotations

import sys
from collections.abc import Iterator
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
def _isolate_llm_env() -> None:
    """确保单测不触发真实 LLM/搜索调用：清除 API Key 与搜索增强 Key 环境变量"""
    import os

    for key in ("OPENAI_API_KEY", "DEEPSEEK_API_KEY", "LLM_API_KEY", "TAVILY_API_KEY"):
        os.environ.pop(key, None)


@pytest.fixture(autouse=True, scope="session")
def _disable_real_search(tmp_path_factory: pytest.TempPathFactory) -> Iterator[None]:
    """禁用测试内真实联网搜索（doc 89 断网隔离纪律延伸）。

    doc 71 后 DDG 为免 Key 恒可用主力：无显式 web_tool 时装配层自动注入
    ``build_search_router``——mock LLM 的 discovery 编排（web_search_candidates）
    会发出真实 HTTP 请求，断网/死代理环境表现为超时假死而非快速降级。
    会话级用 ``COMPETITOR_AGENT_CONFIG`` 指向 ``enable_external_sources: false``
    的最小配置，使搜索注入确定关闭；显式注入 web_tool 的用例不受影响
    （显式优先于自动注入，doc 61 契约）。
    """
    import os

    cfg_file = tmp_path_factory.mktemp("config") / "test_config.yaml"
    cfg_file.write_text("collector:\n  enable_external_sources: false\n", encoding="utf-8")
    os.environ["COMPETITOR_AGENT_CONFIG"] = str(cfg_file)
    yield
    os.environ.pop("COMPETITOR_AGENT_CONFIG", None)


@pytest.fixture(autouse=True, scope="session")
def _offline_huggingface() -> Iterator[None]:
    """嵌入/精排层权重探测禁止触网（doc 89 断网隔离纪律的延伸）。

    HF 本地缓存不全时 sentence_transformers 会对缺失文件在线补拉（HEAD + 5 次重试），
    无网/死代理环境表现为分钟级假死而非快速降级。离线模式语义：
    缓存完整 → 正常加载；缓存缺失 → 立即抛错 → ``is_available()=False`` 确定性降级
    （与无权重机器逐位一致，回归安全阀不变）。
    """
    import os

    set_keys = []
    for key in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE", "HF_HUB_DISABLE_TELEMETRY"):
        if key not in os.environ:
            os.environ[key] = "1"
            set_keys.append(key)
    yield
    for key in set_keys:
        os.environ.pop(key, None)


@pytest.fixture(autouse=True, scope="session")
def _isolate_user_data_dir(tmp_path_factory: pytest.TempPathFactory) -> Iterator[None]:
    """单测不触碰真实用户数据目录（``~/.competitor_agent``）。

    会话级把 ``COMPETITOR_AGENT_DATA_DIR`` 指向临时目录：知识库/记忆/缓存全部隔离。
    动机：真实 KB 已增长到万级 chunk，无持久化 chroma 时 API 构建期会全量 CPU 重嵌
    （分钟级假死）；且真实数据损坏会误伤无关用例。与 doc 89 断网隔离同思路——
    个别需覆盖默认路径解析的用例自行 delenv/setenv（显式管理优先于本隔离）。
    """
    import os

    os.environ["COMPETITOR_AGENT_DATA_DIR"] = str(tmp_path_factory.mktemp("user_data"))
    yield
    os.environ.pop("COMPETITOR_AGENT_DATA_DIR", None)


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
