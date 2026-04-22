# DotaHelperAgent - Dota 2 英雄推荐助手

基于 OpenDota API 的智能 Dota 2 英雄推荐 Agent，提供英雄克制分析、出装推荐和技能加点建议。**全模块支持 LLM 优先，数据驱动兜底的混合模式**，提供更智能的推荐和策略建议。

## ✨ 特性

- **英雄推荐** - 根据己方和对方阵容，推荐最佳英雄选择（🤖 LLM 优先）
- **克制分析** - 分析英雄间的克制关系，提供数据支撑
- **出装推荐** - 根据游戏阶段推荐最优物品搭配（🤖 LLM 优先）
- **技能加点** - 基于英雄定位推荐技能加点顺序（🤖 LLM 优先）
- **智能缓存** - 两级缓存架构（内存 + 文件），减少 API 调用
- **速率限制** - 自动限流，符合 OpenDota API 限制（60 次/分钟）
- **可配置化** - 支持灵活的配置选项
- **策略模式** - 支持多种评分策略，易于扩展
- **缓存预热** - 支持预加载热门数据，提升性能
- **线程安全** - 缓存支持多线程并发访问
- **🆕 混合模式架构** - **所有核心功能优先使用 LLM**，数据驱动作为兜底
- **🆕 中文本地化** - 英雄和物品中文名称支持

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

### 🆕 LLM 增强分析（可选）

支持接入本地部署的大模型（如 LM Studio、Ollama），提供智能推荐解释。

#### 方式一：使用配置文件（推荐）

1. 复制配置文件模板：
```bash
cp agents/DotaHelperAgent/config/llm_config.yaml.example agents/DotaHelperAgent/config/llm_config.yaml
```

2. 编辑 `agents/DotaHelperAgent/config/llm_config.yaml`：
```yaml
llm:
  enabled: true
  base_url: "http://127.0.0.1:1234/v1"  # 本地模型服务地址
  model: "qwen3.5-9b"                    # 模型名称
  temperature: 0.7
  max_tokens: 2048
```

3. 使用配置：
```python
from agents.DotaHelperAgent import DotaHelperAgent, AgentConfig, LLMConfig

# 自动从配置文件加载 LLM 配置
llm_config = LLMConfig.from_yaml()  # 自动查找配置文件
config = AgentConfig(llm=llm_config)
agent = DotaHelperAgent(config=config)
```

#### 方式二：代码中直接配置

```python
from agents.DotaHelperAgent import (
    DotaHelperAgent,
    AgentConfig,
    LLMConfig,
)

# 代码中直接配置（优先级高于配置文件）
llm_config = LLMConfig(
    enabled=True,
    base_url="http://127.0.0.1:1234/v1",  # 本地模型服务地址
    model="qwen3.5-9b",                    # 模型名称
    temperature=0.7,
    max_tokens=2048,
)

config = AgentConfig(llm=llm_config)
agent = DotaHelperAgent(config=config)
```

#### 使用 LLM 功能

```python
# 获取推荐（优先使用 LLM，失败则使用数据驱动兜底）
result = agent.recommend_heroes(
    our_heroes=["Anti-Mage"],
    enemy_heroes=["Pudge", "Phantom Assassin"],
    top_n=3
)

# 查看推荐来源
print(f"推荐来源：{result.get('source', 'unknown')}")  # 'llm' 或 'data'

# 使用 LLM 解释推荐原因
for rec in result['recommendations']:
    explanation = agent.explain_recommendation_with_llm(
        hero_name=rec['hero_name'],
        enemy_heroes=result['enemy_team'],
        win_rate=0.55,  # 示例胜率
        reasons=rec['reasons']
    )
    if explanation:
        print(f"\n🤖 AI 解释: {explanation}")

# 使用 LLM 分析阵容
analysis = agent.analyze_composition_with_llm(
    our_heroes=result['our_team'],
    enemy_heroes=result['enemy_team']
)
if analysis:
    print(f"\n📊 AI 阵容分析: {analysis}")

# 向 LLM 提问
answer = agent.ask_llm("什么英雄最克制帕吉？")
if answer:
    print(f"\n❓ AI 回答: {answer}")
```

