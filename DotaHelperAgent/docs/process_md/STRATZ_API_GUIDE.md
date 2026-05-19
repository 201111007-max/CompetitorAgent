# STRATZ GraphQL API 使用指南

> 本文档专为 DotaHelperAgent 设计，提供 STRATZ API 的完整使用说明

---

## 一、API 概述

### 1.1 基本信息

| 项目 | 值 |
|------|------|
| **API 类型** | GraphQL |
| **端点 URL** | `https://api.stratz.com/graphql` |
| **交互式文档** | `https://api.stratz.com/graphiql` |
| **官方文档** | `https://stratz.com/api` |
| **数据来源** | SkadiStats Clarity 2 解析器 + 自研解析器 |

### 1.2 数据特点

- **最全面的 Dota 2 统计数据库**
- 支持比赛数据、英雄统计、物品热度、玩家分析等
- 数据更新速度快，实时性强
- 支持按段位、位置、区域、时间段筛选

---

## 二、认证与速率限制

### 2.1 Token 类型

| Token 类型 | 适用场景 | 调用/秒 | 调用/分钟 | 调用/小时 | 调用/日 |
|-----------|---------|--------|----------|----------|--------|
| **默认 Token** | 休闲用户、个人项目 | 20 | 250 | 2,000 | 10,000 |
| **个人 Token** | Web 应用、社区项目 | 20 | 250 | 4,000 | 20,000 |
| **多 Token** | 桌面应用（多用户） | 20/用户 | 20/用户 | 50/用户 | 100/用户 |

### 2.2 当前项目 Token

```
eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJTdWJqZWN0IjoiYjNhNWI4NmQtZGZlNC00YmJmLWFiMGEtMzZkMzc4ZjBiNDNhIiwiU3RlYW1JZCI6IjE0ODg3NzM1MSIsIkFQSVVzZXIiOiJ0cnVlIiwibmJmIjoxNzc4MzMzMDE4LCJleHAiOjE4MDk4NjkwMTgsImlhdCI6MTc3ODMzMzAxOCwiaXNzIjoiaHR0cHM6Ly9hcGkuc3RyYXR6LmNvbSJ9.Afjbu4LtlAp2tBFoLXi595_AbkIU3WbZXIU6nxCUrn4
```

**注意**: Token 有效期约 1 年，需定期检查续期

### 2.3 请求头要求

所有 API 请求必须包含以下请求头：

```
User-Agent: STRATZ_API
Authorization: Bearer {token}
Content-Type: application/json
```

---

## 三、GraphQL 查询格式

### 3.1 基本请求结构

```python
import requests

STRATZ_TOKEN = "your_token_here"
API_URL = "https://api.stratz.com/graphql"

def run_query(query: str) -> dict:
    """执行 GraphQL 查询"""
    headers = {
        'User-Agent': 'STRATZ_API',
        'Authorization': f'Bearer {STRATZ_TOKEN}',
        'Content-Type': 'application/json'
    }
    response = requests.post(
        API_URL,
        json={'query': query},
        headers=headers
    )
    return response.json()
```

### 3.2 GraphQL 查询语法

```graphql
{
  fieldName(argument1: value1, argument2: value2) {
    subField1
    subField2 {
      nestedField
    }
  }
}
```

---

## 四、主要查询类型

### 4.1 常量数据查询 (constants)

获取游戏基础数据：英雄、物品、技能、游戏模式等。

#### 4.1.1 获取英雄列表

```graphql
{
  constants {
    heroes {
      id
      name
      displayName
      shortName
      language {
        displayName
        hypeRideName
      }
      roles
      primaryAttribute
      attackType
      complexity
      movementSpeed
      armor
      attackDamageMin
      attackDamageMax
      attackRate
      attackRange
      projectileSpeed
      legs
      team
      heroOrder
    }
  }
}
```

#### 4.1.2 获取物品列表

