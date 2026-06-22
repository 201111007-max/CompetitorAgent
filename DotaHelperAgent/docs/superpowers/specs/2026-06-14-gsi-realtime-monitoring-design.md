# GSI 实时数据监控技术实现方案

> **版本**: v1.0
> **日期**: 2026-06-14
> **优先级**: P1
> **所属阶段**: 第二阶段 — GSI 实时数据处理
> **状态**: 待审核

---

## 一、问题陈述

当前 DotaHelperAgent 仅能查询 OpenDota API 的历史数据，无法获取实时游戏状态。用户在游戏过程中需要手动提问，Agent 无法主动感知游戏局势变化并提供实时建议（如堆野提醒、出装推荐、局势预警）。

核心痛点：
- 无法实时监控游戏状态（金钱、血量、技能冷却等）
- 缺乏事件驱动的主动提醒（堆野、符文刷新等）
- 无法基于实时数据做动态决策推荐

---

## 二、解决方案

通过 Dota 2 Game State Integration (GSI) 接口，接收游戏客户端推送的实时数据，建立状态管理 → 事件检测 → 主动推送的完整链路，使 Agent 从"被动查询助手"升级为"实时监控 + 主动推荐"系统。

### 2.1 技术决策

| 决策项 | 选择 | 理由 |
|--------|------|------|
| GSI 服务器 | 独立 Flask 实例（端口 3000） | 与主 API 解耦，GSI 高频推送不影响主服务性能 |
| 前端推送 | SSE (Server-Sent Events) | 复用现有 SSE 基础设施，前端已有 useLogStream 可参考 |
| 配置管理 | YAML 配置文件 | 与项目现有模式一致（knowledge_config.yaml 等） |
| 状态存储 | 内存缓存 + SQLite 持久化 | 内存缓存高性能，SQLite 支持历史查询 |
| 认证方式 | Token 认证 | GSI 配置中设置 token，确保数据来源安全 |

---

## 三、系统架构

### 3.1 整体架构图

```
┌─────────────────────────────────────────────────────────────────────┐
│                        Dota 2 客户端                                 │
│                   (GSI HTTP POST 推送)                               │
└────────────────────────────┬────────────────────────────────────────┘
                             │ HTTP POST (每秒 ~1次)
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    GSI HTTP 服务器 (独立 Flask, :3000)               │
│  ┌─────────────┐  ┌──────────────┐  ┌──────────────────┐          │
│  │ Token 认证   │→│ 数据解析      │→│ 状态管理器        │          │
│  └─────────────┘  └──────────────┘  │ (GSIStateManager) │          │
│                                      └────────┬─────────┘          │
└───────────────────────────────────────────────┼────────────────────┘
                                                │ 状态变化事件
                                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      事件处理器 (GSIEventHandler)                    │
│  ┌────────────┐  ┌────────────┐  ┌────────────┐  ┌────────────┐  │
│  │ 堆野提醒    │  │ 符文提醒    │  │ 昼夜提醒    │  │ 局势预警    │  │
│  └────────────┘  └────────────┘  └────────────┘  └────────────┘  │
│  ┌────────────┐  ┌────────────┐  ┌────────────┐  ┌────────────┐  │
│  │ 死亡分析    │  │ 出装提醒    │  │ 中立物品    │  │ 肉山提醒    │  │
│  └────────────┘  └────────────┘  └────────────┘  └────────────┘  │
└───────────────────────────────┬─────────────────────────────────────┘
                                │
                    ┌───────────┼───────────┐
                    ▼                       ▼
┌───────────────────────────┐  ┌───────────────────────────────────┐
│  Agent 工具层              │  │  SSE 推送通道                     │
│  (GSIDataTool)            │  │  (主 API :5000)                   │
│  Agent 查询时获取实时数据   │  │  主动推送事件提醒到前端            │
└───────────────────────────┘  └───────────────────────────────────┘
```

### 3.2 数据流

