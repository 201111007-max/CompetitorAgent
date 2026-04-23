"""分析器模块测试"""

import pytest
from unittest.mock import Mock, patch, MagicMock
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from analyzers.hero_analyzer import HeroAnalyzer
from analyzers.item_recommender import ItemRecommender
from analyzers.skill_builder import SkillBuilder
from core.config import MatchupConfig
from strategies.score_strategies import WinRateStrategy, PopularityStrategy


class TestHeroAnalyzer:
    """测试英雄分析器"""
    
    @pytest.fixture
    def mock_client(self):
        """模拟 API 客户端"""
        client = Mock()
        client.get_heroes.return_value = [
            {"id": 1, "name": "npc_dota_hero_antimage", "localized_name": "Anti-Mage"},
            {"id": 2, "name": "npc_dota_hero_axe", "localized_name": "Axe"},
            {"id": 5, "name": "npc_dota_hero_crystal_maiden", "localized_name": "Crystal Maiden"},
            {"id": 10, "name": "npc_dota_hero_pudge", "localized_name": "Pudge"},
        ]
        client.get_hero_matchups.return_value = [
            {"hero_id": 2, "games_played": 150, "wins": 80},
            {"hero_id": 5, "games_played": 200, "wins": 90},
        ]
        client.hero_id_to_name.side_effect = lambda x: {
            1: "Anti-Mage", 2: "Axe", 5: "Crystal Maiden", 10: "Pudge"
        }.get(x, "Unknown")
        client.hero_name_to_id.side_effect = lambda x: {
            "Anti-Mage": 1, "Axe": 2, "Crystal Maiden": 5, "Pudge": 10
        }.get(x, None)
        return client
    
    @pytest.fixture
    def analyzer(self, mock_client):
        """创建分析器实例"""
        return HeroAnalyzer(mock_client)
    
    def test_init(self, mock_client):
        """测试初始化"""
        analyzer = HeroAnalyzer(mock_client)
        
        assert analyzer.client == mock_client
        assert isinstance(analyzer.config, MatchupConfig)
        assert len(analyzer._strategies) == 1
        assert isinstance(analyzer._strategies[0], WinRateStrategy)
    
    def test_add_strategy(self, analyzer):
        """测试添加策略"""
        strategy = PopularityStrategy()
        analyzer.add_strategy(strategy)
        
        assert len(analyzer._strategies) == 2
        assert strategy in analyzer._strategies
    
    def test_analyze_single_matchup(self, analyzer, mock_client):
        """测试单个克制关系分析"""
        score, reasons = analyzer._analyze_single_matchup(1, 2)
        
        assert isinstance(score, float)
        assert isinstance(reasons, list)
    
    def test_calculate_synergy(self, analyzer):
        """测试配合计算"""
        score, reasons = analyzer._calculate_synergy(1, 2)
        
        assert isinstance(score, float)
        assert isinstance(reasons, list)
    
    def test_evaluate_hero(self, analyzer):
        """测试英雄评估"""
        hero = {"id": 1, "localized_name": "Anti-Mage"}
        our_hero_ids = [2]
        enemy_hero_ids = [5]
        
        result = analyzer._evaluate_hero(hero, our_hero_ids, enemy_hero_ids)
        
        if result is not None:
            assert "score" in result
            assert "reasons" in result
    
    def test_evaluate_hero_skip_selected(self, analyzer):
        """测试跳过已选英雄"""
        hero = {"id": 1, "localized_name": "Anti-Mage"}
        our_hero_ids = [1]
        enemy_hero_ids = [5]
        
        result = analyzer._evaluate_hero(hero, our_hero_ids, enemy_hero_ids)
        
        assert result is None
    
    def test_analyze_matchups(self, analyzer):
        """测试阵容分析"""
        result = analyzer.analyze_matchups(
            our_heroes=["Anti-Mage"],
            enemy_heroes=["Pudge"],
            top_n=3
        )
        
        assert isinstance(result, list)
        assert len(result) <= 3
    
    def test_analyze_matchups_empty(self, mock_client):
        """测试空阵容分析"""
        mock_client.get_heroes.return_value = []
        analyzer = HeroAnalyzer(mock_client)
        
        result = analyzer.analyze_matchups(
            our_heroes=[],
            enemy_heroes=[],
            top_n=3
        )
        
        assert result == []
    
    def test_get_counter_heroes(self, analyzer):
        """测试获取克制英雄"""
        result = analyzer.get_counter_heroes("Pudge", top_n=5)
        
        assert isinstance(result, list)
    
    def test_analyze_team_composition(self, analyzer):
        """测试阵容分析"""
        result = analyzer.analyze_team_composition(
            our_heroes=["Anti-Mage", "Crystal Maiden"],
            enemy_heroes=["Pudge", "Axe"]
        )
        
        assert isinstance(result, dict)