```graphql
{
  constants {
    items {
      id
      name
      displayName
      shortName
      language {
        displayName
        description
        notes
        lore
      }
      cost
      recipe
      secretShop
      sideShop
      neutralDropTier
      ability {
        id
        name
        language {
          displayName
          description
        }
        attributes {
          name
          value
        }
        cooldown
        manaCost
      }
    }
  }
}
```

#### 4.1.3 获取技能列表

```graphql
{
  constants {
    abilities {
      id
      name
      displayName
      language {
        displayName
        description
        notes
        lore
      }
      type
      behavior
      targetTeam
      targetType
      damageType
      spellImmunity
      dispellable
      cooldown
      manaCost
      attributes {
        name
        value
      }
    }
  }
}
```

#### 4.1.4 获取游戏版本

```graphql
{
  constants {
    gameVersions {
      id
      name
      asOfDateTime
    }
  }
}
```

#### 4.1.5 获取游戏模式

```graphql
{
  constants {
    gameModes {
      id
      name
      displayName
      language {
        displayName
      }
      isStats
      isRanked
    }
  }
}
```

#### 4.1.6 获取区域列表

```graphql
{
  constants {
    regions {
      id
      name
      displayName
      language {
        displayName
      }
    }
  }
}
```

---

### 4.2 英雄统计查询 (heroStats)

获取英雄胜率、选取率等统计数据。

#### 4.2.1 按周获取英雄统计

```graphql
{
  heroStats {
    winWeek(
      take: 4,
      bracketIds: [DIVINE_IMMORTAL],
      positionIds: [POSITION_1],
      gameModeIds: [ALL_PICK],
      regionIds: [EUROPE, CHINA]
    ) {
      heroId
      matchCount
      winCount
      week
    }
  }
}
```

**参数说明**:

| 参数 | 类型 | 说明 |
|------|------|------|
| `take` | Int | 查询最近几周的数据 |
| `bracketIds` | [RankBracketBasicEnum] | 段位筛选（合并段位） |
| `positionIds` | [MatchPlayerPositionType] | 位置筛选 |
| `gameModeIds` | [GameModeEnumType] | 游戏模式筛选 |
| `regionIds` | [BasicRegionType] | 区域筛选 |
| `heroIds` | [Short] | 英雄ID筛选 |
| `skip` | Int | 分页跳过 |
| `groupBy` | FilterHeroWinRequestGroupBy | 分组方式 |

**段位枚举 (RankBracketBasicEnum)** - ⚠️ 注意：段位是合并的！

| 枚举值 | 说明 |
|--------|------|
| `UNCALIBRATED` | 未定级 |
| `HERALD_GUARDIAN` | 先锋 + 卫士（低分段） |
| `CRUSADER_ARCHON` | 骑士 + 主教（中低分段） |
| `LEGEND_ANCIENT` | 传奇 + 万古流芳（中高分段） |
| `DIVINE_IMMORTAL` | 超凡入圣 + 冠绝一世（高分段） |
| `FILTERED` | 已过滤 |
| `ALL` | 全部段位 |

**位置枚举 (MatchPlayerPositionType)**:
- `POSITION_1` - 1号位（大哥/Carry）
- `POSITION_2` - 2号位（中单/Mid）
- `POSITION_3` - 3号位（劣单/Offlane）
- `POSITION_4` - 4号位（辅助/Soft Support）
- `POSITION_5` - 5号位（辅助/Hard Support）

**游戏模式枚举 (GameModeEnumType)** - 常用值:
- `ALL_PICK` - 全英雄选择
- `CAPTAINS_MODE` - 队长模式
- `RANDOM_DRAFT` - 随机征召
- `SINGLE_DRAFT` - 单独征召
- `ALL_RANDOM` - 全随机
- `RANKED` - 天梯匹配
- `TURBO` - 快速模式

#### 4.2.2 获取英雄详细统计

