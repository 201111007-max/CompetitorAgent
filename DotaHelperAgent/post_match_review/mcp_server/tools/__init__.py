"""MCP 工具模块

导入子模块以触发 @mcp.tool() 装饰器注册。
"""

from post_match_review.mcp_server.tools import match_tools  # noqa: F401
from post_match_review.mcp_server.tools import hero_tools  # noqa: F401
from post_match_review.mcp_server.tools import player_tools  # noqa: F401
from post_match_review.mcp_server.tools import team_tools  # noqa: F401
from post_match_review.mcp_server.tools import ward_tools  # noqa: F401
from post_match_review.mcp_server.tools import search_tools  # noqa: F401
from post_match_review.mcp_server.tools import stats_tools  # noqa: F401
from post_match_review.mcp_server.tools import review_tools  # noqa: F401
