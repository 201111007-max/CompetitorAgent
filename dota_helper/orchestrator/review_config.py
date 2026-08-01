"""P1-3: 类型安全的复盘配置 dataclass

替代 Runtime 中的 Dict[str, Any] 配置，提供 IDE 补全和编译期检查。
"""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class StrategicLoopConfig:
    """战略循环配置"""
    max_iterations: int = 3
    min_confidence: float = 0.6
    required_phases: List[str] = field(default_factory=lambda: [
        "laning", "teamfight", "economy", "decisions",
    ])


@dataclass
class TacticalLoopConfig:
    """战术循环配置"""
    max_iterations_per_phase: int = 3
    default_budgets: Dict[str, int] = field(default_factory=lambda: {
        "laning": 3, "teamfight": 3, "economy": 2, "decisions": 2, "vision": 1,
    })


@dataclass
class CompressionConfig:
    """上下文压缩配置"""
    enabled: bool = False
    target_max_tokens: int = 15250
    head_protect_count: int = 2
    tail_token_budget: int = 20000
    summary_token_budget: int = 750


@dataclass
class StopVerifierConfig:
    """停止验证配置"""
    required_phases: List[str] = field(default_factory=lambda: [
        "laning", "teamfight", "economy", "decisions",
    ])
    min_confidence: float = 0.6
    min_evidence_ratio: float = 0.7


@dataclass
class ReportConfig:
    """报告配置"""
    include_evidence: bool = True
    include_improvements: bool = True
    max_conclusions_per_phase: int = 5


@dataclass
class LoggingConfig:
    """日志配置"""
    level: str = "INFO"
    format: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"


@dataclass
class MemoryConfig:
    """四层记忆系统配置"""
    enabled: bool = True
    data_dir: Optional[str] = None
    background_review: bool = True
    confidence_threshold: float = 0.7
    max_persistent_notes: int = 100
    max_skills: int = 50


@dataclass
class ReviewConfig:
    """复盘总配置

    类型安全的配置对象，替代 Dict[str, Any]。
    """
    # 基础配置
    api_base_url: str = "https://api.openai.com/v1"
    model: str = "deepseek-v4-flash"
    temperature: float = 0.3
    max_tokens: int = 4000

    # 并行配置
    enable_parallel_phases: bool = False
    max_concurrency: int = 4

    # 子模块配置
    strategic_loop: StrategicLoopConfig = field(default_factory=StrategicLoopConfig)
    tactical_loop: TacticalLoopConfig = field(default_factory=TacticalLoopConfig)
    compression: CompressionConfig = field(default_factory=CompressionConfig)
    stop_verifier: StopVerifierConfig = field(default_factory=StopVerifierConfig)
    report: ReportConfig = field(default_factory=ReportConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    memory: MemoryConfig = field(default_factory=MemoryConfig)

    # 技能目录（可选）
    skills_dir: Optional[str] = None

    # 兼容旧 Dict[str, Any] 接口的 get 方法
    def get(self, key: str, default: Any = None) -> Any:
        """兼容旧字典接口的 get 方法

        Args:
            key: 配置键名
            default: 默认值

        Returns:
            Any: 配置值
        """
        # 常用键名映射
        key_map = {
            "max_iterations_per_phase": lambda: self.tactical_loop.max_iterations_per_phase,
            "required_phases": lambda: self.stop_verifier.required_phases,
            "min_confidence": lambda: self.stop_verifier.min_confidence,
            "default_budgets": lambda: self.tactical_loop.default_budgets,
            "skills_dir": lambda: self.skills_dir,
            "enable_parallel_phases": lambda: self.enable_parallel_phases,
            "max_concurrency": lambda: self.max_concurrency,
            "model": lambda: self.model,
            "temperature": lambda: self.temperature,
            "max_tokens": lambda: self.max_tokens,
        }
        if key in key_map:
            return key_map[key]()
        return default

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ReviewConfig":
        """从 YAML 加载的字典创建 ReviewConfig

        Args:
            data: YAML 配置字典

        Returns:
            ReviewConfig: 配置实例
        """
        strategic_data = data.get("strategic_loop", {})
        tactical_data = data.get("tactical_loop", {})
        compression_data = data.get("compression", {})
        verifier_data = data.get("stop_verifier", {})
        report_data = data.get("report", {})
        logging_data = data.get("logging", {})
        memory_data = data.get("memory", {})

        return cls(
            api_base_url=data.get("api_base_url", cls.api_base_url),
            model=data.get("model", cls.model),
            temperature=data.get("temperature", cls.temperature),
            max_tokens=data.get("max_tokens", cls.max_tokens),
            enable_parallel_phases=data.get("enable_parallel_phases", cls.enable_parallel_phases),
            max_concurrency=data.get("max_concurrency", cls.max_concurrency),
            strategic_loop=StrategicLoopConfig(
                max_iterations=strategic_data.get("max_iterations", 3),
                min_confidence=strategic_data.get("min_confidence", 0.6),
                required_phases=strategic_data.get("required_phases", [
                    "laning", "teamfight", "economy", "decisions",
                ]),
            ),
            tactical_loop=TacticalLoopConfig(
                max_iterations_per_phase=tactical_data.get("max_iterations_per_phase", 3),
                default_budgets=tactical_data.get("default_budgets", {
                    "laning": 3, "teamfight": 3, "economy": 2, "decisions": 2, "vision": 1,
                }),
            ),
            compression=CompressionConfig(
                enabled=compression_data.get("enabled", False),
                target_max_tokens=compression_data.get("target_max_tokens", 15250),
                head_protect_count=compression_data.get("head_protect_count", 2),
                tail_token_budget=compression_data.get("tail_token_budget", 20000),
                summary_token_budget=compression_data.get("summary_token_budget", 750),
            ),
            stop_verifier=StopVerifierConfig(
                required_phases=verifier_data.get("required_phases", [
                    "laning", "teamfight", "economy", "decisions",
                ]),
                min_confidence=verifier_data.get("min_confidence", 0.6),
                min_evidence_ratio=verifier_data.get("min_evidence_ratio", 0.7),
            ),
            report=ReportConfig(
                include_evidence=report_data.get("include_evidence", True),
                include_improvements=report_data.get("include_improvements", True),
                max_conclusions_per_phase=report_data.get("max_conclusions_per_phase", 5),
            ),
            logging=LoggingConfig(
                level=logging_data.get("level", "INFO"),
                format=logging_data.get("format", LoggingConfig.format),
            ),
            memory=MemoryConfig(
                enabled=memory_data.get("enabled", True),
                data_dir=memory_data.get("data_dir"),
                background_review=memory_data.get("background_review", True),
                confidence_threshold=memory_data.get("confidence_threshold", 0.7),
                max_persistent_notes=memory_data.get("max_persistent_notes", 100),
                max_skills=memory_data.get("max_skills", 50),
            ),
            skills_dir=data.get("skills_dir"),
        )