```
Dota 2 客户端
    │ POST / (GSI JSON)
    ▼
GSI 服务器 (:3000)
    │ 解析 + 认证
    ▼
GSIStateManager.update_state()
    │ 保存旧状态 → 解析新状态 → 检测变化 → 触发事件
    ▼
GSIEventHandler
    │ 根据事件类型分发处理
    ├─→ 游戏时间事件 → 检查堆野/符文/昼夜等定时提醒
    ├─→ 击杀/死亡事件 → 局势评估 + 策略推荐
    ├─→ 金钱变化事件 → 出装推荐
    └─→ 游戏状态变化 → 游戏开始/结束通知
        │
        ▼
    事件队列 (GSIEventQueue)
        │
    ├─→ 主 API SSE 推送 (/api/gsi/events) → 前端实时展示
    └─→ Agent 工具查询 (GSIDataTool) → Agent 推理时获取实时数据
```

---

## 四、模块设计

### 4.1 模块清单

| 模块 | 文件路径 | 职责 |
|------|---------|------|
| GSI 服务器 | `gsi/server.py` | 独立 Flask 服务器，接收 GSI 数据 |
| GSI 数据模型 | `gsi/models.py` | 游戏状态数据结构定义 |
| 状态管理器 | `gsi/state_manager.py` | 状态缓存、变化检测、事件触发 |
| 事件处理器 | `gsi/event_handler.py` | 游戏事件检测与提醒生成 |
| 事件队列 | `gsi/event_queue.py` | 事件缓冲与分发（SSE 推送 + Agent 查询） |
| GSI 工具 | `tools/gsi_tools.py` | Agent 可调用的 GSI 数据访问工具 |
| SSE 推送端 | `web/app.py` (新增路由) | SSE 事件推送接口 |
| 前端消费 | `frontend/src/composables/useGsiStream.ts` | 前端 SSE 消费 |
| 配置文件 | `config/gsi_config.yaml` | GSI 配置管理 |

### 4.2 模块依赖关系

```
gsi/server.py
    ├── gsi/models.py (数据结构)
    ├── gsi/state_manager.py (状态管理)
    │       └── gsi/models.py
    ├── gsi/event_handler.py (事件处理)
    │       ├── gsi/models.py
    │       ├── gsi/state_manager.py
    │       └── gsi/event_queue.py
    └── gsi/event_queue.py (事件分发)

tools/gsi_tools.py
    └── gsi/state_manager.py (查询状态)

web/app.py
    └── gsi/event_queue.py (SSE 推送)

frontend/src/composables/useGsiStream.ts
    └── (HTTP SSE 消费)
```

---

## 五、详细设计

### 5.1 GSI 数据模型 (`gsi/models.py`)

```python
@dataclass
class GameState:
    """完整游戏状态"""
    # 地图
    map_name: str = ""
    match_id: str = ""
    game_time: int = 0          # 游戏时间（秒）
    clock_time: int = 0         # 显示时间（可为负数，赛前）
    daytime: bool = True
    radiant_score: int = 0
    dire_score: int = 0
    game_state: str = ""        # DOTA_GAMERULES_STATE_*
    paused: bool = False
    win_team: str = ""

    # 玩家
    player_name: str = ""
    steam_id: str = ""
    kills: int = 0
    deaths: int = 0
    assists: int = 0
    last_hits: int = 0
    denies: int = 0
    gold: int = 0
    gold_reliable: int = 0
    gpm: int = 0
    xpm: int = 0

    # 英雄
    hero_name: str = ""
    hero_id: int = 0
    level: int = 1
    alive: bool = True
    respawn_seconds: int = 0
    health: int = 0
    max_health: int = 0
    mana: int = 0
    max_mana: int = 0
    buyback_cost: int = 0

    # 技能
    abilities: List[AbilityInfo] = field(default_factory=list)

    # 物品
    inventory: List[ItemInfo] = field(default_factory=list)

    # 元数据
    updated_at: float = 0.0


@dataclass
class AbilityInfo:
    """技能信息"""
    name: str = ""
    level: int = 0
    can_cast: bool = False
    passive: bool = False
    cooldown: float = 0.0
    ultimate: bool = False


@dataclass
class ItemInfo:
    """物品信息"""
    name: str = ""
    slot: str = ""          # slot0-5, stash0-5
    can_cast: bool = False
    cooldown: float = 0.0
    charges: int = 0


@dataclass
class GSIEvent:
    """GSI 事件"""
    event_type: str            # stack, rune, daytime, death, kill, item, roshan, neutral, game_state
    message: str               # 提醒消息
    priority: str = "info"     # info, warning, critical
    data: Dict = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
```

