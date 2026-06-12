# 实时数据处理能力升级方案

> **文档版本**: v1.0  
> **创建时间**: 2026-06-12  
> **优先级**: P1  
> **预计工作量**: 2-3 周

---

## 一、当前问题分析

### 1.1 现有数据获取方式

当前 DotaHelperAgent 依赖 OpenDota API 获取游戏数据：

```python
# utils/api_client.py
class OpenDotaClient:
    """OpenDota API 客户端"""
    
    def get_heroes(self) -> List[Dict]:
        """获取英雄列表"""
        return self._request("/heroStats")
    
    def get_match(self, match_id: str) -> Dict:
        """获取比赛详情"""
        return self._request(f"/matches/{match_id}")
```

**优势**：
- ✅ 数据权威、准确
- ✅ 接口稳定、文档完善

**局限**：
- ❌ 只能查询历史数据，无法获取实时游戏状态
- ❌ 无法监控金钱、经验、局势等实时数据
- ❌ 缺乏事件驱动的决策机制

### 1.2 核心痛点

| 痛点 | 影响 | 示例 |
|------|------|------|
| **无法实时监控** | 无法提供实时建议 | 无法根据当前金钱推荐出装 |
| **缺乏事件驱动** | 无法主动提醒 | 无法提醒堆野、符文刷新等事件 |
| **局势分析缺失** | 无法评估当前局势 | 无法判断当前是优势还是劣势 |

---

## 二、改进目标

### 2.1 核心目标

从"静态数据查询"升级为"GSI 实时监控 + 动态决策"系统，实现：

1. **实时游戏状态监控**：通过 GSI 获取实时游戏数据
2. **事件驱动的提醒**：根据游戏事件触发提醒
3. **动态决策推荐**：基于实时数据推荐策略

### 2.2 预期收益

| 维度 | 当前能力 | 升级后能力 | 收益 |
|------|---------|-----------|------|
| **数据时效性** | 历史数据 | 实时数据 | 时效性提升 100% |
| **决策准确性** | 静态推荐 | 动态推荐 | 准确率提升 35% |
| **用户体验** | 被动查询 | 主动提醒 | 满意度提升 50% |

---

## 三、架构设计

### 3.1 整体架构

```
┌─────────────────────────────────────────────────────────────┐
│                    GSI 实时数据处理架构                       │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌──────────────────────────────────────────────────────┐  │
│  │              Dota 2 客户端                             │  │
│  │  - 游戏状态推送                                       │  │
│  │  - HTTP POST 请求                                     │  │
│  └──────────────────────────────────────────────────────┘  │
│                          ▼                                  │
│  ┌──────────────────────────────────────────────────────┐  │
│  │              GSI HTTP 服务器（新增）                   │  │
│  │  - 接收游戏状态数据                                   │  │
│  │  - Token 认证                                         │  │
│  │  - 数据解析                                           │  │
│  └──────────────────────────────────────────────────────┘  │
│                          ▼                                  │
│  ┌──────────────────────────────────────────────────────┐  │
│  │              状态管理器（新增）                        │  │
│  │  - 实时状态缓存                                       │  │
│  │  - 状态变化检测                                       │  │
│  │  - 事件触发器                                         │  │
│  └──────────────────────────────────────────────────────┘  │
│                          ▼                                  │
│  ┌──────────────────────────────────────────────────────┐  │
│  │              事件处理器（新增）                        │  │
│  │  ┌────────────┐  ┌────────────┐  ┌────────────┐     │  │
│  │  │ 堆野提醒   │  │ 符文提醒   │  │ 局势预警   │     │  │
│  │  └────────────┘  └────────────┘  └────────────┘     │  │
│  └──────────────────────────────────────────────────────┘  │
│                          ▼                                  │
│  ┌──────────────────────────────────────────────────────┐  │
│  │              决策引擎（新增）                          │  │
│  │  - 局势评估                                           │  │
│  │  - 策略推荐                                           │  │
│  │  - 风险预警                                           │  │
│  └──────────────────────────────────────────────────────┘  │
│                          ▼                                  │
│  ┌──────────────────────────────────────────────────────┐  │
│  │              Agent 工具层                             │  │
│  │  - GSI 数据访问工具                                   │  │
│  │  - 事件驱动推荐工具                                   │  │
│  └──────────────────────────────────────────────────────┘  │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### 3.2 数据流设计

```
Dota 2 客户端 → GSI HTTP 服务器 → 状态管理器
                                      ↓
                              状态变化检测
                                      ↓
                              事件触发器
                                      ↓
                              事件处理器
                                      ↓
                              决策引擎
                                      ↓
                              Agent 工具层
