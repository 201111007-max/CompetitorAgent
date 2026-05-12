"""测试 trace_1feb1a30e8474962 的 JSON 输出问题修复"""

import sys
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from web.app import _format_answer_for_stream
import json

# 测试数据：用户提供的原始数据
test_data_list = [
    {'hero_id': 71, 'hero_name': '裂魂人', 'score': 11.82, 'reasons': ['对 撼地者: 胜率 61.8%'], 'matchup_details': [{'enemy_hero': '撼地者', 'advantage': 11.818181818181817, 'reasons': ['胜率 61.8%']}]},
    {'hero_id': 53, 'hero_name': '自然先知', 'score': 7.0, 'reasons': ['对 撼地者: 胜率 57.0%'], 'matchup_details': [{'enemy_hero': '撼地者', 'advantage': 7.0048309178743935, 'reasons': ['胜率 57.0%']}]},
    {'hero_id': 48, 'hero_name': '露娜', 'score': 4.95, 'reasons': ['对 撼地者: 胜率 55.0%'], 'matchup_details': [{'enemy_hero': '撼地者', 'advantage': 4.95495495495496, 'reasons': ['胜率 55.0%']}]}
]

def test_direct_list_formatting():
    """测试直接格式化列表"""
    print("=" * 60)
    print("测试 1: 直接格式化列表")
    print("=" * 60)
    
    result = _format_answer_for_stream(test_data_list)
    print(f"\n格式化结果:\n{result}\n")
    
    # 验证不包含 JSON 格式
    assert '[' not in result or '推荐结果' in result, "结果不应该包含原始 JSON 格式"
    assert '裂魂人' in result, "结果应该包含中文英雄名"
    print("✓ 测试通过\n")

def test_merged_result_formatting():
    """测试合并后的结果格式化（模拟 _merge_sub_goal_results 的输出）"""
    print("=" * 60)
    print("测试 2: 合并后的结果格式化（修复前的问题场景）")
    print("=" * 60)
    
    # 模拟修复前的数据结构（answer 是包含 message 的字典）
    merged_data_before_fix = {
        "main_goal": "分析克制英雄",
        "sub_goals_summary": {"total": 1, "completed": 1, "failed": 0},
        "sub_goals_results": [{
            "sub_goal_id": "goal_1",
            "description": "分析克制关系",
            "result": test_data_list
        }],
        "answer": test_data_list  # 修复后：answer 直接是列表
    }
    
    result = _format_answer_for_stream(merged_data_before_fix)
    print(f"\n格式化结果:\n{result}\n")
    
    # 验证不包含 JSON 格式
    assert 'hero_id' not in result, "结果不应该包含 JSON 字段名"
    assert '裂魂人' in result, "结果应该包含中文英雄名"
    print("✓ 测试通过\n")

def test_message_field_with_json_string():
    """测试 message 字段包含 JSON 字符串的情况"""
    print("=" * 60)
    print("测试 3: message 字段包含 JSON 字符串")
    print("=" * 60)
    
    # 模拟修复前可能出现的情况（message 字段包含 JSON 字符串）
    merged_data_with_message = {
        "main_goal": "分析克制英雄",
        "sub_goals_summary": {"total": 1, "completed": 1, "failed": 0},
        "answer": {
            "message": json.dumps(test_data_list, ensure_ascii=False)
        }
    }
    
    result = _format_answer_for_stream(merged_data_with_message)
    print(f"\n格式化结果:\n{result}\n")
    
    # 验证不包含 JSON 格式
    assert 'hero_id' not in result, "结果不应该包含 JSON 字段名"
    assert '裂魂人' in result, "结果应该包含中文英雄名"
    print("✓ 测试通过\n")

def test_legacy_message_field():
    """测试传统的 message 字段（纯文本）"""
    print("=" * 60)
    print("测试 4: 传统 message 字段（纯文本）")
    print("=" * 60)
    
    merged_data = {
        "answer": {
            "message": "根据分析，推荐以下英雄：\n1. 裂魂人\n2. 自然先知"
        }
    }
    
    result = _format_answer_for_stream(merged_data)
    print(f"\n格式化结果:\n{result}\n")
    
    assert '裂魂人' in result, "结果应该包含英雄名"
    print("✓ 测试通过\n")

if __name__ == "__main__":
    print("\n开始测试 JSON 输出问题修复\n")
    
    try:
        test_direct_list_formatting()
        test_merged_result_formatting()
        test_message_field_with_json_string()
        test_legacy_message_field()
        
        print("=" * 60)
        print("✓ 所有测试通过！")
        print("=" * 60)
        print("\n修复说明：")
        print("1. 在 _merge_sub_goal_results 中，当结果是列表时，直接作为 answer")
        print("2. 在 _format_answer_for_stream 中，增强对 message 字段的处理")
        print("3. 尝试解析 message 中的 JSON 字符串并递归格式化")
        print("=" * 60)
        
    except AssertionError as e:
        print(f"\n✗ 测试失败: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n✗ 测试异常: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
