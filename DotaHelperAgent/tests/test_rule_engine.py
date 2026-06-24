"""
规则推理引擎单元测试

测试覆盖：
- 规则加载和初始化
- 条件评估逻辑
- 规则匹配结果
- 推荐建议生成
- 自定义规则添加/移除
"""

import pytest
from core.decision.rule_engine import RuleEngine, Rule, RulePriority, RuleResult


class TestRuleEngine:
    """规则引擎测试类"""
    
    def test_initialization(self):
        """测试规则引擎初始化"""
        engine = RuleEngine()
        assert engine is not None
        assert len(engine.rules) > 0
    
    def test_load_default_rules(self):
        """测试默认规则加载"""
        engine = RuleEngine()
        
        # 验证关键规则存在
        rule_ids = [rule.id for rule in engine.rules]
        assert "health_warning" in rule_ids
        assert "mana_warning" in rule_ids
        assert "stack_neutral" in rule_ids
        assert "rune_spawn" in rule_ids
        assert "roshan_respawn" in rule_ids
    
    def test_evaluate_health_warning(self):
        """测试血量预警规则"""
        engine = RuleEngine()
        
        # 低血量场景
        game_state = {
            "health": 200,
            "max_health": 1000,
            "mana": 500,
            "max_mana": 1000,
            "game_time": 300,
            "is_alive": True
        }
        
        results = engine.evaluate(game_state)
        
        # 应该触发血量预警
        health_warning_found = any(r.rule.id == "health_warning" for r in results)
        assert health_warning_found, "低血量应该触发血量预警规则"
    
    def test_evaluate_mana_warning(self):
        """测试魔法预警规则"""
        engine = RuleEngine()
        
        # 低魔法场景
        game_state = {
            "health": 800,
            "max_health": 1000,
            "mana": 100,
            "max_mana": 1000,
            "game_time": 300,
            "is_alive": True
        }
        
        results = engine.evaluate(game_state)
        
        # 应该触发魔法预警
        mana_warning_found = any(r.rule.id == "mana_warning" for r in results)
        assert mana_warning_found, "低魔法应该触发魔法预警规则"
    
    def test_evaluate_stack_neutral(self):
        """测试堆野规则"""
        engine = RuleEngine()
        
        # 堆野时机（第53-55秒）
        game_state = {
            "health": 800,
            "max_health": 1000,
            "mana": 500,
            "max_mana": 1000,
            "game_time": 53,  # 第53秒
            "is_alive": True
        }
        
        results = engine.evaluate(game_state)
        
        # 应该触发堆野规则
        stack_found = any(r.rule.id == "stack_neutral" for r in results)
        assert stack_found, "第53秒应该触发堆野规则"
    
    def test_evaluate_rune_spawn(self):
        """测试符文刷新规则"""
        engine = RuleEngine()
        
        # 符文刷新时机（每3分钟）
        game_state = {
            "health": 800,
            "max_health": 1000,
            "mana": 500,
            "max_mana": 1000,
            "game_time": 180,  # 第3分钟
            "is_alive": True
        }
        
        results = engine.evaluate(game_state)
        
        # 应该触发符文刷新规则
        rune_found = any(r.rule.id == "rune_spawn" for r in results)
        assert rune_found, "第180秒应该触发符文刷新规则"
    
    def test_evaluate_roshan_respawn(self):
        """测试肉山刷新规则"""
        engine = RuleEngine()
        
        # 肉山刷新时机（8分钟）
        game_state = {
            "health": 800,
            "max_health": 1000,
            "mana": 500,
            "max_mana": 1000,
            "game_time": 480,  # 第8分钟
            "is_alive": True
        }
        
        results = engine.evaluate(game_state)
        
        # 应该触发肉山刷新规则
        roshan_found = any(r.rule.id == "roshan_respawn" for r in results)
        assert roshan_found, "第480秒应该触发肉山刷新规则"
    
    def test_evaluate_death_warning(self):
        """测试死亡预警规则"""
        engine = RuleEngine()
        
        # 极低血量场景
        game_state = {
            "health": 50,
            "max_health": 1000,
            "mana": 500,
            "max_mana": 1000,
            "game_time": 300,
            "is_alive": True
        }
        
        results = engine.evaluate(game_state)
        
        # 应该触发死亡预警
        death_warning_found = any(r.rule.id == "death_warning" for r in results)
        assert death_warning_found, "极低血量应该触发死亡预警规则"
    
    def test_evaluate_no_match(self):
        """测试无规则匹配场景"""
        engine = RuleEngine()
        
        # 正常状态
        game_state = {
            "health": 800,
            "max_health": 1000,
            "mana": 500,
            "max_mana": 1000,
            "game_time": 100,  # 非特殊时机
            "is_alive": True
        }
        
        results = engine.evaluate(game_state)
        
        # 不应该触发高优先级规则
        high_priority_rules = [r for r in results if r.rule.priority in [RulePriority.HIGH, RulePriority.CRITICAL]]
        assert len(high_priority_rules) == 0, "正常状态不应该触发高优先级规则"
    
    def test_get_recommendations(self):
        """测试获取推荐建议"""
        engine = RuleEngine()
        
        game_state = {
            "health": 200,
            "max_health": 1000,
            "mana": 500,
            "max_mana": 1000,
            "game_time": 300,
            "is_alive": True
        }
        
        recommendations = engine.get_recommendations(game_state)
        
        # 应该有推荐
        assert len(recommendations) > 0
        
        # 验证推荐格式
        rec = recommendations[0]
        assert "type" in rec
        assert "rule_id" in rec
        assert "rule_name" in rec
        assert "priority" in rec
        assert "recommendation" in rec
        assert "confidence" in rec
        assert rec["type"] == "rule"
    
    def test_add_custom_rule(self):
        """测试添加自定义规则"""
        engine = RuleEngine()
        initial_count = len(engine.rules)
        
        custom_rule = Rule(
            id="custom_rule",
            name="自定义规则",
            description="测试自定义规则",
            priority=RulePriority.MEDIUM,
            condition="game_time > 1000",
            recommendation="这是自定义推荐",
            confidence=0.7
        )
        
        engine.add_rule(custom_rule)
        
        assert len(engine.rules) == initial_count + 1
        assert any(r.id == "custom_rule" for r in engine.rules)
    
    def test_remove_rule(self):
        """测试移除规则"""
        engine = RuleEngine()
        initial_count = len(engine.rules)
        
        # 移除存在的规则
        success = engine.remove_rule("health_warning")
        assert success, "应该成功移除存在的规则"
        assert len(engine.rules) == initial_count - 1
        assert not any(r.id == "health_warning" for r in engine.rules)
        
        # 移除不存在的规则
        success = engine.remove_rule("non_existent_rule")
        assert not success, "移除不存在的规则应该返回 False"
    
    def test_get_all_rules(self):
        """测试获取所有规则"""
        engine = RuleEngine()
        
        rules = engine.get_all_rules()
        
        assert len(rules) == len(engine.rules)
        assert all(isinstance(rule, dict) for rule in rules)
        assert all("id" in rule for rule in rules)
        assert all("name" in rule for rule in rules)
    
    def test_rule_priority_sorting(self):
        """测试规则按优先级排序"""
        engine = RuleEngine()
        
        # 触发多个规则的场景
        game_state = {
            "health": 50,  # 触发死亡预警（CRITICAL）
            "max_health": 1000,
            "mana": 50,  # 触发魔法预警（MEDIUM）
            "max_mana": 1000,
            "game_time": 300,
            "is_alive": True
        }
        
        results = engine.evaluate(game_state)
        
        # 验证按优先级排序
        if len(results) >= 2:
            priorities = [r.rule.priority.value for r in results]
            assert priorities == sorted(priorities, reverse=True), "结果应该按优先级降序排列"
    
    def test_evaluate_with_missing_fields(self):
        """测试缺失字段的容错性"""
        engine = RuleEngine()
        
        # 缺少某些字段
        game_state = {
            "health": 200,
            "max_health": 1000
            # 缺少 mana, game_time 等
        }
        
        # 不应该抛出异常
        results = engine.evaluate(game_state)
        assert isinstance(results, list)
    
    def test_evaluate_with_zero_max_values(self):
        """测试最大值为0的容错性"""
        engine = RuleEngine()
        
        game_state = {
            "health": 200,
            "max_health": 0,  # 最大值为0
            "mana": 100,
            "max_mana": 0,
            "game_time": 300,
            "is_alive": True
        }
        
        # 不应该抛出除零异常
        results = engine.evaluate(game_state)
        assert isinstance(results, list)