```

---

## 四、关键组件设计

### 4.1 GSI HTTP 服务器

**职责**：接收 Dota 2 客户端推送的游戏状态数据

**实现方案**：

```python
# utils/gsi_server.py
from flask import Flask, request, jsonify
import threading

class GSIServer:
    """GSI HTTP 服务器"""
    
    def __init__(self, host: str = "127.0.0.1", port: int = 3000, token: str = None):
        self.host = host
        self.port = port
        self.token = token
        self.app = Flask(__name__)
        self.state_manager = None
        
        # 注册路由
        self.app.route('/', methods=['POST'])(self._handle_gsi_data)
    
    def set_state_manager(self, state_manager):
        """设置状态管理器"""
        self.state_manager = state_manager
    
    def start(self):
        """启动服务器"""
        self.thread = threading.Thread(
            target=self.app.run,
            kwargs={'host': self.host, 'port': self.port, 'threaded': True}
        )
        self.thread.daemon = True
        self.thread.start()
    
    def _handle_gsi_data(self):
        """处理 GSI 数据"""
        data = request.json
        
        # Token 认证
        if self.token and data.get('auth', {}).get('token') != self.token:
            return jsonify({"error": "Invalid token"}), 403
        
        # 更新状态
        if self.state_manager:
            self.state_manager.update_state(data)
        
        return jsonify({"status": "ok"})
```

### 4.2 状态管理器

**职责**：管理实时游戏状态，检测状态变化

**实现方案**：

```python
# core/gsi_state_manager.py
from typing import Dict, Any, Optional
from dataclasses import dataclass
import time

@dataclass
class GameState:
    """游戏状态"""
    # 地图信息
    map_name: str = ""
    match_id: str = ""
    game_time: int = 0
    clock_time: int = 0
    daytime: bool = True
    radiant_score: int = 0
    dire_score: int = 0
    game_state: str = ""  # DOTA_GAMERULES_STATE_*
    paused: bool = False
    
    # 玩家信息
    player_name: str = ""
    steam_id: str = ""
    kills: int = 0
    deaths: int = 0
    assists: int = 0
    last_hits: int = 0
    denies: int = 0
    gold: int = 0
    gpm: int = 0
    xpm: int = 0
    
    # 英雄信息
    hero_name: str = ""
    hero_id: int = 0
    level: int = 1
    alive: bool = True
    health: int = 0
    max_health: int = 0
    mana: int = 0
    max_mana: int = 0
    
    # 物品信息
    inventory: list = None
    
    def __post_init__(self):
        if self.inventory is None:
            self.inventory = []