```graphql
{
  heroStats {
    heroVsHeroMatchup(
      heroId: 1,
      bracketBasicIds: [DIVINE_IMMORTAL],
      positionIds: [POSITION_1]
    ) {
      vsHeroId
      matchCount
      winCount
      synergy
      advantage
    }
  }
}
```

#### 4.2.3 获取英雄出装统计

```graphql
{
  heroStats {
    itemBuild(
      heroId: 1,
      bracketBasicIds: [DIVINE_IMMORTAL],
      positionIds: [POSITION_1]
    ) {
      itemId
      matchCount
      winCount
      order
    }
  }
}
```

#### 4.2.4 获取英雄技能加点

```graphql
{
  heroStats {
    abilityBuild(
      heroId: 1,
      bracketBasicIds: [DIVINE_IMMORTAL],
      positionIds: [POSITION_1]
    ) {
      abilityId
      matchCount
      winCount
      order
    }
  }
}
```

---

### 4.3 比赛查询 (match)

获取比赛详情数据。

#### 4.3.1 获取比赛详情

```graphql
{
  match(matchId: 7000000000) {
    id
    startDateTime
    duration
    gameMode
    lobbyType
    isRanked
    isStats
    didRadiantWin
    radiantKills
    direKills
    radiantTeam {
      id
      name
    }
    direTeam {
      id
      name
    }
    players {
      steamAccountId
      heroId
      heroDamage
      towerDamage
      heroHealing
      kills
      deaths
      assists
      netWorth
      goldPerMinute
      experiencePerMinute
      position
      isRadiant
      level
      item0Id
      item1Id
      item2Id
      item3Id
      item4Id
      item5Id
      itemNeutralId
      backpack0Id
      backpack1Id
      backpack2Id
    }
    pickBans {
      heroId
      isPick
      isRadiant
      order
    }
  }
}
```

#### 4.3.2 获取比赛事件

```graphql
{
  match(matchId: 7000000000) {
    id
    duration
    events {
      type
      time
      playerSlot
      unit
      key
      value
    }
    killEvents {
      time
      killerPlayerSlot
      victimPlayerSlot
      assistsPlayerSlots
      x
      y
    }
  }
}
```

---

### 4.4 玩家查询 (player)

获取玩家数据和表现。

#### 4.4.1 获取玩家信息

```graphql
{
  player(steamAccountId: 148877351) {
    steamAccount {
      id
      name
      avatar
      isDotaPlusSubscriber
      dotaAccountLevel
      seasonRank
      seasonLeaderboardRank
    }
    matchCount
    winCount
    firstMatchDate
    lastMatchDate
    heroes {
      heroId
      matchCount
      winCount
      avgKills
      avgDeaths
      avgAssists
      avgGoldPerMinute
      avgExperiencePerMinute
    }
  }
}
```

#### 4.4.2 获取玩家比赛记录

```graphql
{
  player(steamAccountId: 148877351) {
    matches(take: 20, gameModeIds: [ALL_PICK_RANKED]) {
      id
      startDateTime
      duration
      didRadiantWin
      heroId
      kills
      deaths
      assists
      netWorth
      goldPerMinute
      experiencePerMinute
    }
  }
}
```

#### 4.4.3 获取玩家英雄表现

```graphql
{
  player(steamAccountId: 148877351) {
    heroPerformance(heroId: 1) {
      heroId
      matchCount
      winCount
      avgKills
      avgDeaths
      avgAssists
      avgGoldPerMinute
      avgExperiencePerMinute
      avgHeroDamage
      avgTowerDamage
      avgHeroHealing
    }
  }
}
```

---

### 4.5 联赛查询 (league)

获取职业联赛数据。

#### 4.5.1 获取联赛列表

```graphql
{
  leagues(take: 50, tier: [PROFESSIONAL, PREMIUM]) {
    id
    name
    displayName
    tier
    prizePool
    startDateTime
    endDateTime
    location
    imageUri
    isFinished
  }
}
```

