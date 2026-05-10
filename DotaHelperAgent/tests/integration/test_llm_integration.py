"""测试 LLM 集成功能 - 集成测试

测试 LLM 与 DotaHelperAgent 的集成功能
"""

import sys
import os

# 添加项目路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from core.config import AgentConfig, LLMConfig
from core.agent import DotaHelperAgent


def test_llm_integration():
    """测试 LLM 集成功能"""
    print("="*70)
    print("测试 LLM 集成功能")
    print("="*70)

    # 配置 LLM
    llm_config = LLMConfig(
        enabled=True,
        base_url="http://127.0.0.1:1234/v1",
        model="qwen3.5-9b",
        temperature=0.7,
        max_tokens=512,
        timeout=30,
    )

    config = AgentConfig(llm=llm_config)

    print("\n1. 创建 Agent（启用 LLM）...")
    agent = DotaHelperAgent(config=config)

    print(f"\n2. LLM 状态: {'已启用' if agent.llm_enabled else '未启用'}")

    if agent.llm_enabled:
        print("\n3. 测试英雄推荐...")
        result = agent.recommend_heroes(
            our_heroes=[],
            enemy_heroes=["Pudge", "Phantom Assassin"],
            top_n=2
        )
        
        print(f"\n推荐来源: {result.get('source', 'unknown')}")
        print("\n推荐结果:")
        for rec in result.get('recommendations', []):
            print(f"  - {rec.get('hero_name', 'unknown')} (得分: {rec.get('score', 'N/A')})")
        
        print("\n4. 测试出装推荐...")
        item_result = agent.recommend_items(
            hero_name="anti-mage",
            game_stage="all"
        )
        print(f"  出装推荐: {item_result}")
        
        print("\n5. 测试技能加点推荐...")
        skill_result = agent.recommend_skills(
            hero_name="anti-mage",
            role="core"
        )
        print(f"  技能加点: {skill_result}")
        
        print("\n6. 测试 Memory 系统...")
        agent.save_experience(
            event_type="hero_recommendation",
            content="推荐了敌法师",
            context={"enemy_heroes": ["Pudge"]},
            sentiment="positive"
        )
        context = agent.get_relevant_context("敌法师", limit=3)
        print(f"  获取到 {len(context)} 条相关记忆")
        
        memory_stats = agent.get_memory_stats()
        print(f"  Memory 统计: {memory_stats}")
    else:
        print("\n[提示] LLM 未启用，跳过 LLM 测试")
        print("   请确保本地模型服务已启动: http://127.0.0.1:1234")
        print("\n   支持的本地模型服务:")
        print("   - LM Studio: 启动本地服务器，设置端口 1234")
        print("   - Ollama: ollama serve")
        print("   - vLLM: python -m vllm.entrypoints.openai.api_server")

    print("\n" + "="*70)
    print("测试完成!")
    print("="*70)


if __name__ == "__main__":
    try:
        test_llm_integration()
    except Exception as e:
        print(f"\n[错误] 测试失败: {e}")
        import traceback
        traceback.print_exc()
