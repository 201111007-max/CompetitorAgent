"""接口契约层 - Protocol/ABC 定义"""
from dota_helper.interfaces.analyzer import IReviewAnalyzer
from dota_helper.interfaces.budget import IIterationBudget
from dota_helper.interfaces.compressor import IContextCompressor
from dota_helper.interfaces.data_source import IMatchDataSource
from dota_helper.interfaces.llm import ILLMClient
from dota_helper.interfaces.memory import IFourLayerMemory
from dota_helper.interfaces.report import IReportBuilder
from dota_helper.interfaces.skill import ISkillStore, IAnalysisSkillStore
from dota_helper.interfaces.strategy import IStrategicLoop
from dota_helper.interfaces.verifier import IStopVerifier

__all__ = [
    "IReviewAnalyzer",
    "IIterationBudget",
    "IContextCompressor",
    "IMatchDataSource",
    "ILLMClient",
    "IFourLayerMemory",
    "IReportBuilder",
    "ISkillStore",
    "IAnalysisSkillStore",
    "IStrategicLoop",
    "IStopVerifier",
]
