"""垂直领域 Agent 框架（示例领域：Dota 2 赛后复盘）

提供从单轮查询工具到自主多步分析 Agent 的转型。
框架层（编排/引擎/记忆/可观测）与领域层（数据源/分析器/工具）解耦，
接入新垂直领域只需替换领域层实现。

外部调用方应仅通过 `PostMatchReviewAPI` 与本包交互：

    from dota_helper import PostMatchReviewAPI

    api = PostMatchReviewAPI()
    report = await api.review(match_id)
"""

from dota_helper.facade.api import PostMatchReviewAPI
from dota_helper.facade.entrypoint import create_default_api

__version__ = "0.1.0"
__all__ = ["PostMatchReviewAPI", "create_default_api"]