### 5.2 GSI 服务器 (`gsi/server.py`)

独立 Flask 实例，运行在 3000 端口，接收 Dota 2 客户端推送。

```python
class GSIServer:
    """GSI HTTP 服务器 — 独立 Flask 实例"""

    def __init__(self, host, port, token, state_manager, event_handler):
        self.host = host
        self.port = port
        self.token = token
        self.state_manager = state_manager
        self.event_handler = event_handler
        self.app = Flask(__name__)
        self._register_routes()

    def _register_routes(self):
        self.app.route('/', methods=['POST'])(self._handle_gsi)

    def _handle_gsi(self):
        """处理 GSI 数据推送"""
        data = request.json
        # Token 认证
        if self.token and data.get('auth', {}).get('token') != self.token:
            return jsonify({"error": "Invalid token"}), 403
        # 更新状态 → 触发事件检测
        self.state_manager.update_state(data)
        return jsonify({"status": "ok"})

    def start(self):
        """后台线程启动"""
        thread = threading.Thread(
            target=lambda: self.app.run(
                host=self.host, port=self.port,
                threaded=True, debug=False, use_reloader=False
            ),
            daemon=True
        )
        thread.start()
```

**Dota 2 客户端 GSI 配置文件**（用户需手动放置到 Dota 2 配置目录）：

```json
// 文件路径: Steam/steamapps/common/dota 2 beta/game/dota/cfg/gamestate_integration/dotahelper.cfg
{
    "uri": "http://127.0.0.1:3000",
    "timeout": 5.0,
    "buffer": 0.1,
    "throttle": 1.0,
    "heartbeat": 30.0,
    "data": {
        "provider": 1,
        "map": 1,
        "player": 1,
        "hero": 1,
        "abilities": 1,
        "items": 1
    },
    "auth": {
        "token": "your_secret_token"
    }
}
```

### 5.3 状态管理器 (`gsi/state_manager.py`)

```python
class GSIStateManager:
    """GSI 状态管理器 — 状态缓存 + 变化检测 + 事件触发"""

    def __init__(self, event_handler):
        self.current_state: Optional[GameState] = None
        self.previous_state: Optional[GameState] = None
        self.event_handler = event_handler
        self._lock = threading.Lock()

    def update_state(self, gsi_data: Dict):
        """更新游戏状态（线程安全）"""
        with self._lock:
            self.previous_state = self.current_state
            self.current_state = self._parse_gsi_data(gsi_data)
            if self.previous_state:
                self._detect_changes()

    def get_state(self) -> Optional[GameState]:
        """获取当前状态（线程安全）"""
        with self._lock:
            return self.current_state

    def _detect_changes(self):
        """检测状态变化，触发事件"""
        prev = self.previous_state
        curr = self.current_state

        # 游戏状态变化（进入/离开游戏）
        if curr.game_state != prev.game_state:
            self.event_handler.on_game_state_changed(prev.game_state, curr.game_state)

        # 游戏时间变化 → 定时事件检测
        if curr.game_time != prev.game_time:
            self.event_handler.on_game_time_tick(curr, prev)

        # 击杀变化
        if curr.kills > prev.kills:
            self.event_handler.on_kill(curr)

        # 死亡变化
        if curr.alive != prev.alive and not curr.alive:
            self.event_handler.on_death(curr)

        # 金钱大幅变化（购买物品）
        if prev.gold - curr.gold > 500:
            self.event_handler.on_gold_spent(curr, prev.gold - curr.gold)

        # 昼夜变化
        if curr.daytime != prev.daytime:
            self.event_handler.on_daytime_changed(curr)

        # 等级变化
        if curr.level > prev.level:
            self.event_handler.on_level_up(curr)
```

