"""接口契约层 - Protocol/ABC 定义"""
from post_match_review.interfaces.analyzer import IReviewAnalyzer
from post_match_review.interfaces.budget import IIterationBudget
from post_match_review.interfaces.compressor import IContextCompressor
from post_match_review.interfaces.data_source import IMatchDataSource
from post_match_review.interfaces.llm import ILLMClient
from post_match_review.interfaces.memory import IFourLayerMemory
from post_match_review.interfaces.report import IReportBuilder
from post_match_review.interfaces.skill import ISkillStore
from post_match_review.interfaces.strategy import IStrategicLoop
from post_match_review.interfaces.verifier import IStopVerifier

__all__ = [
    "IReviewAnalyzer",
    "IIterationBudget",
    "IContextCompressor",
    "IMatchDataSource",
    "ILLMClient",
    "IFourLayerMemory",
    "IReportBuilder",
    "ISkillStore",
    "IStrategicLoop",
    "IStopVerifier",
]
