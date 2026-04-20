# DotaHelperAgent - Dota 2 英雄推荐助手

基于 OpenDota API 的智能 Dota 2 英雄推荐 Agent，提供英雄克制分析、出装推荐和技能加点建议。

## ✨ 特性

- **英雄推荐** - 根据己方和对方阵容，推荐最佳英雄选择
- **克制分析** - 分析英雄间的克制关系，提供数据支撑
- **出装推荐** - 根据游戏阶段推荐最优物品搭配
- **技能加点** - 基于英雄定位推荐技能加点顺序
- **智能缓存** - 两级缓存架构（内存 + 文件），减少 API 调用
- **速率限制** - 自动限流，符合 OpenDota API 限制（60 次/分钟）
- **可配置化** - 支持灵活的配置选项
- **策略模式** - 支持多种评分策略，易于扩展
- **缓存预热** - 支持预加载热门数据，提升性能
- **线程安全** - 缓存支持多线程并发访问

## 📦 安装

```bash
pip install requests
```

## 🚀 快速开始

### 基础使用

```python
from agents.DotaHelperAgent import DotaHelperAgent

# 创建 Agent
agent = DotaHelperAgent()

# 英雄推荐
result = agent.recommend_heroes(
    our_heroes=["Anti-Mage"],
    enemy_heroes=["Phantom Assassin", "Pudge"],
    top_n=3
)
print(agent.format_recommendation(result))

# 出装推荐
build = agent.recommend_build(
    hero_name="Anti-Mage",
    role="core",
    game_stage="all"
)
print(agent.format_build(build))
```

### 自定义配置

```python
from agents.DotaHelperAgent import (
    DotaHelperAgent,
    AgentConfig,
    MatchupConfig,
    CacheConfig,
)

# 创建自定义配置
config = AgentConfig(
    matchup=MatchupConfig(
        min_games_threshold=50,      # 最小样本数
        min_winrate_threshold=0.50,  # 最小胜率
    ),
    cache=CacheConfig(
        ttl_hours=48,          # 缓存 48 小时
        max_size_mb=200,       # 最大 200MB
    ),
)

# 使用配置
agent = DotaHelperAgent(config=config)
```

### 自定义评分策略

```python
from agents.DotaHelperAgent import (
    DotaHelperAgent,
    WinRateStrategy,
    PopularityStrategy,
)

agent = DotaHelperAgent()

# 添加多种评分策略
agent.hero_analyzer.add_strategy(WinRateStrategy())
agent.hero_analyzer.add_strategy(PopularityStrategy())

result = agent.recommend_heroes(
    our_heroes=["Crystal Maiden"],
    enemy_heroes=["Pudge"],
    top_n=3
)
```

### 缓存预热

```python
agent = DotaHelperAgent()

# 预热缓存（预加载热门英雄数据）
agent.warm_up_cache()

# 后续调用会更快
result = agent.recommend_heroes(
    our_heroes=["Anti-Mage"],
    enemy_heroes=["Phantom Assassin"],
    top_n=3
)
```

## 📁 项目结构

```
DotaHelperAgent/
├── core/                   # 核心模块
│   ├── __init__.py
│   ├── agent.py           # 主 Agent 类
│   └── config.py          # 配置管理
├── analyzers/              # 分析器模块
│   ├── __init__.py
│   ├── hero_analyzer.py   # 英雄克制分析
│   ├── item_recommender.py # 物品推荐
│   └── skill_builder.py   # 技能加点建议
├── strategies/             # 评分策略
│   ├── __init__.py
│   └── score_strategies.py # 胜率/热度策略
├── utils/                  # 工具模块
│   ├── __init__.py
│   └── api_client.py      # OpenDota API 客户端
├── cache/                  # 缓存模块
│   ├── __init__.py
│   └── cache_manager.py   # 缓存管理器
├── examples/               # 使用示例
│   └── usage_examples.py
├── tests/                  # 测试目录
│   ├── __init__.py
│   ├── test_agent.py      # 功能测试
│   └── test_cache.py      # 缓存性能测试
├── README.md              # 本文件
└── __init__.py            # 包入口
```

## 🔧 核心组件

### 1. DotaHelperAgent

主入口类，整合所有功能模块。

```python
agent = DotaHelperAgent(
    api_key=None,  # API Key 可选
    config=None    # 配置对象可选
)

# 主要方法
agent.recommend_heroes(our_heroes, enemy_heroes, top_n=3)
agent.recommend_build(hero_name, role="core", game_stage="all")
agent.get_counter_heroes(target_hero, top_n=5)
agent.warm_up_cache()           # 预热缓存
agent.clear_cache()             # 清空缓存
```

### 2. OpenDotaClient

API 客户端，内置缓存和速率限制。

```python
from agents.DotaHelperAgent import OpenDotaClient

client = OpenDotaClient(
    api_key=None,              # 可选，可提升 API 限制
    cache_dir="cache",         # 缓存目录
    rate_limit_delay=1.0,      # 请求间隔（秒）
    cache_ttl_hours=24,        # 缓存过期时间
)

# API 方法
client.get_heroes()                     # 获取所有英雄
client.get_hero_matchups(hero_id)       # 获取英雄克制数据
client.get_hero_item_popularity(hero_id) # 获取物品 popularity
client.get_hero_stats()                 # 获取英雄统计数据
client.warm_up_cache()                  # 预热缓存
```

### 3. CacheManager

两级缓存管理器（内存 + 文件），线程安全，支持 LRU 淘汰。

