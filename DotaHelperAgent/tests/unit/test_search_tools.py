"""SearchTools 单元测试"""

import pytest
from unittest.mock import Mock, MagicMock, patch

from tools.search_tools import (
    DuckDuckGoSearchTool,
    DotaWikiSearchTool,
    WebFetchTool,
    create_search_tools,
    get_search_tool
)
from tools.base import ToolResult


class TestDuckDuckGoSearchTool:
    """DuckDuckGoSearchTool 测试类"""
    
    @pytest.fixture
    def search_tool(self):
        """创建搜索工具"""
        return DuckDuckGoSearchTool()
    
    def test_init(self, search_tool):
        """测试初始化"""
        assert search_tool is not None
        assert search_tool.name == "search_dota_info"
        assert search_tool.category == "search"
    
    def test_search_mock(self, search_tool):
        """测试搜索（模拟）"""
        search_tool._initialized = True
        search_tool._ddgs = Mock()
        
        mock_results = [
            {"title": "Dota 2 帕吉攻略", "href": "https://example.com", "body": "帕吉是一个强力英雄..."}
        ]
        
        mock_ddgs_instance = Mock()
        mock_ddgs_instance.text = Mock(return_value=mock_results)
        search_tool._ddgs.return_value = mock_ddgs_instance
        
        result = search_tool._search("帕吉攻略", max_results=1)
        
        assert "query" in result
        assert "results" in result
        assert result["query"] == "帕吉攻略"
    
    def test_search_without_duckduckgo(self, search_tool):
        """测试未安装 duckduckgo-search"""
        search_tool._initialized = False
        
        result = search_tool._search("帕吉攻略")
        
        assert "error" in result
        assert "duckduckgo-search" in result["error"]
    
    def test_execute_success(self, search_tool):
        """测试执行成功"""
        search_tool._initialized = True
        search_tool._ddgs = Mock()
        
        mock_results = [
            {"title": "Test", "href": "https://test.com", "body": "Test content"}
        ]
        
        mock_ddgs_instance = Mock()
        mock_ddgs_instance.text = Mock(return_value=mock_results)
        search_tool._ddgs.return_value = mock_ddgs_instance
        
        result = search_tool.execute("test query", max_results=1)
        
        assert result.success is True
        assert result.data is not None
    
    def test_execute_failure(self, search_tool):
        """测试执行失败"""
        search_tool._initialized = False
        
        result = search_tool.execute("test query")
        
        assert result.success is False
        assert result.error is not None
    
    def test_dota_prefix(self, search_tool):
        """测试 Dota 2 前缀"""
        search_tool._initialized = True
        search_tool._ddgs = Mock()
        
        mock_ddgs_instance = Mock()
        mock_ddgs_instance.text = Mock(return_value=[])
        search_tool._ddgs.return_value = mock_ddgs_instance
        
        result = search_tool._search("帕吉")
        
        assert "dota_query" in result
        assert "Dota 2" in result["dota_query"]


class TestDotaWikiSearchTool:
    """DotaWikiSearchTool 测试类"""
    
    @pytest.fixture
    def wiki_tool(self):
        """创建 Wiki 搜索工具"""
        return DotaWikiSearchTool()
    
    def test_init(self, wiki_tool):
        """测试初始化"""
        assert wiki_tool is not None
        assert wiki_tool.name == "search_dota_wiki"
        assert wiki_tool.WIKI_BASE_URL == "https://dota2.fandom.com/wiki/"
    
    def test_search_hero(self, wiki_tool):
        """测试搜索英雄"""
        result = wiki_tool._search_wiki(hero_name="Pudge")
        
        assert "results" in result
        assert len(result["results"]) == 1
        assert result["results"][0]["type"] == "hero"
        assert "Pudge" in result["results"][0]["url"]
    
    def test_search_item(self, wiki_tool):
        """测试搜索物品"""
        result = wiki_tool._search_wiki(item_name="Blink")
        
        assert "results" in result
        assert len(result["results"]) == 1
        assert result["results"][0]["type"] == "item"
        assert "Blink" in result["results"][0]["url"]
    
    def test_search_both(self, wiki_tool):
        """测试同时搜索英雄和物品"""
        result = wiki_tool._search_wiki(hero_name="Pudge", item_name="Blink")
        
        assert len(result["results"]) == 2


class TestWebFetchTool:
    """WebFetchTool 测试类"""
    
    @pytest.fixture
    def fetch_tool(self):
        """创建网页获取工具"""
        return WebFetchTool()
    
    def test_init(self, fetch_tool):
        """测试初始化"""
        assert fetch_tool is not None
        assert fetch_tool.name == "fetch_web_content"
    
    @patch('requests.get')
    def test_fetch_success(self, mock_get, fetch_tool):
        """测试成功获取网页"""
        mock_response = Mock()
        mock_response.text = "<html><title>Test</title><body>Content</body></html>"
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response
        
        with patch('bs4.BeautifulSoup') as mock_bs:
            mock_soup = Mock()
            mock_soup.find = Mock(return_value=Mock(get_text=Mock(return_value="Test")))
            mock_soup.get_text = Mock(return_value="Test Content")
            mock_bs.return_value = mock_soup
            
            result = fetch_tool._fetch("https://example.com")
            
            assert result["success"] is True
            assert "title" in result
            assert "content" in result
    
    def test_fetch_without_requests(self, fetch_tool):
        """测试未安装 requests"""
        with patch.dict('sys.modules', {'requests': None, 'bs4': None}):
            result = fetch_tool._fetch("https://example.com")
            
            assert result["success"] is False
            assert "error" in result


class TestSearchToolsFactory:
    """搜索工具工厂测试"""
    
    def test_create_search_tools(self):
        """测试创建所有搜索工具"""
        tools = create_search_tools()
        
        assert len(tools) >= 2
        assert any(t.name == "search_dota_info" for t in tools)
        assert any(t.name == "search_dota_wiki" for t in tools)
    
    def test_get_search_tool(self):
        """测试获取默认搜索工具"""
        tool = get_search_tool()
        
        assert tool is not None
        assert tool.name == "search_dota_info"
        assert isinstance(tool, DuckDuckGoSearchTool)


class TestSearchToolsIntegration:
    """搜索工具集成测试"""
    
    def test_tool_result_format(self):
        """测试工具结果格式"""
        tool = DuckDuckGoSearchTool()
        tool._initialized = False
        
        result = tool.execute("test")
        
        assert isinstance(result, ToolResult)
        assert hasattr(result, 'success')
        assert hasattr(result, 'data')
        assert hasattr(result, 'error')


if __name__ == "__main__":
    pytest.main([__file__, "-v"])