### 5.4 事件处理器 (`gsi/event_handler.py`)

基于游戏时间的事件检测，所有时间阈值可配置。

```python
class GSIEventHandler:
    """GSI 事件处理器"""

    def __init__(self, event_queue, config):
        self.event_queue = event_queue
        self.config = config  # gsi_config.yaml 中的 events 配置
        self._last_stack_reminder = -60   # 防重复提醒
        self._last_rune_reminder = -60

    def on_game_time_tick(self, state: GameState, prev: GameState):
        """游戏时间 tick — 检测定时事件"""
        t = state.game_time

        # 堆野提醒：每分钟 53 秒（可配置偏移量）
        if self.config.get('stack', {}).get('enabled', True):
            stack_offset = self.config['stack'].get('offset', 53)
            if t % 60 == stack_offset and t - self._last_stack_reminder > 30:
                self._emit('stack', f"堆野时间到了！（游戏 {self._fmt_time(t)}）", 'info')
                self._last_stack_reminder = t

        # 中符提醒：每 2 分钟
        if self.config.get('mid_rune', {}).get('enabled', True):
            if t > 0 and t % 120 == 0 and t - self._last_rune_reminder > 60:
                self._emit('rune', "中符刷新了！", 'info')
                self._last_rune_reminder = t

        # 财神符提醒：每 3 分钟（从 0:00 开始）
        if self.config.get('bounty_rune', {}).get('enabled', True):
            if t > 0 and t % 180 == 0:
                self._emit('rune', "财神符刷新了！", 'info')

        # 智慧符提醒：每 7 分钟（从 7:00 开始）
        if self.config.get('wisdom_rune', {}).get('enabled', True):
            if t > 0 and t % 420 == 0:
                self._emit('rune', "智慧符刷新了！", 'info')

        # 莲花提醒：每 3 分钟（从 3:00 开始）
        if self.config.get('lotus', {}).get('enabled', True):
            if t > 0 and t % 180 == 0:
                self._emit('rune', "莲花刷新了！", 'info')

        # 中立物品提醒：每 7 分钟（从 7:00 开始）
        if self.config.get('neutral_item', {}).get('enabled', True):
            if t > 0 and t % 420 == 0:
                self._emit('neutral', "中立物品刷新了！", 'info')

        # 肉山提醒：基于游戏阶段（简化：每 8-11 分钟提醒一次）
        if self.config.get('roshan', {}).get('enabled', True):
            roshan_interval = self.config['roshan'].get('interval', 480)
            if t > 0 and t % roshan_interval == 0:
                self._emit('roshan', "肉山可能已复活，注意查看！", 'warning')

    def on_game_state_changed(self, old_state: str, new_state: str):
        """游戏状态变化"""
        if new_state == 'DOTA_GAMERULES_STATE_GAME_IN_PROGRESS':
            self._emit('game_start', "游戏开始！祝你好运！", 'info')
        elif new_state == 'DOTA_GAMERULES_STATE_POST_GAME':
            self._emit('game_end', "游戏结束", 'info')

    def on_kill(self, state: GameState):
        self._emit('kill', f"击杀！当前 KDA: {state.kills}/{state.deaths}/{state.assists}", 'info')

    def on_death(self, state: GameState):
        self._emit('death', f"阵亡！复活时间: {state.respawn_seconds}s", 'warning')

    def on_gold_spent(self, state: GameState, amount: int):
        self._emit('item', f"购买了物品（花费 {amount} 金），剩余 {state.gold} 金", 'info')

    def on_daytime_changed(self, state: GameState):
        label = "白天" if state.daytime else "夜晚"
        self._emit('daytime', f"切换到{label}", 'info')

    def on_level_up(self, state: GameState):
        self._emit('level_up', f"升级到 {state.level} 级！", 'info')

    def _emit(self, event_type: str, message: str, priority: str):
        """发送事件到队列"""
        event = GSIEvent(
            event_type=event_type,
            message=message,
            priority=priority,
        )
        self.event_queue.put(event)

    @staticmethod
    def _fmt_time(seconds: int) -> str:
        m, s = divmod(abs(seconds), 60)
        return f"{m}:{s:02d}"
```

