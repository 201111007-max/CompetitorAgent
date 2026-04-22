"""测试 LLM 集成功能"""

import sys
sys.path.insert(0, 'd:/trae_projects/first-agent')

from agents.DotaHelperAgent import (
    DotaHelperAgent,
    AgentConfig,
    LLMConfig,
)

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

print(f"\n2. LLM 状态: {'已启用' if agent.is_llm_enabled() else '未启用'}")

if agent.is_llm_enabled():
    print("\n3. 测试英雄推荐...")
    result = agent.recommend_heroes(
        our_heroes=[],
        enemy_heroes=["Pudge", "Phantom Assassin"],
        top_n=2
    )
    
    print("\n推荐结果:")
    for rec in result['recommendations']:
        print(f"  - {rec['hero_name']} (得分: {rec['score']})")
    
    print("\n4. 测试 LLM 解释推荐...")
    if result['recommendations']:
        rec = result['recommendations'][0]
        explanation = agent.explain_recommendation_with_llm(
            hero_name=rec['hero_name'],
            enemy_heroes=result['enemy_team'],
            win_rate=0.55,
            reasons=rec['reasons']
        )
        if explanation:
            print(f"\nAI 解释:\n{explanation[:200]}...")  # 只显示前200字符
        else:
            print("  (未获取到解释)")
    
    print("\n5. 测试阵容分析...")
    try:
        analysis = agent.analyze_composition_with_llm(
            our_heroes=["Anti-Mage", "Crystal Maiden"],
            enemy_heroes=result['enemy_team']
        )
        if analysis:
            print(f"\nAI 阵容分析:\n{analysis[:200]}...")  # 只显示前200字符
        else:
            print("  (未获取到分析)")
    except Exception as e:
        print(f"  阵容分析出错: {e}")
    
    print("\n6. 测试问答...")
    try:
        answer = agent.ask_llm("什么英雄最克制帕吉？请简要回答。")
        if answer:
            print(f"\nAI 回答:\n{answer[:200]}...")  # 只显示前200字符
        else:
            print("  (未获取到回答)")
    except Exception as e:
        print(f"  问答出错: {e}")
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
