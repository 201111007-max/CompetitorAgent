"""LLM Tool Selector 单元测试

测试 LLM 工具选择器的核心功能
"""

import pytest
import json
from unittest.mock import Mock, patch, MagicMock
import sys
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from core.llm_tool_selector import LLMToolSelector, ToolCall, ToolCallPlan
from core.tool_registry import ToolRegistry
from tools.base import Tool


class TestToolCall:
    """测试 ToolCall 数据类"""

    def test_tool_call_creation(self):
        """测试 ToolCall 创建"""
        tool_call = ToolCall(
            tool_name="analyze_counter_picks",
            parameters={"our_heroes": [], "enemy_heroes": ["pudge"], "top_n": 3}
        )
        assert tool_call.tool_name == "analyze_counter_picks"
        assert tool_call.parameters["enemy_heroes"] == ["pudge"]
        assert tool_call.parameters["top_n"] == 3


class TestToolCallPlan:
    """测试 ToolCallPlan 数据类"""

    def test_tool_call_plan_creation(self):
        """测试 ToolCallPlan 创建"""
        tools = [
            ToolCall(tool_name="analyze_counter_picks", parameters={}),
            ToolCall(tool_name="recommend_items", parameters={})
        ]
        plan = ToolCallPlan(
            tools=tools,
            reasoning="用户需要克制分析和出装推荐"
        )
        assert len(plan.tools) == 2
        assert plan.reasoning == "用户需要克制分析和出装推荐"