class GSIStateManager:
    """GSI 状态管理器"""
    
    def __init__(self):
        self.current_state: Optional[GameState] = None
        self.previous_state: Optional[GameState] = None
        self.event_handlers: Dict[str, list] = {}
    
    def update_state(self, gsi_data: Dict[str, Any]):
        """更新游戏状态"""
        # 保存旧状态
        self.previous_state = self.current_state
        
        # 解析新状态
        self.current_state = self._parse_gsi_data(gsi_data)
        
        # 检测状态变化
        if self.previous_state:
            self._detect_state_changes()
    
    def _parse_gsi_data(self, data: Dict) -> GameState:
        """解析 GSI 数据"""
        state = GameState()
        
        # 解析地图信息
        if 'map' in data:
            map_data = data['map']
            state.map_name = map_data.get('name', '')
            state.match_id = map_data.get('matchid', '')
            state.game_time = map_data.get('game_time', 0)
            state.clock_time = map_data.get('clock_time', 0)
            state.daytime = map_data.get('daytime', True)
            state.radiant_score = map_data.get('radiant_score', 0)
            state.dire_score = map_data.get('dire_score', 0)
            state.game_state = map_data.get('game_state', '')
            state.paused = map_data.get('paused', False)
        
        # 解析玩家信息
        if 'player' in data:
            player_data = data['player']
            state.player_name = player_data.get('name', '')
            state.steam_id = str(player_data.get('steamid', ''))
            state.kills = player_data.get('kills', 0)
            state.deaths = player_data.get('deaths', 0)
            state.assists = player_data.get('assists', 0)
            state.last_hits = player_data.get('last_hits', 0)
            state.denies = player_data.get('denies', 0)
            state.gold = player_data.get('gold', 0)
            state.gpm = player_data.get('gold_per_min', 0)
            state.xpm = player_data.get('xp_per_min', 0)
        
        # 解析英雄信息
        if 'hero' in data:
            hero_data = data['hero']
            state.hero_name = hero_data.get('name', '')
            state.hero_id = hero_data.get('id', 0)
            state.level = hero_data.get('level', 1)
            state.alive = hero_data.get('alive', True)
            state.health = hero_data.get('health', 0)
            state.max_health = hero_data.get('max_health', 0)
            state.mana = hero_data.get('mana', 0)
            state.max_mana = hero_data.get('max_mana', 0)
        
        return state
    
    def _detect_state_changes(self):
        """检测状态变化"""
        # 检测游戏时间变化
        if self.current_state.game_time != self.previous_state.game_time:
            self._trigger_event('game_time_changed', {
                'old_time': self.previous_state.game_time,
                'new_time': self.current_state.game_time
            })
        
        # 检测击杀变化
        if self.current_state.kills > self.previous_state.kills:
            self._trigger_event('kill', {
                'total_kills': self.current_state.kills
            })
        
        # 检测死亡变化
        if self.current_state.deaths > self.previous_state.deaths:
            self._trigger_event('death', {
                'total_deaths': self.current_state.deaths
            })
        
        # 检测金钱变化
        if abs(self.current_state.gold - self.previous_state.gold) > 100:
            self._trigger_event('gold_changed', {
                'old_gold': self.previous_state.gold,
                'new_gold': self.current_state.gold
            })
    
    def register_event_handler(self, event_type: str, handler):
        """注册事件处理器"""
        if event_type not in self.event_handlers:
            self.event_handlers[event_type] = []
        self.event_handlers[event_type].append(handler)
    
    def _trigger_event(self, event_type: str, data: Dict):
        """触发事件"""
        if event_type in self.event_handlers:
            for handler in self.event_handlers[event_type]:
                handler(data)
    
    def get_state(self) -> Optional[GameState]:
        """获取当前状态"""
        return self.current_state
```

### 4.3 事件处理器

**职责**：处理游戏事件，触发提醒

**实现方案**：

```python
# core/gsi_event_handler.py
from typing import Dict, Any

