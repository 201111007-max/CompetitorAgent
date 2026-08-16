"""配置加载器 — 将 config/review_config.yaml 加载为类型安全的 AppConfig

支持环境变量 COMPETITOR_AGENT_CONFIG 覆盖配置文件路径。
配置值注入 CompetitorAnalysisAPI 及各组件（预算/终止/维度/采集/记忆/报告/可观测性）。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

_DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent / "review_config.yaml"
_CONFIG_ENV = "COMPETITOR_AGENT_CONFIG"


@dataclass
class BudgetConfig:
    max_iterations: int = 10
    max_parallel_subagents: int = 4
    cost_limit_usd: float = 1.0
    token_high_water_mark: int = 120000
    token_compression_target: int = 80000


@dataclass
class TerminationConfig:
    core_priority_threshold: int = 8
    core_confidence: float = 0.8


@dataclass
class ExecutionConfig:
    """执行调度配置（并行缺口分析）"""

    mode: str = "single"  # single 串行（默认，兼容）；parallel 并行执行独立缺口
    max_parallel_subagents: int = 4  # 并行子代理上限


@dataclass
class DimensionsConfig:
    enabled: list[str] = field(
        default_factory=lambda: ["feature", "pricing", "performance", "ecosystem", "sentiment", "roadmap"]
    )
    default_budget: dict[str, int] = field(default_factory=dict)
    analysis_order: list[str] = field(default_factory=list)


@dataclass
class CollectorConfig:
    cache_ttl_seconds: int = 86400
    max_retries: int = 2
    timeout_seconds: int = 20
    max_content_chars: int = 8000  # 统一内容大小上限（设计文档 41，替代 ReAct 2000 / web_tools 8000 硬编码）
    block_private_urls: bool = True  # URL 守卫（设计文档 41）：默认开启；False 用于本地调试
    rate_limit_per_second: int = 2
    use_playwright: bool = False
    user_agent: str = "competitor-agent/0.1"
    # 外部源多源路由（设计文档 23）：主开关默认关闭，保证无网络/无 Key 的测试与
    # benchmark 不触发真实网络；开启后按维度开关启用对应提供方。
    enable_external_sources: bool = False
    enable_github: bool = True
    enable_marketplace: bool = True
    enable_community: bool = True
    enable_benchmark: bool = True


@dataclass
class StopVerifierConfig:
    required_dimensions: list[str] = field(default_factory=lambda: ["pricing", "feature"])
    min_confidence: float = 0.6
    min_evidence_ratio: float = 0.7


@dataclass
class MemoryConfig:
    enabled: bool = True
    data_dir: str = "~/.competitor_agent"
    session_ttl_days: int = 30
    skills_max_per_competitor: int = 50
    evolution_window: int = 30


@dataclass
class ReportConfig:
    include_confidence: bool = True
    include_evidence_urls: bool = True
    output_dir: str = "reports/competitor"
    export_json: bool = True  # 结构化 JSON 导出开关（设计文档 28）
    comparison_dir: str = "reports/comparison"  # 比较报告矩阵 JSON 目录


@dataclass
class FreshnessConfig:
    """新鲜度/陈旧度配置（设计文档 26 §3.2）"""

    dimension_ttl_days: dict[str, int] = field(
        default_factory=lambda: {
            "pricing": 7,
            "performance": 14,
            "feature": 30,
            "ecosystem": 30,
            "sentiment": 7,
            "roadmap": 14,
        }
    )
    refresh_check_enabled: bool = True


@dataclass
class ObservabilityConfig:
    log_level: str = "INFO"


@dataclass
class LLMConfig:
    api_base_url: str = "https://api.openai.com/v1"
    model: str = "deepseek-v4-flash"
    temperature: float = 0.1
    max_tokens: int = 2048
    fallback_models: list[str] = field(default_factory=list)  # 主模型重试耗尽后的回退模型链（设计文档 36）
    timeout: float | None = None  # 单次调用超时（秒，连接+读）；None 用 SDK 默认
    max_retries: int = 3  # 每个模型的可重试错误最大重试次数
    # 计价（美元/千 token，设计文档 46 §3.3）：按模型覆盖；None 沿用内置 DeepSeek 量级近似
    pricing_per_1k: dict[str, float] | None = None


@dataclass
class SecurityConfig:
    """Web/MCP 安全配置（CORS 受信来源 + API Token 认证）"""

    cors_origins: list[str] = field(default_factory=lambda: ["http://localhost:8000"])
    auth_token: str = ""  # 从环境变量 COMPETITOR_AUTH_TOKEN 读取，不明文落码


@dataclass
class AppConfig:
    """应用级配置聚合（对应 review_config.yaml 各 section）"""

    api_base_url: str = "https://api.openai.com/v1"
    model: str = "deepseek-v4-flash"
    temperature: float = 0.1
    max_tokens: int = 2048
    llm: LLMConfig = field(default_factory=LLMConfig)
    budget: BudgetConfig = field(default_factory=BudgetConfig)
    termination: TerminationConfig = field(default_factory=TerminationConfig)
    execution: ExecutionConfig = field(default_factory=ExecutionConfig)
    dimensions: DimensionsConfig = field(default_factory=DimensionsConfig)
    collector: CollectorConfig = field(default_factory=CollectorConfig)
    stop_verifier: StopVerifierConfig = field(default_factory=StopVerifierConfig)
    memory: MemoryConfig = field(default_factory=MemoryConfig)
    report: ReportConfig = field(default_factory=ReportConfig)
    freshness: FreshnessConfig = field(default_factory=FreshnessConfig)
    observability: ObservabilityConfig = field(default_factory=ObservabilityConfig)
    security: SecurityConfig = field(default_factory=SecurityConfig)


def _build_section(cls: type[Any], data: dict[str, Any] | None) -> Any:
    """用 YAML section 字典构造 dataclass，缺失字段用默认值。"""
    if not data:
        return cls()
    known = {f for f in cls.__dataclass_fields__}
    return cls(**{k: v for k, v in data.items() if k in known})


def load_config(path: str | os.PathLike | None = None) -> AppConfig:
    """加载配置。

    Args:
        path: 配置文件路径。为 None 时优先读环境变量 COMPETITOR_AGENT_CONFIG，
            否则用默认 config/review_config.yaml。
    """
    cfg_path = Path(path) if path else Path(os.environ.get(_CONFIG_ENV, _DEFAULT_CONFIG_PATH))
    if not cfg_path.exists():
        raise FileNotFoundError(f"配置文件不存在: {cfg_path}")

    with open(cfg_path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    return AppConfig(
        api_base_url=raw.get("api_base_url", "https://api.openai.com/v1"),
        model=raw.get("model", "deepseek-v4-flash"),
        temperature=raw.get("temperature", 0.1),
        max_tokens=raw.get("max_tokens", 2048),
        llm=_build_section(LLMConfig, raw.get("llm")),
        budget=_build_section(BudgetConfig, raw.get("budget")),
        termination=_build_section(TerminationConfig, raw.get("termination")),
        execution=_build_section(ExecutionConfig, raw.get("execution")),
        dimensions=_build_section(DimensionsConfig, raw.get("dimensions")),
        collector=_build_section(CollectorConfig, raw.get("collector")),
        stop_verifier=_build_section(StopVerifierConfig, raw.get("stop_verifier")),
        memory=_build_section(MemoryConfig, raw.get("memory")),
        report=_build_section(ReportConfig, raw.get("report")),
        freshness=_build_freshness(raw.get("freshness")),
        observability=_build_section(ObservabilityConfig, raw.get("observability")),
        security=_build_security(raw.get("security")),
    )


def _build_freshness(data: dict[str, Any] | None) -> FreshnessConfig:
    """构造新鲜度配置：TLL 表只覆盖 YAML 中给出的维度，其余沿用默认（叠加）。"""
    cfg = _build_section(FreshnessConfig, data)
    if isinstance(data, dict) and isinstance(data.get("dimension_ttl_days"), dict):
        merged = dict(FreshnessConfig().dimension_ttl_days)
        merged.update(data["dimension_ttl_days"])
        cfg.dimension_ttl_days = merged
    return cfg


def _build_security(data: dict[str, Any] | None) -> SecurityConfig:
    """构造安全配置：token 优先从环境变量 COMPETITOR_AUTH_TOKEN 读取，不明文落码。"""
    cfg = _build_section(SecurityConfig, data)
    cfg.auth_token = os.environ.get("COMPETITOR_AUTH_TOKEN", cfg.auth_token)
    return cfg
