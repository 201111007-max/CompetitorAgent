"""搜索工具模块

提供 DuckDuckGo 搜索功能，用于获取 Dota 2 相关的最新信息
"""

import json
from typing import Dict, Any, Optional, List

try:
    from ..tools.base import Tool, ToolResult
    from ..utils.log_config import get_logger
except ImportError:
    from tools.base import Tool, ToolResult
    from utils.log_config import get_logger

logger = get_logger("search_tools", component="tools")


class DuckDuckGoSearchTool(Tool):
    """DuckDuckGo 搜索工具
    
    特性：
    - 免费，无需 API Key
    - 无速率限制
    - 自动添加 Dota 2 前缀
    - 返回结构化搜索结果
    
    Usage:
        tool = DuckDuckGoSearchTool()
        result = tool.execute(query="帕吉攻略")
    """
    
    def __init__(self):
        super().__init__(
            name="search_dota_info",
            description="搜索 Dota 2 相关信息，包括英雄攻略、版本更新、比赛数据、出装建议等。当需要最新信息或实时数据时使用此工具。",
            parameters={
                "query": str,
                "max_results": int
            },
            func=self._search,
            category="search"
        )
        
        self._ddgs = None
        self._initialized = False
    
    def _init_ddgs(self):
        """初始化 DuckDuckGo 搜索"""
        if self._initialized:
            return
        
        try:
            from duckduckgo_search import DDGS
            self._ddgs = DDGS
            self._initialized = True
            logger.info("DuckDuckGo 搜索工具初始化成功")
        except ImportError:
            logger.warning("duckduckgo-search 未安装，搜索功能不可用")
            self._initialized = False
    
    def _search(self, query: str, max_results: int = 5) -> Dict[str, Any]:
        """执行搜索
        
        Args:
            query: 搜索关键词
            max_results: 最大结果数量
            
        Returns:
            搜索结果字典
        """
        start_time = time.time()
        self._init_ddgs()
        
        if not self._initialized:
            elapsed = time.time() - start_time
            logger.warning(f"[SEARCH_INIT_FAILED] 搜索工具未初始化: time={elapsed:.3f}s")
            return {
                "error": "搜索功能不可用，请安装 duckduckgo-search: pip install duckduckgo-search",
                "results": []
            }
        
        dota_query = f"Dota 2 {query}"
        logger.info(f"[SEARCH_START] 开始搜索: query='{query}', dota_query='{dota_query}', max_results={max_results}")
        
        try:
            search_start = time.time()
            with self._ddgs() as ddgs:
                results = list(ddgs.text(
                    dota_query,
                    max_results=max_results
                ))
            search_elapsed = time.time() - search_start
            
            formatted_results = []
            for r in results:
                formatted_results.append({
                    "title": r.get("title", ""),
                    "url": r.get("href", ""),
                    "snippet": r.get("body", ""),
                    "source": "DuckDuckGo"
                })
            
            total_elapsed = time.time() - start_time
            logger.info(f"[SEARCH_SUCCESS] 搜索完成: query='{dota_query}', results={len(formatted_results)}, search_time={search_elapsed:.2f}s, total_time={total_elapsed:.2f}s")
            
            return {
                "query": query,
                "dota_query": dota_query,
                "results": formatted_results,
                "total": len(formatted_results),
                "elapsed": total_elapsed
            }
            
        except Exception as e:
            total_elapsed = time.time() - start_time
            logger.error(f"[SEARCH_ERROR] 搜索失败: query='{query}', error={type(e).__name__}, time={total_elapsed:.2f}s")
            return {
                "error": f"搜索失败: {str(e)}",
                "query": query,
                "results": [],
                "elapsed": total_elapsed
            }
    
    def execute(self, query: str, max_results: int = 5) -> ToolResult:
        """执行工具
        
        Args:
            query: 搜索关键词
            max_results: 最大结果数量
            
        Returns:
            ToolResult 对象
        """
        result = self._search(query, max_results)
        
        if "error" in result and result.get("results", []) == []:
            return ToolResult(
                success=False,
                data=result,
                error=result.get("error")
            )
        
        return ToolResult(
            success=True,
            data=result
        )


class DotaWikiSearchTool(Tool):
    """Dota Wiki 搜索工具
    
    直接访问 Dota 2 Wiki 获取详细信息
    """
    
    WIKI_BASE_URL = "https://dota2.fandom.com/wiki/"
    
    def __init__(self):
        super().__init__(
            name="search_dota_wiki",
            description="搜索 Dota 2 Wiki 获取英雄、物品、技能的详细信息。",
            parameters={
                "hero_name": str,
                "item_name": str
            },
            func=self._search_wiki,
            category="search"
        )
    
    def _search_wiki(self, hero_name: Optional[str] = None, item_name: Optional[str] = None) -> Dict[str, Any]:
        """搜索 Wiki
        
        Args:
            hero_name: 英雄名称（可选）
            item_name: 物品名称（可选）
            
        Returns:
            Wiki URL 信息
        """
        results = []
        
        if hero_name:
            wiki_url = f"{self.WIKI_BASE_URL}{hero_name}"
            results.append({
                "type": "hero",
                "name": hero_name,
                "url": wiki_url,
                "description": f"查看 {hero_name} 的详细英雄信息"
            })
        
        if item_name:
            wiki_url = f"{self.WIKI_BASE_URL}{item_name}"
            results.append({
                "type": "item",
                "name": item_name,
                "url": wiki_url,
                "description": f"查看 {item_name} 的详细物品信息"
            })
        
        return {
            "results": results,
            "wiki_base_url": self.WIKI_BASE_URL
        }


class WebFetchTool(Tool):
    """网页内容获取工具
    
    获取指定 URL 的内容并转换为结构化数据
    """
    
    def __init__(self):
        super().__init__(
            name="fetch_web_content",
            description="获取指定网页的内容，用于读取攻略、数据等详细信息。",
            parameters={
                "url": str
            },
            func=self._fetch,
            category="search"
        )
    
    def _fetch(self, url: str) -> Dict[str, Any]:
        """获取网页内容
        
        Args:
            url: 网页 URL
            
        Returns:
            网页内容
        """
        try:
            import requests
            from bs4 import BeautifulSoup
            
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, 'html.parser')
            
            title = soup.find('title')
            title_text = title.get_text() if title else ""
            
            content = soup.get_text(separator='\n', strip=True)
            content = content[:2000]  # 限制长度
            
            return {
                "url": url,
                "title": title_text,
                "content": content,
                "success": True
            }
            
        except ImportError:
            return {
                "error": "需要安装 requests 和 beautifulsoup4",
                "success": False
            }
        except Exception as e:
            return {
                "error": f"获取网页失败: {str(e)}",
                "url": url,
                "success": False
            }


def create_search_tools() -> List[Tool]:
    """创建所有搜索工具
    
    Returns:
        搜索工具列表
    """
    tools = []
    
    tools.append(DuckDuckGoSearchTool())
    tools.append(DotaWikiSearchTool())
    
    return tools


def get_search_tool() -> DuckDuckGoSearchTool:
    """获取默认搜索工具
    
    Returns:
        DuckDuckGo 搜索工具实例
    """
    return DuckDuckGoSearchTool()