### 5.5 事件队列 (`gsi/event_queue.py`)

线程安全的事件缓冲队列，支持多个消费者（SSE 推送 + Agent 查询）。

```python
class GSIEventQueue:
    """GSI 事件队列 — 线程安全，支持多消费者"""

    def __init__(self, max_history: int = 100):
        self._queue = queue.Queue()
        self._history: List[GSIEvent] = []
        self._max_history = max_history
        self._lock = threading.Lock()
        self._subscribers: List[queue.Queue] = []  # SSE 订阅者

    def put(self, event: GSIEvent):
        """入队事件，通知所有订阅者"""
        self._queue.put(event)
        with self._lock:
            self._history.append(event)
            if len(self._history) > self._max_history:
                self._history = self._history[-self._max_history:]
        # 分发给所有 SSE 订阅者
        for sub in self._subscribers:
            try:
                sub.put_nowait(event)
            except queue.Full:
                pass  # 慢消费者丢弃

    def subscribe(self) -> queue.Queue:
        """订阅事件流（SSE 使用）"""
        q = queue.Queue(maxsize=50)
        with self._lock:
            self._subscribers.append(q)
        return q

    def unsubscribe(self, q: queue.Queue):
        """取消订阅"""
        with self._lock:
            if q in self._subscribers:
                self._subscribers.remove(q)

    def get_recent(self, n: int = 20) -> List[GSIEvent]:
        """获取最近 N 条事件"""
        with self._lock:
            return self._history[-n:]
```

### 5.6 GSI 工具 (`tools/gsi_tools.py`)

Agent 可调用的 GSI 数据访问工具，遵循项目现有 Tool 基类。

```python
class GSIDataTool(Tool):
    """获取当前游戏实时状态"""

    def __init__(self, state_manager):
        super().__init__(
            name="get_gsi_state",
            description="获取当前游戏的实时状态数据，包括英雄信息、金钱、血量、技能冷却、物品栏等。仅在游戏进行中可用。",
            parameters={},
            func=self._get_state,
            category="gsi"
        )
        self.state_manager = state_manager

    def _get_state(self) -> Dict[str, Any]:
        state = self.state_manager.get_state()
        if not state:
            return {"available": False, "message": "当前未检测到游戏状态，可能不在游戏中或 GSI 未连接"}
        return {
            "available": True,
            "hero": state.hero_name,
            "level": state.level,
            "alive": state.alive,
            "health": f"{state.health}/{state.max_health}",
            "mana": f"{state.mana}/{state.max_mana}",
            "gold": state.gold,
            "kills": state.kills,
            "deaths": state.deaths,
            "assists": state.assists,
            "gpm": state.gpm,
            "xpm": state.xpm,
            "game_time": state.game_time,
            "game_state": state.game_state,
            "inventory": [item.name for item in state.inventory],
        }


class GSIRecentEventsTool(Tool):
    """获取最近的 GSI 事件"""

    def __init__(self, event_queue):
        super().__init__(
            name="get_gsi_events",
            description="获取最近的游戏事件列表，如堆野提醒、符文刷新、击杀/死亡等事件。",
            parameters={"count": int},
            func=self._get_events,
            category="gsi"
        )
        self.event_queue = event_queue

    def _get_events(self, count: int = 10) -> Dict[str, Any]:
        events = self.event_queue.get_recent(count)
        return {
            "count": len(events),
            "events": [
                {"type": e.event_type, "message": e.message, "priority": e.priority}
                for e in events
            ]
        }
```