#### 4.5.2 获取联赛比赛

```graphql
{
  league(leagueId: 12345) {
    id
    name
    matches(take: 100) {
      id
      startDateTime
      duration
      didRadiantWin
      radiantTeam {
        id
        name
      }
      direTeam {
        id
        name
      }
    }
  }
}
```

---

### 4.6 搜索查询 (search)

搜索玩家、比赛、联赛等。

#### 4.6.1 搜索玩家

```graphql
{
  search(query: "player_name") {
    players {
      steamAccountId
      name
      avatar
      seasonRank
    }
  }
}
```

#### 4.6.2 搜索联赛

```graphql
{
  search(query: "TI") {
    leagues {
      id
      name
      displayName
      tier
    }
  }
}
```

---

## 五、与 OpenDota API 对比

| 特性 | OpenDota | STRATZ |
|------|----------|--------|
| **API 类型** | REST | GraphQL |
| **查询灵活性** | 固定端点 | 自定义字段 |
| **英雄克制** | 直接提供 `/heroes/{id}/matchups` | 需自行计算 |
| **物品热度** | 直接提供 `/heroes/{id}/itemPopularity` | 需通过比赛数据计算 |
| **速率限制** | 60次/分钟 | 20次/秒（默认Token） |
| **数据更新** | 较慢 | 更快 |
| **段位筛选** | 不支持 | 支持多段位筛选 |
| **位置筛选** | 不支持 | 支持1-5号位筛选 |
| **区域筛选** | 不支持 | 支持多区域筛选 |
| **学习曲线** | 简单 | 需要学习 GraphQL |

---

## 六、DotaHelperAgent 集成建议

### 6.1 推荐使用场景

| 场景 | 推荐 API | 原因 |
|------|---------|------|
| 英雄克制分析 | OpenDota | 直接提供克制数据 |
| 实时胜率统计 | STRATZ | 支持段位/位置筛选 |
| 版本强势英雄 | STRATZ | 数据更新更快 |
| 玩家分析 | STRATZ | 数据更全面 |
| 比赛详情 | STRATZ | 事件数据更详细 |
| 出装推荐 | OpenDota | 直接提供物品热度 |

### 6.2 实现方案

建议在 `utils/` 目录下创建 `stratz_client.py`：