class TestItemRecommender:
    """测试物品推荐器"""
    
    @pytest.fixture
    def mock_client(self):
        """模拟 API 客户端"""
        client = Mock()
        client.hero_name_to_id.return_value = 1
        client.get_hero_item_popularity.return_value = {
            "start_game_items": {
                1: 500,
                2: 450,
            },
            "early_game_items": {
                3: 800,
                4: 600,
            },
            "mid_game_items": {
                5: 1250,
                6: 980,
            },
            "late_game_items": {
                7: 750,
                8: 600,
            }
        }
        return client
    
    @pytest.fixture
    def recommender(self, mock_client):
        """创建推荐器实例"""
        return ItemRecommender(mock_client, llm_enabled=False)
    
    def test_init(self, mock_client):
        """测试初始化"""
        recommender = ItemRecommender(mock_client, llm_enabled=False)
        
        assert recommender.client == mock_client
    
    def test_recommend_items_all_stages(self, recommender):
        """测试全阶段物品推荐"""
        result = recommender.recommend_items(
            hero_name="Anti-Mage",
            game_stage="all"
        )
        
        assert isinstance(result, dict)
    
    def test_recommend_items_early(self, recommender):
        """测试前期物品推荐"""
        result = recommender.recommend_items(
            hero_name="Anti-Mage",
            game_stage="early"
        )
        
        assert isinstance(result, dict)
    
    def test_recommend_items_invalid_hero(self, mock_client):
        """测试无效英雄"""
        mock_client.hero_name_to_id.return_value = None
        recommender = ItemRecommender(mock_client, llm_enabled=False)
        
        result = recommender.recommend_items(
            hero_name="InvalidHero"
        )
        
        assert isinstance(result, dict)
    
    def test_parse_items(self, recommender):
        """测试物品解析"""
        items_dict = {
            1: 500,
            2: 450,
            3: 400,
        }
        
        result = recommender._parse_items(items_dict, top_n=2)
        
        assert isinstance(result, list)
        assert len(result) == 2
        assert result[0]["popularity"] == 500


class TestSkillBuilder:
    """测试技能加点构建器"""
    
    @pytest.fixture
    def mock_client(self):
        """模拟 API 客户端"""
        client = Mock()
        client.hero_name_to_id.return_value = 1
        client.get_hero_stats.return_value = [
            {
                "id": 1,
                "localized_name": "Anti-Mage",
                "attack_type": "Melee",
                "primary_attr": "agi",
                "roles": ["Carry", "Escape", "Nuker"]
            }
        ]
        return client
    
    @pytest.fixture
    def skill_builder(self, mock_client):
        """创建技能构建器实例"""
        return SkillBuilder(mock_client, llm_enabled=False)
    
    def test_init(self, mock_client):
        """测试初始化"""
        skill_builder = SkillBuilder(mock_client, llm_enabled=False)
        
        assert skill_builder.client == mock_client
    
    def test_recommend_skill_build(self, skill_builder):
        """测试技能加点推荐"""
        result = skill_builder.recommend_skill_build(
            hero_name="Anti-Mage",
            role="core"
        )
        
        assert isinstance(result, dict)
    
    def test_recommend_skill_invalid_hero(self, mock_client):
        """测试无效英雄"""
        mock_client.hero_name_to_id.return_value = None
        skill_builder = SkillBuilder(mock_client, llm_enabled=False)
        
        result = skill_builder.recommend_skill_build(
            hero_name="InvalidHero"
        )
        
        assert isinstance(result, dict)


class TestAnalyzerIntegration:
    """分析器集成测试"""
    
    @patch('analyzers.hero_analyzer.OpenDotaClient')
    def test_full_analysis_workflow(self, mock_client_class):
        """测试完整分析工作流程"""
        mock_client = Mock()
        mock_client.get_heroes.return_value = [
            {"id": 1, "localized_name": "Anti-Mage"},
            {"id": 2, "localized_name": "Axe"},
        ]
        mock_client.get_hero_matchups.return_value = [
            {"hero_id": 2, "games_played": 150, "wins": 80}
        ]
        mock_client.hero_id_to_name.side_effect = lambda x: {
            1: "Anti-Mage", 2: "Axe"
        }.get(x, "Unknown")
        mock_client.hero_name_to_id.side_effect = lambda x: {
            "Anti-Mage": 1, "Axe": 2
        }.get(x, None)
        mock_client_class.return_value = mock_client
        
        analyzer = HeroAnalyzer(mock_client)
        
        result = analyzer.analyze_matchups(
            our_heroes=["Anti-Mage"],
            enemy_heroes=["Axe"],
            top_n=1
        )
        
        assert isinstance(result, list)