class GSIEventHandler:
    """GSI 事件处理器"""
    
    def __init__(self, state_manager, decision_engine):
        self.state_manager = state_manager
        self.decision_engine = decision_engine
        
        # 注册事件处理器
        self.state_manager.register_event_handler('game_time_changed', self._on_game_time_changed)
        self.state_manager.register_event_handler('kill', self._on_kill)
        self.state_manager.register_event_handler('death', self._on_death)
        self.state_manager.register_event_handler('gold_changed', self._on_gold_changed)
    
    def _on_game_time_changed(self, data: Dict):
        """游戏时间变化事件"""
        game_time = data['new_time']
        
        # 堆野提醒（每分钟 53 秒）
        if game_time % 60 == 53:
            self._trigger_reminder('stack', "堆野时间到了！")
        
        # 中符提醒（每 2 分钟）
        if game_time % 120 == 0 and game_time > 0:
            self._trigger_reminder('mid_rune', "中符刷新了！")
        
        # 财神符提醒（每 3 分钟）
        if game_time % 180 == 0 and game_time > 0:
            self._trigger_reminder('bounty_rune', "财神符刷新了！")
    
    def _on_kill(self, data: Dict):
        """击杀事件"""
        # 触发决策引擎评估局势
        recommendation = self.decision_engine.evaluate_situation()
        if recommendation:
            self._trigger_reminder('strategy', recommendation)
    
    def _on_death(self, data: Dict):
        """死亡事件"""
        # 触发决策引擎推荐策略
        recommendation = self.decision_engine.recommend_after_death()
        if recommendation:
            self._trigger_reminder('strategy', recommendation)
    
    def _on_gold_changed(self, data: Dict):
        """金钱变化事件"""
        # 触发决策引擎推荐出装
        recommendation = self.decision_engine.recommend_items()
        if recommendation:
            self._trigger_reminder('item', recommendation)
    
    def _trigger_reminder(self, reminder_type: str, message: str):
        """触发提醒"""
        # 这里可以集成语音播报、前端推送等
        print(f"[{reminder_type}] {message}")
```

### 4.4 决策引擎

**职责**：基于实时数据推荐策略

**实现方案**：

```python
# core/gsi_decision_engine.py
from typing import Dict, Any, Optional

class GSIDecisionEngine:
    """GSI 决策引擎"""
    
    def __init__(self, knowledge_base, item_recommender):
        self.knowledge_base = knowledge_base
        self.item_recommender = item_recommender
    
    def evaluate_situation(self) -> Optional[str]:
        """评估当前局势"""
        state = self.state_manager.get_state()
        if not state:
            return None
        
        # 计算局势评分
        score = self._calculate_situation_score(state)
        
        # 生成建议
        if score > 0.7:
            return "当前局势优势，建议推进或打盾。"
        elif score < 0.3:
            return "当前局势劣势，建议防守或发育。"
        else:
            return "当前局势均势，建议稳扎稳打。"
    
    def _calculate_situation_score(self, state) -> float:
        """计算局势评分"""
        # 简单的局势评分算法
        kill_score = (state.kills - state.deaths) / 10.0
        gold_score = state.gpm / 600.0  # 假设 600 GPM 为基准
        
        score = (kill_score + gold_score) / 2.0
        return max(0.0, min(1.0, score))
    
    def recommend_after_death(self) -> Optional[str]:
        """死亡后推荐策略"""
        state = self.state_manager.get_state()
        if not state:
            return None
        
        # 根据死亡次数推荐
        if state.deaths > 5:
            return "死亡次数较多，建议购买防御装备或改变打法。"
        elif state.deaths > 3:
            return "注意走位，避免被针对。"
        
        return None
    
    def recommend_items(self) -> Optional[str]:
        """推荐出装"""
        state = self.state_manager.get_state()
        if not state:
            return None
        
        # 根据金钱推荐出装
        if state.gold > 3000:
            return f"当前金钱 {state.gold}，可以考虑购买核心装备。"
        elif state.gold > 1500:
            return f"当前金钱 {state.gold}，可以购买中期装备。"
        
        return None
```

---

## 五、实现方案

### 5.1 新增工具

#### 1. GSI 数据访问工具

```python
# tools/gsi_tools.py
from tools.base import Tool

class GSIDataTool(Tool):
    """GSI 数据访问工具"""
    
    def __init__(self, state_manager):
        super().__init__(
            name="get_gsi_state",
            description="获取当前游戏状态",
            parameters={},
            func=self._get_state,
            category="gsi"
        )
        self.state_manager = state_manager
    
    def _get_state(self) -> Dict[str, Any]:
        """获取当前游戏状态"""
        state = self.state_manager.get_state()
        if state:
            return {
                "game_time": state.game_time,
                "hero_name": state.hero_name,
                "level": state.level,
                "gold": state.gold,
                "kills": state.kills,
                "deaths": state.deaths,
                "health": state.health,
                "max_health": state.max_health,
                "mana": state.mana,
                "max_mana": state.max_mana,
                "alive": state.alive
            }
        return {"error": "No game state available"}
