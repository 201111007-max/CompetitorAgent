"""分析器基类单元测试"""
import pytest
from unittest.mock import Mock
from typing import List, Dict, Any

from post_match_review.analyzers.base import BaseLLMReviewAnalyzer
from post_match_review.interfaces.llm import ILLMClient
from post_match_review.domain_types.analysis import Conclusion, AnalysisContext
from post_match_review.domain_types.match_data import MatchData
from post_match_review.engines.budget import IterationBudget


class ConcreteAnalyzer(BaseLLMReviewAnalyzer):
    """用于测试的具体分析器实现"""
    
    @property
    def phase_name(self) -> str:
        return "test_phase"
    
    def _format_domain_data(self, match_data: MatchData) -> str:
        """格式化领域数据"""
        return "## 测试数据\n- 测试项 1\n- 测试项 2"
    
    def _calculate_confidence(self, conclusions: List[Conclusion]) -> float:
        """计算置信度"""
        if not conclusions:
            return 0.0
        return 0.8


class TestBaseLLMReviewAnalyzer:
    """测试分析器基类"""
    
    @pytest.fixture
    def mock_llm_client(self) -> Mock:
        """模拟 LLM 客户端"""
        client = Mock(spec=ILLMClient)
        return client
    
    @pytest.fixture
    def analyzer(self, mock_llm_client: Mock) -> ConcreteAnalyzer:
        """创建测试分析器实例"""
        return ConcreteAnalyzer(mock_llm_client)
    
    @pytest.fixture
    def sample_match_data(self) -> MatchData:
        """创建样本比赛数据"""
        return MatchData(
            match_id="test_match_001",
            duration=1800,
            radiant_win=True,
            radiant_score=30,
            dire_score=20,
            game_mode=22,
            players=[],
            picks_bans=[],
            lane_data=None,
            teamfight_data=None,
            economy_data=None,
            raw_metadata={}
        )
    
    @pytest.fixture
    def sample_context(self) -> AnalysisContext:
        """创建样本分析上下文"""
        budget = IterationBudget(max_iterations=3, max_tokens=10000)
        return AnalysisContext(
            phase="test_phase",
            budget=budget,
            completed_results=[],
            iteration_feedback=None
        )
    
    # ==================== parse_response() 测试 ====================
    
    def test_parse_response_with_conclusions_key(self, analyzer: ConcreteAnalyzer):
        """测试解析包含 conclusions 键的 JSON 响应"""
        response = """
        {
            "conclusions": [
                {
                    "title": "测试结论 1",
                    "content": "这是测试内容",
                    "evidence": ["证据 1", "证据 2"],
                    "impact": "high"
                },
                {
                    "title": "测试结论 2",
                    "content": "另一个测试内容",
                    "evidence": ["证据 3"],
                    "impact": "medium"
                }
            ]
        }
        """
        
        conclusions = analyzer.parse_response(response)
        
        assert len(conclusions) == 2
        assert conclusions[0].title == "测试结论 1"
        assert conclusions[0].content == "这是测试内容"
        assert len(conclusions[0].evidence) == 2
        assert conclusions[0].impact == "high"
        assert conclusions[1].title == "测试结论 2"
    
    def test_parse_response_with_analysis_key(self, analyzer: ConcreteAnalyzer):
        """测试解析包含 analysis 键的 JSON 响应"""
        response = """
        {
            "analysis": {
                "key_finding": {
                    "conclusion": "关键发现内容",
                    "evidence": ["证据 A", "证据 B"]
                },
                "another_finding": {
                    "conclusion": "另一个发现",
                    "evidence": ["证据 C"]
                }
            }
        }
        """
        
        conclusions = analyzer.parse_response(response)
        
        assert len(conclusions) == 2
        assert all(isinstance(c, Conclusion) for c in conclusions)
        assert any("Key Finding" in c.title for c in conclusions)
    
    def test_parse_response_with_single_json_object(self, analyzer: ConcreteAnalyzer):
        """测试解析单个 JSON 对象（无 conclusions/analysis 键）"""
        response = """
        {
            "title": "单个结论",
            "content": "结论内容",
            "evidence": ["证据 1"],
            "impact": "low"
        }
        """
        
        conclusions = analyzer.parse_response(response)
        
        assert len(conclusions) == 1
        # _fallback_single_conclusion 返回固定标题 "分析结果"，但会提取 JSON 中的 impact
        assert conclusions[0].title == "分析结果"
        assert conclusions[0].impact == "low"
    
    def test_parse_response_with_text_fallback(self, analyzer: ConcreteAnalyzer):
        """测试文本降级解析"""
        response = """这是第一段分析内容,包含多个句子的详细分析。
包含多个句子的分析。

这是第二段分析内容,也是重要的发现,需要详细说明。
也是重要的发现。

这是第三段内容,虽然较短但仍有分析价值。"""
        
        conclusions = analyzer.parse_response(response)
        
        # 文本降级会将每个段落(按\n\n分割)作为一个结论,跳过长度<20的段落
        assert len(conclusions) >= 2
        assert all(isinstance(c, Conclusion) for c in conclusions)
    
    def test_parse_response_with_invalid_json(self, analyzer: ConcreteAnalyzer):
        """测试解析无效 JSON（应降级到文本解析）"""
        response = "这不是 JSON，只是普通文本分析结果。"
        
        conclusions = analyzer.parse_response(response)
        
        # 应该通过文本降级解析出至少 1 条结论
        assert len(conclusions) >= 1
        assert isinstance(conclusions[0], Conclusion)
    
    # ==================== _parse_conclusion() 测试 ====================
    
    def test_parse_conclusion_with_list_evidence(self, analyzer: ConcreteAnalyzer):
        """测试解析列表格式的证据"""
        data = {
            "title": "测试标题",
            "content": "测试内容",
            "evidence": ["证据 1", "证据 2", "证据 3"],
            "impact": "high"
        }
        
        conclusion = analyzer._parse_conclusion(data)
        
        assert conclusion.title == "测试标题"
        assert conclusion.content == "测试内容"
        assert len(conclusion.evidence) == 3
        assert conclusion.impact == "high"
        assert conclusion.has_evidence is True
    
    def test_parse_conclusion_with_dict_evidence(self, analyzer: ConcreteAnalyzer):
        """测试解析字典格式的证据"""
        data = {
            "title": "测试标题",
            "content": "测试内容",
            "evidence": {
                "stat_1": "数值 1",
                "stat_2": "数值 2"
            },
            "impact": "medium"
        }
        
        conclusion = analyzer._parse_conclusion(data)
        
        assert len(conclusion.evidence) == 2
        assert "数值 1" in conclusion.evidence
        assert "数值 2" in conclusion.evidence
        assert conclusion.has_evidence is True
    
    def test_parse_conclusion_without_evidence(self, analyzer: ConcreteAnalyzer):
        """测试解析无证据的结论"""
        data = {
            "title": "测试标题",
            "content": "测试内容",
            "impact": "low"
        }
        
        conclusion = analyzer._parse_conclusion(data)
        
        assert conclusion.evidence == []
        assert conclusion.has_evidence is False
    
    def test_parse_conclusion_with_finding_key(self, analyzer: ConcreteAnalyzer):
        """测试解析使用 finding 键而非 content 键"""
        data = {
            "title": "测试标题",
            "finding": "使用 finding 键的内容",
            "evidence": ["证据"],
            "impact": "medium"
        }
        
        conclusion = analyzer._parse_conclusion(data)
        
        assert conclusion.content == "使用 finding 键的内容"
    
    def test_parse_conclusion_with_default_values(self, analyzer: ConcreteAnalyzer):
        """测试解析缺少字段的结论（使用默认值）"""
        data = {}
        
        conclusion = analyzer._parse_conclusion(data)
        
        assert conclusion.title == "未命名结论"
        assert conclusion.content == ""
        assert conclusion.impact == "medium"
        assert conclusion.evidence == []
    
    # ==================== _extract_from_analysis() 测试 ====================
    
    def test_extract_from_analysis_with_multiple_findings(self, analyzer: ConcreteAnalyzer):
        """测试从 analysis 中提取多个发现"""
        parsed = {
            "analysis": {
                "finding_one": {
                    "conclusion": "发现一的内容",
                    "evidence": ["证据 A"]
                },
                "finding_two": {
                    "conclusion": "发现二的内容",
                    "evidence": ["证据 B", "证据 C"]
                }
            }
        }
        
        conclusions = analyzer._extract_from_analysis(parsed)
        
        assert len(conclusions) == 2
        assert all(isinstance(c, Conclusion) for c in conclusions)
    
    def test_extract_from_analysis_with_non_dict_analysis(self, analyzer: ConcreteAnalyzer):
        """测试 analysis 字段为非字典的情况"""
        parsed = {
            "analysis": "这是一个字符串形式的分析结果",
            "evidence": ["证据 1"]
        }
        
        conclusions = analyzer._extract_from_analysis(parsed)
        
        assert len(conclusions) == 1
        assert "字符串形式" in conclusions[0].content
    
    # ==================== _fallback_single_conclusion() 测试 ====================
    
    def test_fallback_single_conclusion(self, analyzer: ConcreteAnalyzer):
        """测试降级为单个结论"""
        parsed = {
            "some_key": "some_value",
            "another_key": 123,
            "evidence": ["证据 X", "证据 Y"]
        }
        
        conclusion = analyzer._fallback_single_conclusion(parsed)
        
        assert conclusion.title == "分析结果"
        assert "some_key" in conclusion.content
        assert len(conclusion.evidence) == 2
        assert conclusion.has_evidence is True
    
    # ==================== _parse_conclusions_from_text() 测试 ====================
    
    def test_parse_conclusions_from_text_multiple_paragraphs(self, analyzer: ConcreteAnalyzer):
        """测试从多段落文本中提取结论"""
        text = """第一段分析内容，包含重要的发现。
这里有详细的说明。

第二段分析内容，另一个重要发现。
继续详细说明。

第三段分析内容。"""
        
        conclusions = analyzer._parse_conclusions_from_text(text)
        
        assert len(conclusions) >= 2
        assert all(isinstance(c, Conclusion) for c in conclusions)
        assert all(c.has_evidence is False for c in conclusions)
    
    def test_parse_conclusions_from_text_short_paragraphs(self, analyzer: ConcreteAnalyzer):
        """测试短段落被跳过"""
        text = """短。

这是一个足够长的段落，应该被提取为结论。
包含多行内容。

也很短。

另一个长段落，包含详细的分析内容。
这里有多行说明。"""
        
        conclusions = analyzer._parse_conclusions_from_text(text)
        
        # 应该只提取长段落（跳过长度<20的段落）
        assert len(conclusions) >= 2
        # 验证短段落（"短。" 和 "也很短。"）没有被提取
        assert all("短。" != c.title for c in conclusions)
        assert all("也很短。" != c.title for c in conclusions)
    
    # ==================== build_prompt() 模板方法测试 ====================
    
    def test_build_prompt_calls_format_domain_data(
        self,
        analyzer: ConcreteAnalyzer,
        sample_match_data: MatchData,
        sample_context: AnalysisContext
    ):
        """测试 build_prompt 调用 _format_domain_data"""
        messages = analyzer.build_prompt(sample_match_data, sample_context)
        
        # PromptBuilder 可能返回多条消息(system + 多个user消息)
        assert len(messages) >= 2
        assert messages[0]["role"] == "system"
        # 检查所有user消息中是否包含领域数据
        user_contents = [m["content"] for m in messages if m["role"] == "user"]
        assert any("测试数据" in content for content in user_contents)
    
    def test_build_prompt_appends_domain_data(
        self,
        analyzer: ConcreteAnalyzer,
        sample_match_data: MatchData,
        sample_context: AnalysisContext
    ):
        """测试 build_prompt 追加领域数据到用户消息"""
        messages = analyzer.build_prompt(sample_match_data, sample_context)
        
        # 检查所有 user 消息中是否包含格式化后的领域数据
        user_contents = [m["content"] for m in messages if m["role"] == "user"]
        combined_content = "\n".join(user_contents)
        assert "## 测试数据" in combined_content
        assert "测试项 1" in combined_content
        assert "测试项 2" in combined_content
    
    # ==================== _format_domain_data() 抽象方法测试 ====================
    
    def test_format_domain_data_is_abstract(self):
        """测试 _format_domain_data 是抽象方法"""
        # 尝试创建不实现 _format_domain_data 的子类应该失败
        with pytest.raises(TypeError):
            class IncompleteAnalyzer(BaseLLMReviewAnalyzer):
                @property
                def phase_name(self) -> str:
                    return "incomplete"
                
                # 故意不实现 _format_domain_data
            
            IncompleteAnalyzer(Mock(spec=ILLMClient))
    
    def test_format_domain_data_must_be_implemented(self):
        """测试子类必须实现 _format_domain_data"""
        class CompleteAnalyzer(BaseLLMReviewAnalyzer):
            @property
            def phase_name(self) -> str:
                return "complete"
            
            def _format_domain_data(self, match_data: MatchData) -> str:
                return "完整实现"
        
        # 应该可以成功创建实例
        analyzer = CompleteAnalyzer(Mock(spec=ILLMClient))
        assert analyzer._format_domain_data(MatchData(
            match_id="test",
            duration=0,
            radiant_win=True,
            radiant_score=0,
            dire_score=0,
            game_mode=22,
            players=[],
            picks_bans=[],
            lane_data=None,
            teamfight_data=None,
            economy_data=None,
            raw_metadata={}
        )) == "完整实现"
