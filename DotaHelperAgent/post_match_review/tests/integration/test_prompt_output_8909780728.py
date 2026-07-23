"""验证层 B 重构后的提示词构建输出格式

直接调用 PromptBuilder + DataFormatter，用真实比赛数据
验证 YAML 声明注入是否正确工作。
"""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from post_match_review.data_source.opendota_client import OpenDotaClient
from post_match_review.data_source.match_fetcher import MatchFetcher
from post_match_review.engines.prompt_builder import PromptBuilder
from post_match_review.engines.data_formatter import DataFormatter
from post_match_review.observability.logger import get_logger

logger = get_logger("test_prompt_output")


async def main() -> None:
    """用 match_id=8909780728 获取数据并验证提示词构建"""
    match_id = "8909780728"
    print(f"获取比赛数据: match_id={match_id}")

    # 1. 获取真实比赛数据
    client = OpenDotaClient(timeout=30.0, max_retries=3)
    fetcher = MatchFetcher(client=client)
    try:
        match_data = await fetcher.fetch_and_parse(match_id)
        print(f"✅ 数据获取成功! duration={match_data.duration}s, "
              f"players={len(match_data.players)}, "
              f"lane_data={match_data.lane_data is not None}, "
              f"teamfight_data={match_data.teamfight_data is not None}, "
              f"economy_data={match_data.economy_data is not None}")
    except Exception as e:
        print(f"❌ 数据获取失败: {e}")
        return
    finally:
        try:
            await client.aclose()
        except Exception:
            pass

    # 2. 构建 PromptBuilder
    builder = PromptBuilder()

    # 3. 测试各阶段的提示词构建
    phases = ["laning", "teamfight", "economy", "decisions", "vision"]

    for phase in phases:
        print(f"\n{'='*60}")
        print(f"阶段: {phase}")
        print(f"{'='*60}")

        messages = builder.build(match_data, phase=phase)

        for i, msg in enumerate(messages):
            role = msg["role"]
            content = msg["content"]
            print(f"\n--- Layer {i+1} ({role}) ---")
            # 截断输出
            if len(content) > 1500:
                print(content[:1500])
                print(f"\n... (截断，总长 {len(content)} 字符)")
            else:
                print(content)

    # 4. 验证关键点
    print(f"\n{'='*60}")
    print("验证结果")
    print(f"{'='*60}")

    # 验证 Laning 阶段的 YAML 声明注入
    laning_messages = builder.build(match_data, phase="laning")
    stable = laning_messages[0]["content"]
    context = laning_messages[1]["content"]
    volatile = laning_messages[2]["content"]

    checks = {
        "Laning Stable 层包含 analysis_framework": "对线期分析师" in stable,
        "Laning Stable 层包含 output_schema": "conclusions" in stable and "required" in stable,
        "Laning Context 层包含 DataFormatter 输出": "补刀" in context or "10分钟" in context,
        "Laning Volatile 层包含 formatted_data": "补刀" in volatile or "Juggernaut" in volatile or match_data.players[0].hero_name in volatile,
    }

    all_pass = True
    for check_name, result in checks.items():
        status = "✅" if result else "❌"
        print(f"  {status} {check_name}")
        if not result:
            all_pass = False

    # 验证 Economy 阶段 custom 格式跳过
    eco_messages = builder.build(match_data, phase="economy")
    eco_context = eco_messages[1]["content"]
    # economy 的 data_requirements 全部为 custom，DataFormatter 不应追加领域数据
    # 但 _format_domain_data() 会追加（因为 EconomyAnalyzer 保留了 Python 实现）
    has_base_info = "比赛基本信息" in eco_context
    checks_eco = {
        "Economy Context 层包含基础信息": has_base_info,
    }
    for check_name, result in checks_eco.items():
        status = "✅" if result else "❌"
        print(f"  {status} {check_name}")
        if not result:
            all_pass = False

    if all_pass:
        print("\n🎉 所有验证通过！层 B YAML 增强工作正常。")
    else:
        print("\n⚠️ 部分验证未通过，请检查输出。")


if __name__ == "__main__":
    asyncio.run(main())