class TestRule:
    """规则对象测试类"""
    
    def test_rule_creation(self):
        """测试规则创建"""
        rule = Rule(
            id="test_rule",
            name="测试规则",
            description="这是一个测试规则",
            priority=RulePriority.MEDIUM,
            condition="game_time > 100",
            recommendation="测试推荐",
            confidence=0.8
        )
        
        assert rule.id == "test_rule"
        assert rule.name == "测试规则"
        assert rule.priority == RulePriority.MEDIUM
        assert rule.confidence == 0.8
    
    def test_rule_to_dict(self):
        """测试规则转换为字典"""
        rule = Rule(
            id="test_rule",
            name="测试规则",
            description="这是一个测试规则",
            priority=RulePriority.HIGH,
            condition="health < 100",
            recommendation="快跑",
            confidence=0.9
        )
        
        rule_dict = rule.to_dict()
        
        assert rule_dict["id"] == "test_rule"
        assert rule_dict["name"] == "测试规则"
        assert rule_dict["priority"] == 3  # HIGH = 3
        assert rule_dict["confidence"] == 0.9


class TestRuleResult:
    """规则结果测试类"""
    
    def test_rule_result_creation(self):
        """测试规则结果创建"""
        rule = Rule(
            id="test_rule",
            name="测试规则",
            description="测试",
            priority=RulePriority.MEDIUM,
            condition="true",
            recommendation="推荐",
            confidence=0.8
        )
        
        result = RuleResult(
            rule=rule,
            matched=True,
            context={"game_time": 100}
        )
        
        assert result.matched is True
        assert result.rule == rule
    
    def test_rule_result_to_dict(self):
        """测试规则结果转换为字典"""
        rule = Rule(
            id="test_rule",
            name="测试规则",
            description="测试",
            priority=RulePriority.LOW,
            condition="true",
            recommendation="推荐",
            confidence=0.7
        )
        
        result = RuleResult(
            rule=rule,
            matched=True,
            context={"game_time": 100}
        )
        
        result_dict = result.to_dict()
        
        assert "rule" in result_dict
        assert "matched" in result_dict
        assert "context" in result_dict
        assert result_dict["matched"] is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
