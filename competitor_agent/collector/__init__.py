"""collector 包：数据源采集器"""
from competitor_agent.collector.source_selector import SourceCandidate, SourceSelector
from competitor_agent.collector.spa_extractor import SpaExtractor
from competitor_agent.collector.web_extractor import WebExtractor

__all__ = ["SourceCandidate", "SourceSelector", "SpaExtractor", "WebExtractor"]