### 5.7 SSE 推送端 (`web/app.py` 新增路由)

在主 API 服务器中新增 SSE 推送接口，前端通过此接口接收 GSI 事件。

```python
@app.route('/api/gsi/events')
def gsi_event_stream():
    """SSE 推送 GSI 事件到前端"""
    def generate():
        subscriber = gsi_event_queue.subscribe()
        try:
            # 先发送最近的历史事件
            for event in gsi_event_queue.get_recent(5):
                yield f"event: {event.event_type}\ndata: {json.dumps(event.to_dict())}\n\n"
            # 然后持续推送新事件
            while True:
                try:
                    event = subscriber.get(timeout=30)
                    yield f"event: {event.event_type}\ndata: {json.dumps(event.to_dict())}\n\n"
                except queue.Empty:
                    yield f"event: heartbeat\ndata: {{}}\n\n"
        finally:
            gsi_event_queue.unsubscribe(subscriber)

    return Response(
        stream_with_context(generate()),
        mimetype='text/event-stream',
        headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'}
    )


@app.route('/api/gsi/state')
def gsi_state():
    """获取当前 GSI 状态（REST 接口，前端轮询备用）"""
    state = gsi_state_manager.get_state()
    if not state:
        return jsonify({"available": False})
    return jsonify({"available": True, "state": state.to_dict()})
```

### 5.8 前端消费 (`useGsiStream.ts`)

```typescript
export function useGsiStream() {
  const connected = ref(false)
  const currentState = ref<GameState | null>(null)
  const events = ref<GSIEvent[]>([])

  const connect = () => {
    const baseURL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:5000'
    const eventSource = new EventSource(`${baseURL}/api/gsi/events`)

    eventSource.onopen = () => { connected.value = true }

    eventSource.addEventListener('stack', (e) => {
      events.value.push(parseEvent(e))
    })
    eventSource.addEventListener('rune', (e) => {
      events.value.push(parseEvent(e))
    })
    // ... 其他事件类型

    eventSource.onerror = () => { connected.value = false }

    return eventSource
  }

  return { connected, currentState, events, connect }
}
```

### 5.9 配置文件 (`config/gsi_config.yaml`)

```yaml
# GSI 服务器配置
server:
  host: "127.0.0.1"
  port: 3000
  token: "your_secret_token"   # 需与 Dota 2 GSI cfg 文件中一致

# 状态管理
state:
  max_history: 100             # 事件历史记录最大条数
  persistence_enabled: true    # 是否持久化到 SQLite
  persistence_path: "data/gsi_history.db"

# 事件开关与参数
events:
  stack:
    enabled: true
    offset: 53                 # 堆野提醒偏移（秒），默认每分钟 53 秒
    min_interval: 30           # 最小提醒间隔（秒），防重复
  mid_rune:
    enabled: true
    interval: 120              # 中符刷新间隔（秒）
  bounty_rune:
    enabled: true
    interval: 180
  wisdom_rune:
    enabled: true
    interval: 420
  lotus:
    enabled: true
    interval: 180
  neutral_item:
    enabled: true
    interval: 420
  roshan:
    enabled: true
    interval: 480              # 肉山复活提醒间隔（秒）
  daytime:
    enabled: true
  kill:
    enabled: true
  death:
    enabled: true
  level_up:
    enabled: true
  gold_spent:
    enabled: true
    threshold: 500             # 金钱变化超过此值才触发

# SSE 推送
sse:
  heartbeat_interval: 30       # 心跳间隔（秒）
  max_queue_size: 50           # 每个订阅者队列大小
```

---

## 六、集成方案

### 6.1 初始化流程 (`web/app.py`)

