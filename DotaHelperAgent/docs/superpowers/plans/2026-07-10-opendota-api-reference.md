# 二十一、OpenDota API 参考 — 详细设计

> 更新时间：2026-07-13
> 来源: ARCHITECTURE_ANALYSIS.md 第二十一章
> 官方文档: https://docs.opendota.com/

## 21.1 获取比赛 ID 的 API

**注意**: `account_id` 是 Steam 32位 ID（Steam32 ID），不是 Steam 64位 ID。

| API 端点 | 用途 | 返回内容 |
|---------|------|---------|
| `/players/{account_id}/matches` | 获取指定玩家的比赛历史 | 返回该玩家的所有比赛，每个比赛包含 `match_id` |
| `/proMatches` | 获取职业比赛列表 | 返回最近的职业比赛，包含 `match_id` |
| `/publicMatches` | 获取公开比赛列表 | 返回最近的公开比赛，包含 `match_id` |

**Steam ID 转换**:
- Steam 64位 ID: `76561198047544285`
- Steam 32位 ID: `87278757`（OpenDota API 使用此格式）
- 转换公式: `Steam32 = Steam64 - 76561197960265728`

## 21.2 获取比赛详情的 API

| API 端点 | 用途 | 返回内容 |
|---------|------|---------|
| `/matches/{match_id}` | 获取指定比赛的详细信息 | 返回完整比赛数据（需要已知 match_id） |

## 21.3 赛后复盘推荐调用流程

```
1. 获取玩家比赛列表（得到 match_id）
   GET /players/{account_id}/matches

2. 获取具体比赛的详细数据
   GET /matches/{match_id}
```

**示例请求**：
```
https://api.opendota.com/api/players/87278757/matches
```

返回的比赛对象包含：
- `match_id`: 比赛 ID
- `player_slot`: 玩家位置
- `radiant_win`: 是否胜利
- `duration`: 比赛时长
- `hero_id`: 使用的英雄
- `kills` / `deaths` / `assists`: KDA 数据
- `last_hits` / `denies`: 补刀/反补数据
- `gold_per_min` / `xp_per_min`: 每分钟金钱/经验
- `item_0` ~ `item_5`: 物品栏
- `picks_bans`: Ban/Pick 信息
- `teamfights`: 团战数据
- `radiant_gold_adv`: 经济优势曲线
- `radiant_xp_adv`: 经验优势曲线

## 21.4 项目已有 API 集成

当前项目 `utils/api_client.py` 已集成的 OpenDota API：
- `/heroes/{hero_id}/matchups` - 英雄克制查询（带缓存）

待新增：
- `/players/{account_id}/matches` - 玩家比赛历史
- `/matches/{match_id}` - 比赛详情
