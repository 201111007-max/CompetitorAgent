"""赛后复盘模块公共 API 门面

外部调用方应仅通过 `PostMatchReviewAPI` 与本模块交互。
"""
from post_match_review.facade.api import PostMatchReviewAPI
from post_match_review.facade.entrypoint import create_default_api

__all__ = ["PostMatchReviewAPI", "create_default_api"]