```python
# 在 web/app.py 的初始化代码中添加：

from gsi.server import GSIServer
from gsi.state_manager import GSIStateManager
from gsi.event_handler import GSIEventHandler
from gsi.event_queue import GSIEventQueue
from tools.gsi_tools import GSIDataTool, GSIRecentEventsTool

# 1. 创建事件队列
gsi_event_queue = GSIEventQueue()

# 2. 创建事件处理器
gsi_event_handler = GSIEventHandler(gsi_event_queue, config['events'])

# 3. 创建状态管理器
gsi_state_manager = GSIStateManager(gsi_event_handler)

# 4. 启动 GSI 服务器（独立 Flask 实例）
gsi_server = GSIServer(
    host=config['server']['host'],
    port=config['server']['port'],
    token=config['server']['token'],
    state_manager=gsi_state_manager,
    event_handler=gsi_event_handler
)
gsi_server.start()

# 5. 注册 GSI 工具到 Agent
tool_registry.register(GSIDataTool(gsi_state_manager))
tool_registry.register(GSIRecentEventsTool(gsi_event_queue))
```

### 6.2 Agent 工具注册 (`tools/agent_tools.py`)

在 `create_all_tools()` 中新增 GSI 工具的创建逻辑（可选导入，GSI 未启用时不注册）：

```python
def create_all_tools(hero_analyzer=None, item_recommender=None, ...,
                     gsi_state_manager=None, gsi_event_queue=None):
    all_tools = []
    # ... 现有工具 ...

    # GSI 工具（可选）
    if gsi_state_manager:
        all_tools.append(GSIDataTool(gsi_state_manager))
    if gsi_event_queue:
        all_tools.append(GSIRecentEventsTool(gsi_event_queue))

    return all_tools
```

### 6.3 Langfuse 监控集成

GSI 事件处理也接入 Langfuse 追踪：

```python
# gsi/event_handler.py
try:
    from utils.langfuse_adapter import LangfuseClient
    LANGFUSE_AVAILABLE = True
except ImportError:
    LANGFUSE_AVAILABLE = False

class GSIEventHandler:
    def _emit(self, event_type, message, priority):
        event = GSIEvent(...)
        self.event_queue.put(event)

        # Langfuse 追踪
        if LANGFUSE_AVAILABLE:
            client = LangfuseClient.get_instance()
            if client and client.enabled:
                client.score(name=f"gsi_{event_type}", value=1)
```

---

## 七、前端展示方案

### 7.1 GSI 状态指示

在 `TopStatusBar.vue` 中新增 GSI 连接状态指示：

- 绿色圆点 + "GSI 已连接" — 游戏进行中
- 灰色圆点 + "GSI 未连接" — 不在游戏中
- 黄色圆点 + "GSI 连接中" — 正在建立连接

### 7.2 GSI 事件通知

GSI 事件以 Toast 通知形式展示在右下角，按优先级区分样式：

| 优先级 | 样式 | 示例 |
|--------|------|------|
| info | 默认暗色 | "堆野时间到了！" |
| warning | 黄色边框 | "阵亡！复活时间: 15s" |
| critical | 红色边框 | "肉山可能已复活！" |

### 7.3 GSI 状态面板

在 `RightDrawer.vue` 中新增 GSI 状态面板（可选），展示：
- 当前英雄 + 等级 + KDA
- 金钱 + GPM/XPM
- 血量/蓝量条
- 物品栏
- 游戏时间

---

## 八、文件变更清单

### 8.1 新增文件

| 文件路径 | 说明 |
|----------|------|
| `gsi/__init__.py` | GSI 包初始化 |
| `gsi/server.py` | GSI HTTP 服务器 |
| `gsi/models.py` | GSI 数据模型 |
| `gsi/state_manager.py` | 状态管理器 |
| `gsi/event_handler.py` | 事件处理器 |
| `gsi/event_queue.py` | 事件队列 |
| `tools/gsi_tools.py` | GSI Agent 工具 |
| `config/gsi_config.yaml` | GSI 配置文件 |
| `frontend/src/composables/useGsiStream.ts` | 前端 SSE 消费 |
| `frontend/src/types/gsi.ts` | 前端 GSI 类型定义 |
| `tests/unit/test_gsi_state_manager.py` | 状态管理器单元测试 |
| `tests/unit/test_gsi_event_handler.py` | 事件处理器单元测试 |
| `tests/integration/test_gsi_integration.py` | GSI 集成测试 |