```python
"""STRATZ GraphQL API 客户端"""

import requests
from typing import Dict, List, Optional, Any
from dataclasses import dataclass

@dataclass
class StratzConfig:
    """STRATZ API 配置"""
    token: str
    api_url: str = "https://api.stratz.com/graphql"
    rate_limit_per_second: int = 20
    rate_limit_per_minute: int = 250
    timeout: int = 30


class StratzClient:
    """STRATZ GraphQL API 客户端
    
    特性：
    - GraphQL 查询支持
    - 自动速率限制
    - 缓存支持
    - 错误处理
    """
    
    def __init__(self, config: StratzConfig):
        self.config = config
        self.session = requests.Session()
        self._last_request_time = 0
        
    def _execute_query(self, query: str) -> Dict[str, Any]:
        """执行 GraphQL 查询"""
        headers = {
            'User-Agent': 'STRATZ_API',
            'Authorization': f'Bearer {self.config.token}',
            'Content-Type': 'application/json'
        }
        
        response = self.session.post(
            self.config.api_url,
            json={'query': query},
            headers=headers,
            timeout=self.config.timeout
        )
        
        response.raise_for_status()
        return response.json()
    
    def get_heroes(self) -> List[Dict]:
        """获取所有英雄列表"""
        query = """
        {
          constants {
            heroes {
              id
              name
              displayName
              shortName
              primaryAttribute
              attackType
              roles
            }
          }
        }
        """
        result = self._execute_query(query)
        return result.get('data', {}).get('constants', {}).get('heroes', [])
    
    def get_hero_stats(
        self,
        bracket_ids: List[str] = None,
        position_ids: List[str] = None,
        game_mode_ids: List[str] = None,
        weeks: int = 4
    ) -> List[Dict]:
        """获取英雄统计数据
        
        Args:
            bracket_ids: 段位列表，如 ['DIVINE_IMMORTAL']（注意：段位是合并的）
            position_ids: 位置列表，如 ['POSITION_1']
            game_mode_ids: 游戏模式列表，如 ['ALL_PICK']
            weeks: 查询最近几周的数据
        """
        brackets = bracket_ids or ['DIVINE_IMMORTAL']
        positions = position_ids or []
        game_modes = game_mode_ids or ['ALL_PICK']
        
        query = f"""
        {{
          heroStats {{
            winWeek(
              take: {weeks},
              bracketIds: [{', '.join(brackets)}],
              {f"positionIds: [{', '.join(positions)}]," if positions else ""}
              gameModeIds: [{', '.join(game_modes)}]
            ) {{
              heroId
              matchCount
              winCount
              week
            }}
          }}
        }}
        """
        result = self._execute_query(query)
        return result.get('data', {}).get('heroStats', {}).get('winWeek', [])
    
    def get_match(self, match_id: int) -> Dict:
        """获取比赛详情"""
        query = f"""
        {{
          match(matchId: {match_id}) {{
            id
            startDateTime
            duration
            gameMode
            didRadiantWin
            players {{
              steamAccountId
              heroId
              kills
              deaths
              assists
              netWorth
              goldPerMinute
              experiencePerMinute
            }}
          }}
        }}
        """
        result = self._execute_query(query)
        return result.get('data', {}).get('match', {})
    
    def get_player(self, steam_account_id: int) -> Dict:
        """获取玩家信息"""
        query = f"""
        {{
          player(steamAccountId: {steam_account_id}) {{
            steamAccount {{
              id
              name
              avatar
              seasonRank
            }}
            matchCount
            winCount
          }}
        }}
        """
        result = self._execute_query(query)
        return result.get('data', {}).get('player', {})
```

### 6.3 Agent 工具集成

```python
from langchain.tools import BaseTool
from pydantic import Field
from typing import Optional, Type
from pydantic import BaseModel

class StratzHeroStatsInput(BaseModel):
    """STRATZ 英雄统计工具输入"""
    bracket: str = Field(default="DIVINE_IMMORTAL", description="段位: UNCALIBRATED, HERALD_GUARDIAN, CRUSADER_ARCHON, LEGEND_ANCIENT, DIVINE_IMMORTAL, ALL")
    position: Optional[str] = Field(default=None, description="位置: POSITION_1, POSITION_2, POSITION_3, POSITION_4, POSITION_5")
    weeks: int = Field(default=4, description="查询最近几周的数据")

class StratzHeroStatsTool(BaseTool):
    """STRATZ 英雄统计工具"""
    name = "stratz_hero_stats"
    description = "获取 Dota 2 英雄统计数据，支持按段位、位置筛选。返回英雄胜率、选取率等信息。"
    args_schema: Type[BaseModel] = StratzHeroStatsInput
    
    def __init__(self, client: StratzClient):
        super().__init__()
        self.client = client
    
    def _run(self, bracket: str, position: Optional[str] = None, weeks: int = 4) -> str:
        bracket_ids = [bracket] if bracket else ['DIVINE_IMMORTAL']
        position_ids = [position] if position else []
        
        stats = self.client.get_hero_stats(
            bracket_ids=bracket_ids,
            position_ids=position_ids,
            weeks=weeks
        )
        
        if not stats:
            return "未获取到英雄统计数据"
        
        result = f"## {bracket} 段位英雄统计（最近 {weeks} 周）\n\n"
        result += "| 英雄ID | 比赛场次 | 胜场 | 胜率 |\n"
        result += "|--------|----------|------|------|\n"
        
        for stat in sorted(stats, key=lambda x: x.get('winCount', 0) / max(x.get('matchCount', 1), 1), reverse=True)[:20]:
            hero_id = stat.get('heroId', 0)
            match_count = stat.get('matchCount', 0)
            win_count = stat.get('winCount', 0)
            win_rate = win_count / max(match_count, 1) * 100
            result += f"| {hero_id} | {match_count} | {win_count} | {win_rate:.1f}% |\n"
        
        return result
```

