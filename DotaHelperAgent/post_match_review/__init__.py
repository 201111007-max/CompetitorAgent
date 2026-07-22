"""赛后复盘 Agent - 独立顶级包

提供从单轮查询工具到自主多步分析 Agent 的转型。

外部调用方应仅通过 `PostMatchReviewAPI` 与本包交互：

    from post_match_review import PostMatchReviewAPI

    api = PostMatchReviewAPI()
    report = await api.review(match_id)
"""

from post_match_review.facade.api import PostMatchReviewAPI
from post_match_review.facade.entrypoint import create_default_api

__version__ = "0.1.0"
__all__ = ["PostMatchReviewAPI", "create_default_api"]