## 🏗️ 架构设计

### 混合模式架构（Hybrid Architecture）

本项目采用**LLM 优先，数据驱动兜底**的混合模式架构，所有核心功能模块都遵循以下设计原则：

```
┌─────────────────────────────────────────────────────────────┐
│                      用户请求                                 │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                   HybridAnalyzer (基类)                      │
│  ┌───────────────────────────────────────────────────────┐  │
│  │ 1. 优先尝试 LLM 执行                                     │  │
│  │    - 智能分析                                           │  │
│  │    - 灵活响应                                           │  │
│  │    - 结构化输出                                         │  │
│  └───────────────────────────────────────────────────────┘  │
│                            │                                  │
│                    [LLM 失败？]                               │
│                            │                                  │
│  ┌───────────────────────────────────────────────────────┐  │
│  │ 2. 回退到数据驱动执行                                    │  │
│  │    - 可靠数据                                           │  │
│  │    - 规则分析                                           │  │
│  │    - 稳定输出                                           │  │
│  └───────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                      返回结果 + 来源标识                       │
│  - source: "llm" | "data"                                   │
│  - success: true | false                                    │
└─────────────────────────────────────────────────────────────┘
```

### 核心模块

所有分析器模块都继承自 `HybridAnalyzer` 基类，实现统一的执行流程：

- **HybridHeroAnalyzer** - 英雄推荐与阵容分析
- **HybridItemRecommender** - 物品出装推荐
- **HybridSkillBuilder** - 技能加点建议

### 代码复用性

通过 `hybrid_base.py` 提供通用的基类和工具：

- **ExecutionSource** - 执行来源枚举
- **HybridExecutor** - 混合执行器模板
- **HybridAnalyzer** - 分析器基类（带 LLM 支持）

```python
# 示例：使用混合模式
recommender = HybridItemRecommender(client, llm_enabled=True)

# LLM 优先，自动回退
result = recommender.recommend_items(
    hero_name="axe",
    game_stage="mid",
    enemy_heroes=["anti-mage", "crystal_maiden"]
)

print(f"推荐来源：{result.get('source')}")  # "llm" 或 "data"
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
│   ├── api_client.py      # OpenDota API 客户端
│   ├── llm_client.py      # LLM 客户端（可选）
│   └── localization.py    # 中文本地化
├── cache/                  # 缓存模块
│   ├── __init__.py
│   └── cache_manager.py   # 缓存管理器
├── examples/               # 使用示例
│   └── usage_examples.py
├── tests/                  # 测试目录
│   ├── __init__.py
│   ├── conftest.py        # pytest 配置和 fixtures
│   ├── test_agent.py      # Agent 功能测试
│   ├── test_cache.py      # 缓存完整测试（功能 + 性能）
│   ├── test_config.py     # 配置类测试
│   ├── test_strategies.py # 评分策略测试
│   ├── test_analyzers.py  # 分析器测试
│   └── test_api_client.py # API 客户端测试
├── README.md              # 本文件
└── __init__.py            # 包入口
```

## 🔧 核心组件

### 1. DotaHelperAgent

主入口类，整合所有功能模块。

```python
agent = DotaHelperAgent(
    api_key=None,      # API Key 可选
    config=None,       # 配置对象可选
    enable_llm=None    # 是否启用 LLM（可选，默认使用配置）
)

# 主要方法
agent.recommend_heroes(our_heroes, enemy_heroes, top_n=3)
agent.recommend_build(hero_name, role="core", game_stage="all")
agent.get_counter_heroes(target_hero, top_n=5)
agent.warm_up_cache()           # 预热缓存
agent.clear_cache()             # 清空缓存

# 🆕 LLM 增强方法（需要启用 LLM）
agent.explain_recommendation_with_llm(hero_name, enemy_heroes, win_rate, reasons)
agent.analyze_composition_with_llm(our_heroes, enemy_heroes)
agent.ask_llm(question, context=None)
agent.is_llm_enabled()          # 检查 LLM 是否已启用
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

# LLM 配置
llm_config = LLMConfig(
    enabled=True,                          # 是否启用 LLM
    base_url="http://127.0.0.1:1234/v1",   # 本地模型服务地址
    model="qwen3.5-9b",                    # 模型名称
    api_key=None,                          # API Key（本地通常不需要）
    temperature=0.7,                       # 温度参数
    max_tokens=2048,                       # 最大生成 token 数
    timeout=60,                            # 超时时间（秒）
)

# 总配置
agent_config = AgentConfig(
    api_key=None,
    matchup=matchup_config,
    cache=cache_config,
    rate_limit=rate_config,
    llm=llm_config,                        # 🆕 LLM 配置
)
```