```python
from agents.DotaHelperAgent import CacheManager

cache = CacheManager(
    cache_dir="cache",
    ttl_hours=24,
    max_size_mb=100,      # 最大 100MB
    max_items=1000,       # 最多 1000 项
)

# 基础操作
cache.set("key", data)
data = cache.get("key")
cache.clear()

# 装饰器方式
@cache.cached(prefix="my_func")
def expensive_function(param):
    return result

# 查看统计
stats = cache.get_stats()
```

### 4. HeroAnalyzer

英雄克制关系分析器，支持自定义评分策略。

```python
from agents.DotaHelperAgent import HeroAnalyzer, WinRateStrategy

analyzer = HeroAnalyzer(client)

# 添加评分策略
analyzer.add_strategy(WinRateStrategy())

# 分析克制关系
recommendations = analyzer.analyze_matchups(
    our_heroes=["Anti-Mage"],
    enemy_heroes=["Pudge"],
    top_n=3
)

# 获取克制特定英雄的英雄
counters = analyzer.get_counter_heroes("Phantom Assassin", top_n=5)
```

### 5. 配置类

```python
from agents.DotaHelperAgent import (
    AgentConfig,
    MatchupConfig,
    CacheConfig,
    RateLimitConfig,
)

# 克制分析配置
matchup_config = MatchupConfig(
    min_games_threshold=100,      # 最小比赛场次
    min_winrate_threshold=0.52,   # 最小胜率
    score_weight=100.0,           # 得分权重
)

# 缓存配置
cache_config = CacheConfig(
    enabled=True,
    cache_dir="cache",
    ttl_hours=24,
    max_size_mb=100,
    max_items=1000,
)

# 速率限制配置
rate_config = RateLimitConfig(
    delay_seconds=1.0,
    timeout_seconds=10,
    max_retries=3,
)

# 总配置
agent_config = AgentConfig(
    api_key=None,
    matchup=matchup_config,
    cache=cache_config,
    rate_limit=rate_config,
)
```

## 📊 缓存机制

### 两级缓存架构

```
L1: 内存缓存 (Dict)      - 进程内共享，速度最快 (~0.0001 秒)
L2: 文件缓存 (JSON)      - 持久化存储，程序重启可恢复 (~0.01 秒)
```

### 缓存策略

- **英雄列表** - 内存 + 文件双缓存
- **克制数据** - 按英雄 ID 缓存，24 小时过期
- **物品数据** - 按英雄 ID 缓存，24 小时过期
- **统计数据** - 全局缓存，24 小时过期

### 性能对比

| 方式 | 耗时 | 说明 |
|------|------|------|
| API 请求 | ~3 秒 | 首次调用 |
| 文件缓存 | ~0.01 秒 | 程序重启后 |
| 内存缓存 | ~0.0001 秒 | 同进程内 |

### 缓存优化

- **线程安全** - 使用 RLock 保证并发安全
- **LRU 淘汰** - 自动淘汰最久未使用的缓存
- **大小限制** - 支持最大容量和最大项数限制
- **命中率统计** - 实时统计缓存命中率
- **预热功能** - 支持预加载热门数据

## 🧪 运行测试

```bash
# 基础功能测试
python -m pytest agents/DotaHelperAgent/tests/test_agent.py

# 缓存性能测试
python -m pytest agents/DotaHelperAgent/tests/test_cache.py

# 使用示例
python agents/DotaHelperAgent/examples/usage_examples.py
```

## 📈 API 限制

OpenDota API 默认限制：
- 3000 次/天
- 60 次/分钟

本 Agent 已内置速率限制（默认 1 秒/请求），无需额外处理。

## 🔨 扩展开发

### 添加自定义评分策略

```python
from agents.DotaHelperAgent import IScoreStrategy, MatchupConfig
from typing import Dict, Any, List, Tuple

class MyCustomStrategy(IScoreStrategy):
    """自定义评分策略"""
    
    def calculate(self, matchup: Dict[str, Any], config: MatchupConfig) -> Tuple[float, List[str]]:
        """计算得分"""
        # 实现你的评分逻辑
        score = 0.0
        reasons = ["自定义理由"]
        return score, reasons

# 使用
agent = DotaHelperAgent()
agent.hero_analyzer.add_strategy(MyCustomStrategy())
```

### 修改配置

```python
from agents.DotaHelperAgent import AgentConfig, MatchupConfig

# 创建配置
config = AgentConfig(
    matchup=MatchupConfig(
        min_games_threshold=200,     # 提高样本要求
        min_winrate_threshold=0.55,  # 提高胜率要求
    ),
    cache=CacheConfig(
        ttl_hours=48,                # 延长缓存时间
    ),
)

agent = DotaHelperAgent(config=config)
```

## ⚠️ 注意事项

1. **首次运行较慢** - 需要下载英雄数据到缓存
2. **缓存位置** - 默认在 `cache/` 目录，可手动删除清空
3. **API 稳定性** - OpenDota 为社区维护，偶尔可能不稳定
4. **数据时效性** - 缓存 24 小时，如需最新数据请删除缓存文件
5. **并发安全** - 缓存已支持多线程，但建议单进程使用

## 📝 更新日志

### v1.0.0
- 重构项目结构，按功能模块分层
- 新增配置管理系统
- 新增策略模式支持
- 新增缓存预热功能
- 新增 LRU 淘汰机制
- 新增线程安全支持
- 优化代码结构和可读性
- 添加完整类型注解

## 📄 License

MIT License
