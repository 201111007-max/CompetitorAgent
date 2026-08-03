"""竞品分析 Agent（competitor_agent）

复用 dota_helper 的框架思想，独立目录、独立包，零 import 耦合。
外部唯一入口：CompetitorAnalysisAPI（facade/api.py）。
"""

from competitor_agent.facade.api import CompetitorAnalysisAPI

__version__ = "0.1.0"

__all__ = ["CompetitorAnalysisAPI", "__version__"]