## 💾 缓存系统详解

### 两级缓存架构

```
L1: 内存缓存 (Dict)      - 进程内共享，速度最快 (~0.0001 秒)
L2: 文件缓存 (JSON)      - 持久化存储，程序重启可恢复 (~0.01 秒)
```

### 缓存配置

```python
from agents.DotaHelperAgent import AgentConfig, CacheConfig

# 自定义缓存配置
config = AgentConfig(
    cache=CacheConfig(
        enabled=True,              # 是否启用缓存
        cache_dir="cache",         # 缓存目录
        ttl_hours=48,              # 缓存过期时间（小时）
        max_size_mb=200,           # 最大缓存大小（MB）
        max_items=2000,            # 最多缓存项数量
        enable_memory_cache=True,  # 是否启用内存缓存
    )
)

agent = DotaHelperAgent(config=config)
```

### 缓存管理

```python
agent = DotaHelperAgent()

# 查看缓存统计
stats = agent.client.cache.get_stats()
print(f"命中率：{stats['hit_rate']:.2%}")
print(f"命中次数：{stats['hits']}")
print(f"未命中次数：{stats['misses']}")
print(f"淘汰次数：{stats['evictions']}")

# 重置统计
agent.client.cache.reset_stats()

# 清空缓存
agent.clear_cache()

# 删除指定键
agent.client.cache.delete("hero_matchups_1")

# 检查键是否存在
exists = agent.client.cache.exists("heroes_list")
```

### 缓存预热

```python
agent = DotaHelperAgent()

# 预热热门英雄缓存（推荐在应用启动时执行）
agent.warm_up_cache()

# 预热指定英雄
agent.warm_up_cache(hero_ids=[1, 2, 5, 10, 15])

# 预热后首次访问速度提升 90%+
```

### 缓存装饰器

```python
from agents.DotaHelperAgent import CacheManager, get_cache

cache = CacheManager(cache_dir="cache", ttl_hours=24)

@get_cache("my_function_prefix")
def expensive_function(cache, param1, param2):
    """昂贵计算，结果会自动缓存"""
    result = param1 + param2  # 复杂计算
    return result

# 第一次调用会执行函数
result1 = expensive_function(cache, 1, 2)

# 第二次调用直接从缓存返回
result2 = expensive_function(cache, 1, 2)
```

### 性能优化建议

1. **启用缓存预热**
   ```python
   # 应用启动时预热
   agent.warm_up_cache()
   ```

2. **调整缓存 TTL**
   ```python
   # 开发环境：短 TTL
   cache_config = CacheConfig(ttl_hours=1)
   
   # 生产环境：长 TTL
   cache_config = CacheConfig(ttl_hours=48)
   ```

3. **启用内存缓存**
   ```python
   # 频繁访问的数据启用内存缓存
   cache_config = CacheConfig(enable_memory_cache=True)
   ```

4. **定期清理缓存**
   ```python
   # 定期清空过期缓存
   agent.clear_cache()
   ```

### 缓存数据说明

| 数据类型 | 缓存键 | 过期时间 | 说明 |
|---------|--------|---------|------|
| 英雄列表 | `heroes_list` | 24 小时 | 所有英雄基本信息 |
| 克制数据 | `hero_matchups_{id}` | 24 小时 | 英雄克制关系 |
| 物品数据 | `hero_items_{id}` | 24 小时 | 英雄物品热度 |
| 统计数据 | `hero_stats` | 24 小时 | 英雄统计数据 |


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