class TestLLMToolSelector:
    """测试 LLMToolSelector 核心功能"""

    @pytest.fixture
    def mock_llm_client(self):
        """模拟 LLM 客户端"""
        client = Mock()
        return client

    @pytest.fixture
    def mock_tool_registry(self):
        """模拟工具注册表"""
        registry = ToolRegistry()
        
        # 注册一些测试工具
        registry.register(Tool(
            name="analyze_counter_picks",
            description="分析英雄克制关系",
            parameters={
                "our_heroes": list,
                "enemy_heroes": list,
                "top_n": int
            },
            func=lambda **kwargs: {},
            category="hero_analysis"
        ))
        
        registry.register(Tool(
            name="recommend_items",
            description="推荐物品出装",
            parameters={
                "hero_name": str,
                "game_stage": str,
                "enemy_heroes": list
            },
            func=lambda **kwargs: {},
            category="item_recommendation"
        ))
        
        registry.register(Tool(
            name="recommend_skills",
            description="推荐技能加点",
            parameters={
                "hero_name": str,
                "play_style": str
            },
            func=lambda **kwargs: {},
            category="skill_recommendation"
        ))
        
        return registry

    @pytest.fixture
    def selector(self, mock_llm_client, mock_tool_registry):
        """创建选择器实例"""
        return LLMToolSelector(mock_llm_client, mock_tool_registry)

    def test_init(self, selector, mock_llm_client, mock_tool_registry):
        """测试初始化"""
        assert selector.llm == mock_llm_client
        assert selector.registry == mock_tool_registry

    def test_select_tools_success(self, selector, mock_llm_client):
        """测试成功选择工具"""
        # 模拟 LLM 返回
        mock_llm_client.chat.return_value = {
            'choices': [{
                'message': {
                    'content': json.dumps({
                        "reasoning": "用户需要克制分析",
                        "tools": [
                            {
                                "name": "analyze_counter_picks",
                                "parameters": {
                                    "our_heroes": [],
                                    "enemy_heroes": ["pudge", "axe"],
                                    "top_n": 3
                                }
                            }
                        ]
                    })
                }
            }]
        }

        # 执行选择
        plan = selector.select_tools(
            query="推荐克制敌方帕吉和斧王的英雄",
            context={"our_heroes": [], "enemy_heroes": ["pudge", "axe"]}
        )

        # 验证结果
        assert isinstance(plan, ToolCallPlan)
        assert len(plan.tools) == 1
        assert plan.tools[0].tool_name == "analyze_counter_picks"
        assert plan.tools[0].parameters["enemy_heroes"] == ["pudge", "axe"]
        assert plan.tools[0].parameters["top_n"] == 3
        assert "克制分析" in plan.reasoning

        # 验证 LLM 被调用
        mock_llm_client.chat.assert_called_once()

    def test_select_tools_multiple(self, selector, mock_llm_client):
        """测试选择多个工具"""
        # 模拟 LLM 返回多个工具
        mock_llm_client.chat.return_value = {
            'choices': [{
                'message': {
                    'content': json.dumps({
                        "reasoning": "用户需要克制分析和出装推荐",
                        "tools": [
                            {
                                "name": "analyze_counter_picks",
                                "parameters": {
                                    "our_heroes": [],
                                    "enemy_heroes": ["pudge"],
                                    "top_n": 3
                                }
                            },
                            {
                                "name": "recommend_items",
                                "parameters": {
                                    "hero_name": "anti-mage",
                                    "game_stage": "all",
                                    "enemy_heroes": ["pudge"]
                                }
                            }
                        ]
                    })
                }
            }]
        }

        # 执行选择
        plan = selector.select_tools(
            query="推荐克制帕吉的英雄，并告诉我敌法师怎么出装",
            context={}
        )

        # 验证结果
        assert len(plan.tools) == 2
        assert plan.tools[0].tool_name == "analyze_counter_picks"
        assert plan.tools[1].tool_name == "recommend_items"

    def test_select_tools_with_markdown_code_block(self, selector, mock_llm_client):
        """测试从 markdown 代码块中提取 JSON"""
        # 模拟 LLM 返回包含 markdown 代码块
        mock_llm_client.chat.return_value = {
            'choices': [{
                'message': {
                    'content': '''好的，我来分析这个查询。

```json
{
    "reasoning": "用户需要克制分析",
    "tools": [
        {
            "name": "analyze_counter_picks",
            "parameters": {
                "our_heroes": [],
                "enemy_heroes": ["pudge"],
                "top_n": 3
            }
        }
    ]
}
```

希望这个分析对你有帮助。'''
                }
            }]
        }

        # 执行选择
        plan = selector.select_tools(
            query="推荐克制帕吉的英雄",
            context={}
        )

        # 验证结果
        assert len(plan.tools) == 1
        assert plan.tools[0].tool_name == "analyze_counter_picks"

    def test_select_tools_llm_error(self, selector, mock_llm_client):
        """测试 LLM 返回错误"""
        # 模拟 LLM 错误
        mock_llm_client.chat.return_value = {
            'error': 'LLM service unavailable'
        }

        # 验证抛出异常
        with pytest.raises(Exception) as exc_info:
            selector.select_tools(query="测试查询", context={})
        
        assert "LLM 工具选择失败" in str(exc_info.value)

    def test_select_tools_invalid_json(self, selector, mock_llm_client):
        """测试 LLM 返回无效 JSON"""
        # 模拟 LLM 返回无效 JSON
        mock_llm_client.chat.return_value = {
            'choices': [{
                'message': {
                    'content': '这不是有效的 JSON'
                }
            }]
        }

        # 验证抛出异常
        with pytest.raises(Exception) as exc_info:
            selector.select_tools(query="测试查询", context={})
        
        assert "JSON 解析失败" in str(exc_info.value)

    def test_select_tools_missing_tools_field(self, selector, mock_llm_client):
        """测试 LLM 返回缺少 tools 字段"""
        # 模拟 LLM 返回缺少必要字段
        mock_llm_client.chat.return_value = {
            'choices': [{
                'message': {
                    'content': json.dumps({
                        "reasoning": "缺少 tools 字段"
                    })
                }
            }]
        }

        # 验证抛出异常
        with pytest.raises(Exception) as exc_info:
            selector.select_tools(query="测试查询", context={})
        
        assert "缺少 'tools' 字段" in str(exc_info.value)

    def test_select_tools_invalid_tool_name(self, selector, mock_llm_client):
        """测试 LLM 选择不存在的工具"""
        # 模拟 LLM 选择不存在的工具
        mock_llm_client.chat.return_value = {
            'choices': [{
                'message': {
                    'content': json.dumps({
                        "reasoning": "选择了不存在的工具",
                        "tools": [
                            {
                                "name": "non_existent_tool",
                                "parameters": {}
                            }
                        ]
                    })
                }
            }]
        }

        # 验证抛出异常
        with pytest.raises(Exception) as exc_info:
            selector.select_tools(query="测试查询", context={})
        
        assert "工具 'non_existent_tool' 不存在" in str(exc_info.value)

    def test_select_tools_empty_tools_list(self, selector, mock_llm_client):
        """测试 LLM 返回空工具列表"""
        # 模拟 LLM 返回空列表
        mock_llm_client.chat.return_value = {
            'choices': [{
                'message': {
                    'content': json.dumps({
                        "reasoning": "没有合适的工具",
                        "tools": []
                    })
                }
            }]
        }

        # 验证抛出异常
        with pytest.raises(Exception) as exc_info:
            selector.select_tools(query="测试查询", context={})
        
        assert "工具计划为空" in str(exc_info.value)

    def test_format_tools_description(self, selector):
        """测试工具描述格式化"""
        desc = selector._format_tools_description()
        
        # 验证包含工具信息
        assert "analyze_counter_picks" in desc
        assert "recommend_items" in desc
        assert "recommend_skills" in desc
        assert "描述：" in desc
        assert "参数：" in desc

    def test_format_context_empty(self, selector):
        """测试空上下文格式化"""
        context_info = selector._format_context(None)
        assert context_info == "无额外上下文"

    def test_format_context_with_data(self, selector):
        """测试有数据的上下文格式化"""
        context = {
            "our_heroes": ["anti-mage"],
            "enemy_heroes": ["pudge"],
            "memory_context": ["历史对话"]
        }
        context_info = selector._format_context(context)
        
        assert "our_heroes" in context_info
        assert "enemy_heroes" in context_info
        assert "历史对话记忆" in context_info

    def test_extract_json_from_markdown(self, selector):
        """测试从 markdown 中提取 JSON"""
        content = '''一些文本
```json
{"key": "value"}
```
更多文本'''
        json_str = selector._extract_json(content)
        assert json_str == '{"key": "value"}'

    def test_extract_json_plain(self, selector):
        """测试纯文本 JSON 提取"""
        content = '{"key": "value"}'
        json_str = selector._extract_json(content)
        assert json_str == '{"key": "value"}'

    def test_validate_plan_valid(self, selector):
        """测试验证有效计划"""
        plan = ToolCallPlan(
            tools=[
                ToolCall(tool_name="analyze_counter_picks", parameters={})
            ],
            reasoning="测试"
        )
        # 不应抛出异常
        selector._validate_plan(plan)

    def test_validate_plan_invalid_tool(self, selector):
        """测试验证无效工具"""
        plan = ToolCallPlan(
            tools=[
                ToolCall(tool_name="invalid_tool", parameters={})
            ],
            reasoning="测试"
        )
        with pytest.raises(Exception) as exc_info:
            selector._validate_plan(plan)
        assert "工具 'invalid_tool' 不存在" in str(exc_info.value)

    def test_validate_plan_empty(self, selector):
        """测试验证空计划"""
        plan = ToolCallPlan(
            tools=[],
            reasoning="测试"
        )
        with pytest.raises(Exception) as exc_info:
            selector._validate_plan(plan)
        assert "工具计划为空" in str(exc_info.value)