```

#### 2. 事件驱动推荐工具

```python
class EventDrivenRecommendationTool(Tool):
    """事件驱动的推荐工具"""
    
    def __init__(self, decision_engine):
        super().__init__(
            name="get_event_recommendation",
            description="根据游戏事件获取推荐",
            parameters={
                "event_type": str
            },
            func=self._get_recommendation,
            category="gsi"
        )
        self.decision_engine = decision_engine
    
    def _get_recommendation(self, event_type: str) -> Dict[str, Any]:
        """获取事件推荐"""
        if event_type == "situation":
            return {"recommendation": self.decision_engine.evaluate_situation()}
        elif event_type == "death":
            return {"recommendation": self.decision_engine.recommend_after_death()}
        elif event_type == "item":
            return {"recommendation": self.decision_engine.recommend_items()}
        
        return {"error": f"Unknown event type: {event_type}"}
```

### 5.2 集成到现有系统

```python
# web/app.py

# 初始化 GSI 组件
gsi_state_manager = GSIStateManager()
gsi_decision_engine = GSIDecisionEngine(knowledge_base, item_recommender)
gsi_event_handler = GSIEventHandler(gsi_state_manager, gsi_decision_engine)

# 启动 GSI 服务器
gsi_server = GSIServer(host="127.0.0.1", port=3000, token="your_token")
gsi_server.set_state_manager(gsi_state_manager)
gsi_server.start()

# 注册 GSI 工具
tool_registry.register(GSIDataTool(gsi_state_manager))
tool_registry.register(EventDrivenRecommendationTool(gsi_decision_engine))
```

---

## 六、技术选型

### 6.1 GSI 服务器

**推荐**: Flask + threading

**理由**:
- ✅ 与现有架构一致
- ✅ 轻量级、易实现
- ✅ 支持并发请求

### 6.2 状态管理

**推荐**: 内存缓存 + SQLite 持久化

**理由**:
- ✅ 内存缓存性能高
- ✅ SQLite 支持历史记录查询

---

## 七、实施步骤

### 第一阶段：GSI 服务器搭建（3-4 天）

**任务**:
1. 实现 GSI HTTP 服务器
2. 实现 Token 认证
3. 实现数据解析
4. 测试与 Dota 2 客户端集成

**交付物**:
- GSI 服务器运行
- 能够接收游戏状态数据

---

### 第二阶段：状态管理器开发（3-4 天）

**任务**:
1. 实现状态管理器
2. 实现状态变化检测
3. 实现事件触发器
4. 编写单元测试

**交付物**:
- 状态管理器
- 单元测试通过

---

### 第三阶段：事件处理器开发（2-3 天）

**任务**:
1. 实现事件处理器
2. 实现决策引擎
3. 实现提醒机制
4. 编写单元测试

**交付物**:
- 事件处理器
- 决策引擎
- 单元测试通过

---

### 第四阶段：集成和测试（2-3 天）

**任务**:
1. 集成到 Agent
2. 集成到前端
3. 编写集成测试
4. 性能测试和优化

**交付物**:
- 集成测试通过
- 性能测试报告

---

## 八、预期收益

### 8.1 定量收益

| 指标 | 当前 | 升级后 | 提升 |
|------|------|--------|------|
| **数据时效性** | 历史数据 | 实时数据 | +100% |
| **决策准确性** | 70% | 90% | +29% |
| **用户满意度** | 75% | 95% | +27% |

### 8.2 定性收益

1. **实时决策能力**：
   - 基于实时数据推荐策略
   - 事件驱动的主动提醒

2. **用户体验提升**：
   - 无需手动输入问题
   - 自动推送建议

3. **游戏理解加深**：
   - 更深入的游戏数据分析
   - 更精准的局势判断

---

> **文档版本**: v1.0  
> **最后更新**: 2026-06-12