### 8.2 修改文件

| 文件路径 | 改动范围 | 说明 |
|----------|----------|------|
| `web/app.py` | 新增路由 + 初始化 | SSE 推送接口 + GSI 组件初始化 |
| `tools/agent_tools.py` | 新增参数 | `create_all_tools()` 新增 gsi_state_manager 和 gsi_event_queue 参数 |
| `core/agent_controller.py` | 可选 | Agent 推理时自动注入 GSI 上下文 |
| `frontend/src/components/TopStatusBar.vue` | 新增 GSI 状态 | GSI 连接状态指示 |
| `frontend/src/components/RightDrawer.vue` | 新增面板 | GSI 状态面板（可选） |

---

## 九、实施步骤

### Phase 1: GSI 基础设施（3-4 天）

1. 创建 `gsi/models.py` — 数据模型
2. 创建 `gsi/event_queue.py` — 事件队列
3. 创建 `gsi/state_manager.py` — 状态管理器
4. 创建 `gsi/server.py` — GSI HTTP 服务器
5. 创建 `config/gsi_config.yaml` — 配置文件
6. 编写单元测试
7. 手动测试：启动 GSI 服务器 + Dota 2 客户端连接

### Phase 2: 事件处理与工具集成（2-3 天）

8. 创建 `gsi/event_handler.py` — 事件处理器
9. 创建 `tools/gsi_tools.py` — Agent 工具
10. 修改 `web/app.py` — 初始化 + SSE 路由
11. 修改 `tools/agent_tools.py` — 注册 GSI 工具
12. 编写集成测试

### Phase 3: 前端集成（2-3 天）

13. 创建 `frontend/src/types/gsi.ts` — 类型定义
14. 创建 `frontend/src/composables/useGsiStream.ts` — SSE 消费
15. 修改 `TopStatusBar.vue` — GSI 状态指示
16. 修改 `RightDrawer.vue` — GSI 状态面板（可选）
17. 端到端联调测试

---

## 十、风险与注意事项

1. **GSI 数据频率**：Dota 2 客户端默认每秒推送一次，状态管理器需高效处理，避免阻塞
2. **线程安全**：GSI 服务器在独立线程运行，状态管理器必须使用锁保护共享状态
3. **GSI 未连接降级**：GSI 是可选功能，未连接时 Agent 正常工作，GSIDataTool 返回 "不可用"
4. **事件防抖**：堆野等定时事件需要防重复触发（min_interval 机制）
5. **端口冲突**：3000 端口可能被占用，需在配置文件中支持自定义端口
6. **Dota 2 GSI 配置**：用户需手动放置 cfg 文件到 Dota 2 目录，需提供清晰的安装指引
7. **SSE 连接管理**：前端需处理断线重连，避免内存泄漏

---

## 十一、Out of Scope

- **WebSocket 推送**：不实现 WebSocket，使用 SSE
- **语音播报**：属于第五阶段（P2），不在本方案范围
- **桌面通知**：不在本方案范围，后续可扩展
- **多用户支持**：仅单用户模式
- **STRATZ API 集成**：仅使用 Dota 2 客户端 GSI 数据
- **决策引擎**：复杂局势评估和策略推荐属于第三阶段，本方案仅提供数据基础
- **移动端通知**：不实现

---

## 十二、Further Notes

- GSI 服务器与主 API 服务器通过 `GSIStateManager` 和 `GSIEventQueue` 共享内存，无需进程间通信
- 后续第三阶段（推理决策增强）可基于本方案提供的实时数据，实现更智能的局势评估和策略推荐
- 事件处理器中的时间检测基于 `game_time % interval == offset`，需要考虑 GSI 推送可能跳过某些秒数（throttle=1.0 时通常不会）