class TestLLMToolSelectorIntegration:
    """集成测试"""

    @pytest.fixture
    def mock_llm_client(self):
        """模拟 LLM 客户端"""
        client = Mock()
        return client

    @pytest.fixture
    def mock_tool_registry(self):
        """模拟工具注册表"""
        registry = ToolRegistry()
        
        registry.register(Tool(
            name="analyze_counter_picks",
            description="分析英雄克制关系",
            parameters={
                "our_heroes": list,
                "enemy_heroes": list,
                "top_n": int
            },
            func=lambda our_heroes, enemy_heroes, top_n=3: {
                "recommendations": [
                    {"hero_name": "luna", "score": 0.8, "reasons": ["远程克制"]}
                ]
            },
            category="hero_analysis"
        ))
        
        return registry

    def test_full_workflow(self, mock_llm_client, mock_tool_registry):
        """测试完整工作流程"""
        # 模拟 LLM 返回
        mock_llm_client.chat.return_value = {
            'choices': [{
                'message': {
                    'content': json.dumps({
                        "reasoning": "用户需要克制分析",
                        "tools": [
                            {
                                "name": "analyze_counter_picks",
                                "parameters": {
                                    "our_heroes": [],
                                    "enemy_heroes": ["pudge", "axe"],
                                    "top_n": 3
                                }
                            }
                        ]
                    })
                }
            }]
        }

        # 创建选择器
        selector = LLMToolSelector(mock_llm_client, mock_tool_registry)

        # 执行选择
        plan = selector.select_tools(
            query="推荐克制敌方帕吉和斧王的英雄",
            context={"our_heroes": [], "enemy_heroes": ["pudge", "axe"]}
        )

        # 验证计划
        assert len(plan.tools) == 1
        assert plan.tools[0].tool_name == "analyze_counter_picks"
        
        # 执行工具
        tool = mock_tool_registry.get("analyze_counter_picks")
        assert tool is not None
        
        result = mock_tool_registry.execute(
            "analyze_counter_picks",
            **plan.tools[0].parameters
        )
        
        assert result.is_success()
        assert "recommendations" in result.data


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
