"""测试日志重构后的功能"""

import sys
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from utils.log_config import setup_logging, get_logger
from core.agent import DotaHelperAgent

def test_logger_import():
    """测试 logger 导入是否正常"""
    print("测试 1: 导入 logger...")
    try:
        from core.agent_controller import logger as controller_logger
        from core.agent import logger as agent_logger
        print("✓ logger 导入成功")
        return True
    except Exception as e:
        print(f"✗ logger 导入失败: {e}")
        return False

def test_agent_initialization():
    """测试 Agent 初始化是否正常"""
    print("\n测试 2: Agent 初始化...")
    try:
        agent = DotaHelperAgent(
            enable_llm=False,
            enable_memory=False
        )
        print("✓ Agent 初始化成功")
        print(f"  - LLM 启用: {agent.llm_enabled}")
        print(f"  - Memory 启用: {agent.enable_memory}")
        return True
    except Exception as e:
        print(f"✗ Agent 初始化失败: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_agent_recommend_heroes():
    """测试英雄推荐功能"""
    print("\n测试 3: 英雄推荐功能...")
    try:
        agent = DotaHelperAgent(
            enable_llm=False,
            enable_memory=False
        )
        result = agent.recommend_heroes(
            our_heroes=["axe"],
            enemy_heroes=["crystal_maiden"],
            top_n=3
        )
        print("✓ 英雄推荐成功")
        print(f"  - 来源: {result.get('source')}")
        print(f"  - 推荐数量: {len(result.get('recommendations', []))}")
        return True
    except Exception as e:
        print(f"✗ 英雄推荐失败: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_memory_operations():
    """测试记忆操作"""
    print("\n测试 4: 记忆操作...")
    try:
        agent = DotaHelperAgent(
            enable_llm=False,
            enable_memory=True,
            memory_dir="test_memory"
        )
        
        # 测试保存查询结果
        agent.save_query_result(
            query="test query",
            result={"test": "data"},
            tags=["test"]
        )
        print("✓ 保存查询结果成功")
        
        # 测试获取相关上下文
        context = agent.get_relevant_context("test query")
        print(f"✓ 获取记忆上下文成功 - 返回: {len(context)} 条")
        
        # 测试保存经验
        agent.save_experience(
            event_type="test",
            content="test content",
            context={"test": "context"}
        )
        print("✓ 保存经验成功")
        
        # 清空记忆
        agent.clear_memory()
        print("✓ 清空记忆成功")
        
        return True
    except Exception as e:
        print(f"✗ 记忆操作失败: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """运行所有测试"""
    print("="*60)
    print("日志重构测试")
    print("="*60)
    
    # 设置日志
    setup_logging(log_level="DEBUG", console_output=True)
    
    results = []
    results.append(("Logger 导入", test_logger_import()))
    results.append(("Agent 初始化", test_agent_initialization()))
    results.append(("英雄推荐", test_agent_recommend_heroes()))
    results.append(("记忆操作", test_memory_operations()))
    
    print("\n" + "="*60)
    print("测试结果汇总")
    print("="*60)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for name, result in results:
        status = "✓ 通过" if result else "✗ 失败"
        print(f"{name}: {status}")
    
    print(f"\n总计: {passed}/{total} 通过")
    
    if passed == total:
        print("\n✓ 所有测试通过！")
        return 0
    else:
        print(f"\n✗ {total - passed} 个测试失败")
        return 1

if __name__ == "__main__":
    sys.exit(main())