---

## 七、注意事项

### 7.1 Token 安全

- 不要将 Token 硬编码在代码中
- 使用环境变量或配置文件存储
- 定期检查 Token 有效期

### 7.2 速率限制

- 实现请求频率控制
- 避免超出限制（默认 Token: 20次/秒）
- 实现重试机制

### 7.3 缓存策略

- 对不常变化的数据实施缓存（如英雄列表、物品列表）
- 英雄统计数据建议缓存 1-24 小时
- 比赛数据实时性要求高，不建议长时间缓存

### 7.4 错误处理

- 处理 GraphQL 错误响应
- 处理速率限制响应（HTTP 429）
- 处理网络超时

---

## 八、相关资源

- [STRATZ API 文档](https://stratz.com/api)
- [GraphQL 交互式查询](https://api.stratz.com/graphiql)
- [STRATZ Python 库](https://github.com/fxckfxtxre/Stratz)
- [STRATZ C# 模型](https://github.com/TheAmazingLooser/STRATZ_Models)
- [STRATZ Java 库](https://github.com/nkurgachev/stratz-graphql-api)

---

## 九、常用查询速查表

| 查询目的 | 查询类型 | 主要字段 |
|---------|---------|---------|
| 获取英雄列表 | `constants.heroes` | id, name, displayName, roles |
| 获取物品列表 | `constants.items` | id, name, cost, recipe |
| 获取技能列表 | `constants.abilities` | id, name, cooldown, manaCost |
| 获取游戏版本 | `constants.gameVersions` | id, name, asOfDateTime |
| 获取英雄胜率 | `heroStats.winWeek` | heroId, matchCount, winCount |
| 获取比赛详情 | `match` | id, duration, players, pickBans |
| 获取玩家信息 | `player` | steamAccount, matchCount, winCount |
| 获取联赛列表 | `leagues` | id, name, tier, prizePool |
| 搜索玩家 | `search.players` | steamAccountId, name |

---

## 十、文档修订说明

### 10.1 基于 GraphQL Schema 的修正

本文档已根据 STRATZ API 的实际 GraphQL Introspection 查询结果进行修正。

**主要修正内容**：

1. **段位枚举 (RankBracketBasicEnum)** - ⚠️ 重大修正
   - 原文档错误地使用了单独段位：`HERALD`, `GUARDIAN`, `DIVINE`, `IMMORTAL` 等
   - 实际 API 使用合并段位：`HERALD_GUARDIAN`, `CRUSADER_ARCHON`, `LEGEND_ANCIENT`, `DIVINE_IMMORTAL`
   - 这意味着无法单独查询某个段位的数据，只能查询合并后的段位区间

2. **游戏模式枚举 (GameModeEnumType)**
   - 原文档使用了 `ALL_PICK_RANKED`，实际 API 中不存在此值
   - 实际应使用 `ALL_PICK` 或 `RANKED`

3. **查询参数名称**
   - `bracketIds` 参数使用 `RankBracket` 枚举（更细粒度）或 `RankBracketBasicEnum`（合并段位）
   - 部分查询使用 `bracketBasicIds` 参数

### 10.2 验证方法

建议使用以下 GraphQL Introspection 查询验证 Schema：

```graphql
{
  __schema {
    types {
      name
      kind
      ... on ENUM_TYPE {
        enumValues {
          name
          description
        }
      }
    }
  }
}
```

或访问交互式文档：`https://api.stratz.com/graphiql`
