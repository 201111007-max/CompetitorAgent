"""测试比赛数据获取"""
import sys
import json
sys.path.insert(0, 'DotaHelperAgent')

from utils.api_client import OpenDotaClient

client = OpenDotaClient()
match_data = client._make_request('/matches/8893253595')

if match_data:
    print("=" * 80)
    print("比赛基本信息")
    print("=" * 80)
    
    basic_fields = [
        ('match_id', '比赛 ID'),
        ('duration', '比赛时长（秒）'),
        ('radiant_win', '天辉是否胜利'),
        ('game_mode', '游戏模式'),
        ('lobby_type', '大厅类型'),
        ('start_time', '开始时间（Unix 时间戳）'),
        ('radiant_score', '天辉得分'),
        ('dire_score', '夜魇得分'),
        ('radiant_team', '天辉队伍信息'),
        ('dire_team', '夜魇队伍信息'),
        ('cluster', '服务器集群'),
        ('first_blood_time', '一血时间（秒）'),
        ('tower_status_radiant', '天辉塔状态'),
        ('tower_status_dire', '夜魇塔状态'),
        ('barracks_status_radiant', '天辉兵营状态'),
        ('barracks_status_dire', '夜魇兵营状态'),
        ('human_players', '人类玩家数量'),
        ('leagueid', '联赛 ID'),
        ('positive_votes', '正面投票数'),
        ('negative_votes', '负面投票数'),
        ('radiant_team_id', '天辉队伍 ID'),
        ('dire_team_id', '夜魇队伍 ID'),
    ]
    
    for field, desc in basic_fields:
        value = match_data.get(field)
        if value is not None:
            print(f"{desc}: {value}")
    
    print("\n" + "=" * 80)
    print("所有顶级字段列表")
    print("=" * 80)
    all_keys = list(match_data.keys())
    for i, key in enumerate(all_keys, 1):
        value = match_data[key]
        value_type = type(value).__name__
        if isinstance(value, list):
            print(f"{i}. {key} ({value_type}, 长度: {len(value)})")
        elif isinstance(value, dict):
            print(f"{i}. {key} ({value_type}, 键数: {len(value)})")
        else:
            print(f"{i}. {key} ({value_type}): {value}")
    
    print("\n" + "=" * 80)
    print("玩家数据字段（以第一个玩家为例）")
    print("=" * 80)
    if match_data.get('players'):
        player = match_data['players'][0]
        player_fields = [
            ('account_id', 'Steam 32位 ID'),
            ('player_slot', '玩家位置（0-4 天辉，128-132 夜魇）'),
            ('hero_id', '英雄 ID'),
            ('hero_name', '英雄名称'),
            ('kills', '击杀数'),
            ('deaths', '死亡数'),
            ('assists', '助攻数'),
            ('last_hits', '正补数'),
            ('denies', '反补数'),
            ('gold_per_min', '每分钟金钱'),
            ('xp_per_min', '每分钟经验'),
            ('hero_damage', '英雄伤害'),
            ('tower_damage', '塔伤害'),
            ('hero_healing', '英雄治疗'),
            ('level', '等级'),
            ('gold', '当前金钱'),
            ('gold_spent', '花费金钱'),
            ('gold_t', '每分钟金钱变化'),
            ('xp_t', '每分钟经验变化'),
            ('kills_log', '击杀日志'),
            ('buyback_log', '买活日志'),
            ('item_0', '物品栏 0'),
            ('item_1', '物品栏 1'),
            ('item_2', '物品栏 2'),
            ('item_3', '物品栏 3'),
            ('item_4', '物品栏 4'),
            ('item_5', '物品栏 5'),
            ('backpack_0', '背包 0'),
            ('backpack_1', '背包 1'),
            ('backpack_2', '背包 2'),
            ('item_neutral', '中立物品'),
            ('kills', '击杀数'),
            ('deaths', '死亡数'),
            ('assists', '助攻数'),
            ('killed', '击杀的英雄'),
            ('killed_by', '被击杀的英雄'),
            ('damage', '伤害统计'),
            ('damage_taken', '受到伤害统计'),
            ('damage_inflictor', '伤害来源'),
            ('runes', '符文使用'),
            ('runes_log', '符文使用日志'),
            ('teamfight_participation', '团战参与率'),
            ('towers', '塔攻击统计'),
            ('courier_kills', '信使击杀'),
            ('ward', '守卫统计'),
            ('observer_uses', '侦查守卫使用次数'),
            ('sentry_uses', '岗哨守卫使用次数'),
            ('actions_per_min', '每分钟操作数'),
            ('purchase', '购买物品统计'),
            ('purchase_log', '购买日志'),
            ('lane', '对线位置'),
            ('lane_role', '对线角色'),
            ('is_roaming', '是否游走'),
            ('obs', '侦查守卫放置'),
            ('sen', '岗哨守卫放置'),
            ('obs_left_log', '侦查守卫残留日志'),
            ('sen_left_log', '岗哨守卫残留日志'),
            ('actions', '操作统计'),
            ('lane_efficiency', '对线效率'),
            ('lane_efficiency_pct', '对线效率百分比'),
            ('net_worth', '净资产'),
            ('stuns', '眩晕时间'),
            ('hero_hits', '英雄攻击次数'),
            ('camps_stacked', '堆野数量'),
            ('rune_pickups', '符文拾取'),
            ('pings', '标记次数'),
            ('stuns_log', '眩晕日志'),
            ('times', '时间点'),
            ('teamfight_participation', '团战参与率'),
            ('roshans_killed', '肉山击杀数'),
            ('observers_placed', '侦查守卫放置数'),
            ('sentients_placed', '岗哨守卫放置数'),
        ]
        
        for field, desc in player_fields:
            if field in player:
                value = player[field]
                if isinstance(value, list):
                    print(f"{desc} ({field}): 列表, 长度 {len(value)}")
                elif isinstance(value, dict):
                    print(f"{desc} ({field}): 字典, 键数 {len(value)}")
                else:
                    print(f"{desc} ({field}): {value}")
    
    print("\n" + "=" * 80)
    print("其他重要数据")
    print("=" * 80)
    
    if 'teamfights' in match_data:
        print(f"团战数据 (teamfights): {len(match_data['teamfights'])} 次团战")
    
    if 'radiant_gold_adv' in match_data:
        print(f"天辉金钱优势曲线 (radiant_gold_adv): {len(match_data['radiant_gold_adv'])} 个时间点")
    
    if 'radiant_xp_adv' in match_data:
        print(f"天辉经验优势曲线 (radiant_xp_adv): {len(match_data['radiant_xp_adv'])} 个时间点")
    
    if 'picks_bans' in match_data:
        print(f"Ban/Pick 数据 (picks_bans): {len(match_data['picks_bans'])} 次选择")
    
    if 'chat' in match_data:
        print(f"聊天消息 (chat): {len(match_data['chat'])} 条消息")
    
    print("\n" + "=" * 80)
    print("数据保存")
    print("=" * 80)
    with open('match_8893253595.json', 'w', encoding='utf-8') as f:
        json.dump(match_data, f, indent=2, ensure_ascii=False)
    print("完整数据已保存到 match_8893253595.json")
else:
    print("获取比赛数据失败")