### 缓存优化特性

- ✅ **线程安全** - 使用 RLock 保证并发安全
- ✅ **LRU 淘汰** - 自动淘汰最久未使用的缓存
- ✅ **大小限制** - 支持最大容量和最大项数限制
- ✅ **命中率统计** - 实时统计缓存命中率
- ✅ **预热功能** - 支持预加载热门数据
- ✅ **自动过期** - 基于 TTL 的自动过期机制
- ✅ **两级缓存** - 内存 + 文件双重加速

## 🧪 测试

### 运行测试

```bash
# 运行所有测试
pytest agents/DotaHelperAgent/tests/

# 运行特定测试文件
pytest agents/DotaHelperAgent/tests/test_agent.py
pytest agents/DotaHelperAgent/tests/test_cache.py
pytest agents/DotaHelperAgent/tests/test_config.py
pytest agents/DotaHelperAgent/tests/test_strategies.py
pytest agents/DotaHelperAgent/tests/test_analyzers.py
pytest agents/DotaHelperAgent/tests/test_api_client.py

# 运行特定测试用例
pytest agents/DotaHelperAgent/tests/test_cache.py::TestCacheManager::test_basic_set_get
pytest agents/DotaHelperAgent/tests/test_agent.py::TestRecommendHeroes::test_recommend_heroes_basic

# 带覆盖率报告
pytest --cov=agents/DotaHelperAgent tests/

# 带详细输出
pytest -v agents/DotaHelperAgent/tests/
```

### 测试覆盖

测试套件覆盖以下方面：

- ✅ **功能测试** (`test_agent.py`)
  - Agent 初始化（默认配置、自定义配置）
  - 英雄推荐功能
  - 出装和技能推荐功能
  - 克制英雄查询
  - 格式化输出
  - 缓存管理

- ✅ **缓存测试** (`test_cache.py`)
  - 基本 set/get 操作
  - 缓存过期机制
  - LRU 淘汰机制
  - 内存缓存 vs 文件缓存
  - 线程安全测试
  - 缓存统计信息
  - 性能对比测试

- ✅ **配置测试** (`test_config.py`)
  - MatchupConfig 配置验证
  - CacheConfig 配置验证
  - RateLimitConfig 配置验证
  - LogConfig 配置验证
  - AgentConfig 集成验证

- ✅ **策略测试** (`test_strategies.py`)
  - WinRateStrategy 胜率策略
  - PopularityStrategy 热度策略
  - 策略边界条件
  - 多策略组合

- ✅ **分析器测试** (`test_analyzers.py`)
  - HeroAnalyzer 英雄分析器
  - ItemRecommender 物品推荐器
  - SkillBuilder 技能加点器

- ✅ **API 客户端测试** (`test_api_client.py`)
  - 速率限制
  - 缓存集成
  - 错误处理
  - 英雄转换方法

### 测试示例

```python
# 示例：缓存测试
import pytest
from cache.cache_manager import CacheManager

def test_cache_performance():
    cache = CacheManager(cache_dir="test_cache", ttl_hours=24)
    
    # 测试写入
    cache.set("test_key", {"data": "value"})
    
    # 测试读取
    data = cache.get("test_key")
    assert data is not None
    assert data["data"] == "value"
    
    # 测试统计
    stats = cache.get_stats()
    assert stats["hits"] >= 0
    assert stats["misses"] >= 0
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
6. **测试依赖** - 运行测试需要安装 pytest：`pip install pytest`
7. **测试隔离** - 测试使用临时目录，不会影响生产缓存

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
- **新增完整测试套件**
  - Agent 功能测试
  - 缓存系统测试（功能 + 性能）
  - 配置类测试
  - 评分策略测试
  - 分析器测试
  - API 客户端测试
- **新增缓存文档**
  - 详细缓存配置说明
  - 缓存管理 API
  - 性能优化建议
  - 缓存装饰器使用

## 📄 License

MIT License
