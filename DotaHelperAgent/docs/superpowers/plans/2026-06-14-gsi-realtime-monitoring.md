# GSI 实时数据监控 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现 Dota 2 GSI 实时数据监控，接收游戏客户端推送的实时数据，建立状态管理 → 事件检测 → SSE 推送的完整链路

**Architecture:** 独立 Flask 实例(:3000) 接收 GSI 数据 → GSIStateManager 检测变化 → GSIEventHandler 生成事件 → GSIEventQueue 分发 → SSE 推送到前端 + Agent 工具查询

**Tech Stack:** Python/Flask, threading, queue, SSE, Vue 3/TypeScript

---

## File Structure

| Action | File | Responsibility |
|--------|------|---------------|
| Create | `gsi/__init__.py` | GSI 包初始化，延迟导入 |
| Create | `gsi/models.py` | GameState, AbilityInfo, ItemInfo, GSIEvent 数据模型 |
| Create | `gsi/event_queue.py` | 线程安全事件队列，支持多消费者 |
| Create | `gsi/state_manager.py` | 状态缓存、变化检测、事件触发 |
| Create | `gsi/event_handler.py` | 游戏事件检测与提醒生成 |
| Create | `gsi/server.py` | 独立 Flask 服务器，接收 GSI 数据 |
| Create | `tools/gsi_tools.py` | Agent 可调用的 GSI 数据访问工具 |
| Create | `config/gsi_config.yaml` | GSI 配置管理 |
| Create | `tests/gsi/__init__.py` | 测试包 |
| Create | `tests/gsi/test_models.py` | 数据模型测试 |
| Create | `tests/gsi/test_event_queue.py` | 事件队列测试 |
| Create | `tests/gsi/test_state_manager.py` | 状态管理器测试 |
| Create | `tests/gsi/test_event_handler.py` | 事件处理器测试 |
| Create | `tests/gsi/test_server.py` | GSI 服务器测试 |
| Create | `frontend/src/types/gsi.ts` | 前端 GSI 类型定义 |
| Create | `frontend/src/composables/useGsiStream.ts` | 前端 SSE 消费 |
| Modify | `tools/agent_tools.py` | create_all_tools() 新增 GSI 工具参数 |
| Modify | `web/app.py` | GSI 初始化 + SSE 路由 + 状态 API |
| Modify | `frontend/src/components/TopStatusBar.vue` | GSI 连接状态指示 |
| Modify | `frontend/src/components/RightDrawer.vue` | GSI 状态面板 |

---

### Task 1: GSI 数据模型

**Files:**
- Create: `gsi/__init__.py`
- Create: `gsi/models.py`
- Create: `tests/gsi/__init__.py`
- Create: `tests/gsi/test_models.py`

- [ ] **Step 1: Create `gsi/__init__.py`**

```python
"""GSI (Game State Integration) 模块

提供 Dota 2 游戏状态集成功能：
- GSI HTTP 服务器（接收游戏客户端推送）
- 游戏状态管理（缓存、变化检测）
- 事件处理（堆野、符文、昼夜等提醒）
- 事件队列（SSE 推送 + Agent 查询）
"""

__all__ = [
    'GameState',
    'AbilityInfo',
    'ItemInfo',
    'GSIEvent',
    'GSIStateManager',
    'GSIEventHandler',
    'GSIEventQueue',
    'GSIServer',
]


def __getattr__(name):
    """延迟导入模块"""
    if name == 'GameState':
        from .models import GameState
        return GameState
    elif name == 'AbilityInfo':
        from .models import AbilityInfo
        return AbilityInfo
    elif name == 'ItemInfo':
        from .models import ItemInfo
        return ItemInfo
    elif name == 'GSIEvent':
        from .models import GSIEvent
        return GSIEvent
    elif name == 'GSIStateManager':
        from .state_manager import GSIStateManager
        return GSIStateManager
    elif name == 'GSIEventHandler':
        from .event_handler import GSIEventHandler
        return GSIEventHandler
    elif name == 'GSIEventQueue':
        from .event_queue import GSIEventQueue
        return GSIEventQueue
    elif name == 'GSIServer':
        from .server import GSIServer
        return GSIServer
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
```

- [ ] **Step 2: Create `gsi/models.py`**

```python
"""GSI 数据模型

定义游戏状态、技能、物品、事件等数据结构
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any
import time


@dataclass
class AbilityInfo:
    """技能信息"""
    name: str = ""
    level: int = 0
    can_cast: bool = False
    passive: bool = False
    cooldown: float = 0.0
    ultimate: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "level": self.level,
            "can_cast": self.can_cast,
            "passive": self.passive,
            "cooldown": self.cooldown,
            "ultimate": self.ultimate,
        }


@dataclass
class ItemInfo:
    """物品信息"""
    name: str = ""
    slot: str = ""
    can_cast: bool = False
    cooldown: float = 0.0
    charges: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "slot": self.slot,
            "can_cast": self.can_cast,
            "cooldown": self.cooldown,
            "charges": self.charges,
        }


@dataclass
class GameState:
    """完整游戏状态"""
    # 地图
    map_name: str = ""
    match_id: str = ""
    game_time: int = 0
    clock_time: int = 0
    daytime: bool = True
    radiant_score: int = 0
    dire_score: int = 0
    game_state: str = ""
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

    # 技能和物品
    abilities: List[AbilityInfo] = field(default_factory=list)
    inventory: List[ItemInfo] = field(default_factory=list)

    # 元数据
    updated_at: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "map_name": self.map_name,
            "match_id": self.match_id,
            "game_time": self.game_time,
            "clock_time": self.clock_time,
            "daytime": self.daytime,
            "radiant_score": self.radiant_score,
            "dire_score": self.dire_score,
            "game_state": self.game_state,
            "paused": self.paused,
            "win_team": self.win_team,
            "player_name": self.player_name,
            "steam_id": self.steam_id,
            "kills": self.kills,
            "deaths": self.deaths,
            "assists": self.assists,
            "last_hits": self.last_hits,
            "denies": self.denies,
            "gold": self.gold,
            "gold_reliable": self.gold_reliable,
            "gpm": self.gpm,
            "xpm": self.xpm,
            "hero_name": self.hero_name,
            "hero_id": self.hero_id,
            "level": self.level,
            "alive": self.alive,
            "respawn_seconds": self.respawn_seconds,
            "health": self.health,
            "max_health": self.max_health,
            "mana": self.mana,
            "max_mana": self.max_mana,
            "buyback_cost": self.buyback_cost,
            "abilities": [a.to_dict() for a in self.abilities],
            "inventory": [i.to_dict() for i in self.inventory],
            "updated_at": self.updated_at,
        }


@dataclass
class GSIEvent:
    """GSI 事件"""
    event_type: str
    message: str
    priority: str = "info"
    data: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_type": self.event_type,
            "message": self.message,
            "priority": self.priority,
            "data": self.data,
            "timestamp": self.timestamp,
        }


def parse_gsi_data(gsi_data: Dict[str, Any]) -> GameState:
    """解析 GSI 推送的原始 JSON 数据为 GameState"""
    state = GameState()

    # 解析 provider
    provider = gsi_data.get("provider", {})
    if provider:
        state.map_name = provider.get("name", "")

    # 解析 map
    map_data = gsi_data.get("map", {})
    if map_data:
        state.match_id = str(map_data.get("matchid", ""))
        state.game_time = map_data.get("game_time", 0)
        state.clock_time = map_data.get("clock_time", 0)
        state.daytime = map_data.get("daytime", True)
        state.radiant_score = map_data.get("radiant_score", 0)
        state.dire_score = map_data.get("dire_score", 0)
        state.game_state = map_data.get("game_state", "")
        state.paused = map_data.get("paused", False)
        state.win_team = map_data.get("win_team", "")

    # 解析 hero
    hero_data = gsi_data.get("hero", {})
    if hero_data:
        state.hero_name = hero_data.get("name", "")
        state.hero_id = hero_data.get("id", 0)
        state.level = hero_data.get("level", 1)
        state.alive = hero_data.get("alive", True)
        state.respawn_seconds = hero_data.get("respawn_seconds", 0)
        state.buyback_cost = hero_data.get("buyback_cost", 0)

        hp = hero_data.get("health", 0)
        max_hp = hero_data.get("max_health", 0)
        if isinstance(hp, (int, float)):
            state.health = int(hp)
        if isinstance(max_hp, (int, float)):
            state.max_health = int(max_hp)

        mp = hero_data.get("mana", 0)
        max_mp = hero_data.get("max_mana", 0)
        if isinstance(mp, (int, float)):
            state.mana = int(mp)
        if isinstance(max_mp, (int, float)):
            state.max_mana = int(max_mp)

        # 技能
        abilities = hero_data.get("abilities", {})
        if isinstance(abilities, dict):
            for _slot, ab in abilities.items():
                if isinstance(ab, dict):
                    state.abilities.append(AbilityInfo(
                        name=ab.get("name", ""),
                        level=ab.get("level", 0),
                        can_cast=ab.get("can_cast", False),
                        passive=ab.get("passive", False),
                        cooldown=ab.get("cooldown", 0.0),
                        ultimate=ab.get("ultimate", False),
                    ))

        # 物品
        items_data = hero_data.get("items", {})
        if isinstance(items_data, dict):
            for slot, item in items_data.items():
                if isinstance(item, dict):
                    state.inventory.append(ItemInfo(
                        name=item.get("name", ""),
                        slot=slot,
                        can_cast=item.get("can_cast", False),
                        cooldown=item.get("cooldown", 0.0),
                        charges=item.get("charges", 0),
                    ))

    # 解析 player
    player_data = gsi_data.get("player", {})
    if player_data:
        state.player_name = player_data.get("name", "")
        state.steam_id = str(player_data.get("steamid", ""))
        state.kills = player_data.get("kills", 0)
        state.deaths = player_data.get("deaths", 0)
        state.assists = player_data.get("assists", 0)
        state.last_hits = player_data.get("last_hits", 0)
        state.denies = player_data.get("denies", 0)
        state.gold = player_data.get("gold", 0)
        state.gold_reliable = player_data.get("gold_reliable", 0)
        state.gpm = player_data.get("gpm", 0)
        state.xpm = player_data.get("xpm", 0)

    state.updated_at = time.time()
    return state
```

- [ ] **Step 3: Create `tests/gsi/__init__.py`** (empty file)

- [ ] **Step 4: Create `tests/gsi/test_models.py`**

```python
"""GSI 数据模型测试"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from gsi.models import GameState, AbilityInfo, ItemInfo, GSIEvent, parse_gsi_data


class TestAbilityInfo:
    def test_default_values(self):
        ability = AbilityInfo()
        assert ability.name == ""
        assert ability.level == 0

    def test_to_dict(self):
        ability = AbilityInfo(name="q", level=3, can_cast=True)
        d = ability.to_dict()
        assert d["name"] == "q"
        assert d["level"] == 3


class TestItemInfo:
    def test_default_values(self):
        item = ItemInfo()
        assert item.name == ""

    def test_to_dict(self):
        item = ItemInfo(name="blink", slot="slot0", charges=1)
        d = item.to_dict()
        assert d["name"] == "blink"
        assert d["slot"] == "slot0"


class TestGameState:
    def test_default_values(self):
        state = GameState()
        assert state.game_time == 0
        assert state.alive is True
        assert state.level == 1

    def test_to_dict(self):
        state = GameState(hero_name="npc_dota_hero_pudge", level=6, kills=3)
        d = state.to_dict()
        assert d["hero_name"] == "npc_dota_hero_pudge"
        assert d["level"] == 6


class TestGSIEvent:
    def test_default_values(self):
        event = GSIEvent(event_type="stack", message="堆野时间到了")
        assert event.priority == "info"

    def test_to_dict(self):
        event = GSIEvent(event_type="rune", message="中符刷新", priority="warning")
        d = event.to_dict()
        assert d["event_type"] == "rune"


class TestParseGSIData:
    def test_parse_empty(self):
        state = parse_gsi_data({})
        assert state.game_time == 0

    def test_parse_map(self):
        data = {"map": {"game_time": 600, "radiant_score": 10, "game_state": "DOTA_GAMERULES_STATE_GAME_IN_PROGRESS"}}
        state = parse_gsi_data(data)
        assert state.game_time == 600
        assert state.radiant_score == 10

    def test_parse_hero(self):
        data = {"hero": {"name": "npc_dota_hero_pudge", "id": 14, "level": 6, "health": 800, "max_health": 1000}}
        state = parse_gsi_data(data)
        assert state.hero_name == "npc_dota_hero_pudge"
        assert state.health == 800

    def test_parse_player(self):
        data = {"player": {"name": "TestPlayer", "kills": 5, "gold": 3000}}
        state = parse_gsi_data(data)
        assert state.player_name == "TestPlayer"
        assert state.kills == 5

    def test_parse_abilities(self):
        data = {"hero": {"abilities": {
            "ability0": {"name": "pudge_hook", "level": 4, "can_cast": True},
            "ability3": {"name": "pudge_dismember", "ultimate": True},
        }}}
        state = parse_gsi_data(data)
        assert len(state.abilities) == 2
        assert state.abilities[0].name == "pudge_hook"
        assert state.abilities[1].ultimate is True

    def test_parse_items(self):
        data = {"hero": {"items": {
            "slot0": {"name": "blink", "can_cast": True},
            "slot1": {"name": "bkb", "cooldown": 5.0},
        }}}
        state = parse_gsi_data(data)
        assert len(state.inventory) == 2
        assert state.inventory[0].name == "blink"
```

- [ ] **Step 5: Run tests**

Run: `cd d:\trae_projects\first-agent\DotaHelperAgent && python -m pytest tests/gsi/test_models.py -v`
Expected: All tests PASS

- [ ] **Step 6: Commit**

```bash
git add gsi/__init__.py gsi/models.py tests/gsi/__init__.py tests/gsi/test_models.py
git commit -m "feat(gsi): add GSI data models and parsing"
```

---

### Task 2: GSI 事件队列

**Files:**
- Create: `gsi/event_queue.py`
- Create: `tests/gsi/test_event_queue.py`

- [ ] **Step 1: Create `gsi/event_queue.py`**

```python
"""GSI 事件队列 - 线程安全，支持多消费者"""

import queue
import threading
from typing import List, Optional

from gsi.models import GSIEvent
from utils.log_config import get_logger

logger = get_logger("gsi_event_queue", component="gsi")


class GSIEventQueue:
    """GSI 事件队列"""

    def __init__(self, max_history: int = 100):
        self._queue: queue.Queue = queue.Queue()
        self._history: List[GSIEvent] = []
        self._max_history = max_history
        self._lock = threading.Lock()
        self._subscribers: List[queue.Queue] = []

    def put(self, event: GSIEvent) -> None:
        """入队事件，通知所有订阅者"""
        self._queue.put(event)
        with self._lock:
            self._history.append(event)
            if len(self._history) > self._max_history:
                self._history = self._history[-self._max_history:]
        for sub in self._subscribers:
            try:
                sub.put_nowait(event)
            except queue.Full:
                pass

    def get(self, timeout: float = 1.0) -> Optional[GSIEvent]:
        """从队列获取事件（阻塞）"""
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def subscribe(self, maxsize: int = 50) -> queue.Queue:
        """订阅事件流（SSE 使用）"""
        q = queue.Queue(maxsize=maxsize)
        with self._lock:
            self._subscribers.append(q)
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        """取消订阅"""
        with self._lock:
            if q in self._subscribers:
                self._subscribers.remove(q)

    def get_recent(self, n: int = 20) -> List[GSIEvent]:
        """获取最近 N 条事件"""
        with self._lock:
            return list(self._history[-n:])

    def clear_history(self) -> None:
        """清空历史记录"""
        with self._lock:
            self._history.clear()

    @property
    def subscriber_count(self) -> int:
        with self._lock:
            return len(self._subscribers)
```

- [ ] **Step 2: Create `tests/gsi/test_event_queue.py`**

```python
"""GSI 事件队列测试"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from gsi.models import GSIEvent
from gsi.event_queue import GSIEventQueue


class TestGSIEventQueue:
    def test_put_and_get(self):
        eq = GSIEventQueue()
        eq.put(GSIEvent(event_type="stack", message="堆野"))
        result = eq.get(timeout=1.0)
        assert result is not None
        assert result.event_type == "stack"

    def test_get_timeout(self):
        eq = GSIEventQueue()
        assert eq.get(timeout=0.1) is None

    def test_get_recent(self):
        eq = GSIEventQueue()
        for i in range(5):
            eq.put(GSIEvent(event_type=f"t_{i}", message=f"m_{i}"))
        recent = eq.get_recent(3)
        assert len(recent) == 3
        assert recent[0].event_type == "t_2"

    def test_max_history(self):
        eq = GSIEventQueue(max_history=5)
        for i in range(10):
            eq.put(GSIEvent(event_type=f"t_{i}", message=f"m_{i}"))
        recent = eq.get_recent(10)
        assert len(recent) == 5

    def test_subscribe_unsubscribe(self):
        eq = GSIEventQueue()
        sub = eq.subscribe()
        assert eq.subscriber_count == 1
        eq.unsubscribe(sub)
        assert eq.subscriber_count == 0

    def test_subscriber_receives_events(self):
        eq = GSIEventQueue()
        sub = eq.subscribe()
        eq.put(GSIEvent(event_type="rune", message="中符"))
        received = sub.get(timeout=1.0)
        assert received.event_type == "rune"

    def test_clear_history(self):
        eq = GSIEventQueue()
        eq.put(GSIEvent(event_type="t1", message="m1"))
        eq.clear_history()
        assert len(eq.get_recent(10)) == 0
```

- [ ] **Step 3: Run tests**

Run: `cd d:\trae_projects\first-agent\DotaHelperAgent && python -m pytest tests/gsi/test_event_queue.py -v`
Expected: All tests PASS

- [ ] **Step 4: Commit**

```bash
git add gsi/event_queue.py tests/gsi/test_event_queue.py
git commit -m "feat(gsi): add thread-safe event queue with multi-consumer support"
```

---

### Task 3: GSI 状态管理器

**Files:**
- Create: `gsi/state_manager.py`
- Create: `tests/gsi/test_state_manager.py`

- [ ] **Step 1: Create `gsi/state_manager.py`**

```python
"""GSI 状态管理器 - 状态缓存、变化检测、事件触发"""

import threading
from typing import Optional, Dict, Any

from gsi.models import GameState, parse_gsi_data
from utils.log_config import get_logger

logger = get_logger("gsi_state_manager", component="gsi")


class GSIStateManager:
    """GSI 状态管理器"""

    def __init__(self, event_handler=None):
        self.current_state: Optional[GameState] = None
        self.previous_state: Optional[GameState] = None
        self.event_handler = event_handler
        self._lock = threading.Lock()
        self._connected: bool = False
        self._last_update_time: float = 0.0

    def update_state(self, gsi_data: Dict[str, Any]) -> None:
        """更新游戏状态（线程安全）"""
        new_state = parse_gsi_data(gsi_data)
        with self._lock:
            self.previous_state = self.current_state
            self.current_state = new_state
            self._connected = True
            self._last_update_time = new_state.updated_at
        if self.previous_state and self.event_handler:
            self._detect_changes(self.previous_state, new_state)

    def get_state(self) -> Optional[GameState]:
        """获取当前状态（线程安全）"""
        with self._lock:
            return self.current_state

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def last_update_time(self) -> float:
        return self._last_update_time

    def _detect_changes(self, prev: GameState, curr: GameState) -> None:
        """检测状态变化，触发事件"""
        handler = self.event_handler
        if handler is None:
            return
        if curr.game_state != prev.game_state:
            handler.on_game_state_changed(prev.game_state, curr.game_state)
        if curr.game_time != prev.game_time and curr.game_time > 0:
            handler.on_game_time_tick(curr, prev)
        if curr.kills > prev.kills:
            handler.on_kill(curr)
        if curr.alive != prev.alive and not curr.alive:
            handler.on_death(curr)
        gold_diff = prev.gold - curr.gold
        if gold_diff > 500:
            handler.on_gold_spent(curr, gold_diff)
        if curr.daytime != prev.daytime:
            handler.on_daytime_changed(curr)
        if curr.level > prev.level:
            handler.on_level_up(curr)
```

- [ ] **Step 2: Create `tests/gsi/test_state_manager.py`**

```python
"""GSI 状态管理器测试"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from gsi.state_manager import GSIStateManager


class MockEventHandler:
    def __init__(self):
        self.events = []

    def on_game_state_changed(self, old, new):
        self.events.append(("game_state_changed", old, new))

    def on_game_time_tick(self, curr, prev):
        self.events.append(("game_time_tick", curr.game_time))

    def on_kill(self, state):
        self.events.append(("kill", state.kills))

    def on_death(self, state):
        self.events.append(("death", state.respawn_seconds))

    def on_gold_spent(self, state, amount):
        self.events.append(("gold_spent", amount))

    def on_daytime_changed(self, state):
        self.events.append(("daytime_changed", state.daytime))

    def on_level_up(self, state):
        self.events.append(("level_up", state.level))


class TestGSIStateManager:
    def test_initial_state(self):
        manager = GSIStateManager()
        assert manager.get_state() is None
        assert manager.connected is False

    def test_update_state(self):
        manager = GSIStateManager()
        manager.update_state({"hero": {"name": "npc_dota_hero_pudge", "level": 6}})
        state = manager.get_state()
        assert state is not None
        assert state.hero_name == "npc_dota_hero_pudge"

    def test_detect_kill(self):
        handler = MockEventHandler()
        manager = GSIStateManager(event_handler=handler)
        manager.update_state({"player": {"kills": 0}})
        manager.update_state({"player": {"kills": 1}})
        assert ("kill", 1) in handler.events

    def test_detect_death(self):
        handler = MockEventHandler()
        manager = GSIStateManager(event_handler=handler)
        manager.update_state({"hero": {"alive": True}})
        manager.update_state({"hero": {"alive": False, "respawn_seconds": 15}})
        assert ("death", 15) in handler.events

    def test_detect_gold_spent(self):
        handler = MockEventHandler()
        manager = GSIStateManager(event_handler=handler)
        manager.update_state({"player": {"gold": 3000}})
        manager.update_state({"player": {"gold": 2000}})
        assert ("gold_spent", 1000) in handler.events

    def test_detect_level_up(self):
        handler = MockEventHandler()
        manager = GSIStateManager(event_handler=handler)
        manager.update_state({"hero": {"level": 5}})
        manager.update_state({"hero": {"level": 6}})
        assert ("level_up", 6) in handler.events

    def test_no_event_on_first_update(self):
        handler = MockEventHandler()
        manager = GSIStateManager(event_handler=handler)
        manager.update_state({"hero": {"level": 6}})
        assert len(handler.events) == 0

    def test_gold_spent_threshold(self):
        handler = MockEventHandler()
        manager = GSIStateManager(event_handler=handler)
        manager.update_state({"player": {"gold": 3000}})
        manager.update_state({"player": {"gold": 2800}})
        assert not any(e[0] == "gold_spent" for e in handler.events)
```

- [ ] **Step 3: Run tests**

Run: `cd d:\trae_projects\first-agent\DotaHelperAgent && python -m pytest tests/gsi/test_state_manager.py -v`
Expected: All tests PASS

- [ ] **Step 4: Commit**

```bash
git add gsi/state_manager.py tests/gsi/test_state_manager.py
git commit -m "feat(gsi): add state manager with change detection"
```

---

### Task 4: GSI 事件处理器

**Files:**
- Create: `gsi/event_handler.py`
- Create: `tests/gsi/test_event_handler.py`

- [ ] **Step 1: Create `gsi/event_handler.py`**

```python
"""GSI 事件处理器 - 游戏事件检测与提醒生成"""

from typing import Dict, Any

from gsi.models import GameState, GSIEvent
from gsi.event_queue import GSIEventQueue
from utils.log_config import get_logger

logger = get_logger("gsi_event_handler", component="gsi")


class GSIEventHandler:
    """GSI 事件处理器"""

    def __init__(self, event_queue: GSIEventQueue, config: Dict[str, Any] = None):
        self.event_queue = event_queue
        self.config = config or {}
        self._last_stack_reminder_time: int = -60
        self._last_rune_reminder_time: int = -60

    def on_game_time_tick(self, state: GameState, prev: GameState) -> None:
        """游戏时间 tick — 检测定时事件"""
        t = state.game_time

        # 堆野提醒
        stack_cfg = self.config.get("stack", {})
        if stack_cfg.get("enabled", True):
            offset = stack_cfg.get("offset", 53)
            min_interval = stack_cfg.get("min_interval", 30)
            if t % 60 == offset and t - self._last_stack_reminder_time > min_interval:
                self._emit("stack", f"堆野时间到了！（游戏 {self._fmt_time(t)}）", "info")
                self._last_stack_reminder_time = t

        # 中符提醒
        mid_rune_cfg = self.config.get("mid_rune", {})
        if mid_rune_cfg.get("enabled", True):
            interval = mid_rune_cfg.get("interval", 120)
            if t > 0 and t % interval == 0 and t - self._last_rune_reminder_time > 60:
                self._emit("rune", "中符刷新了！", "info")
                self._last_rune_reminder_time = t

        # 财神符提醒
        bounty_cfg = self.config.get("bounty_rune", {})
        if bounty_cfg.get("enabled", True):
            interval = bounty_cfg.get("interval", 180)
            if t > 0 and t % interval == 0:
                self._emit("rune", "财神符刷新了！", "info")

        # 智慧符提醒
        wisdom_cfg = self.config.get("wisdom_rune", {})
        if wisdom_cfg.get("enabled", True):
            interval = wisdom_cfg.get("interval", 420)
            if t > 0 and t % interval == 0:
                self._emit("rune", "智慧符刷新了！", "info")

        # 莲花提醒
        lotus_cfg = self.config.get("lotus", {})
        if lotus_cfg.get("enabled", True):
            interval = lotus_cfg.get("interval", 180)
            if t > 0 and t % interval == 0:
                self._emit("rune", "莲花刷新了！", "info")

        # 中立物品提醒
        neutral_cfg = self.config.get("neutral_item", {})
        if neutral_cfg.get("enabled", True):
            interval = neutral_cfg.get("interval", 420)
            if t > 0 and t % interval == 0:
                self._emit("neutral", "中立物品刷新了！", "info")

        # 肉山提醒
        roshan_cfg = self.config.get("roshan", {})
        if roshan_cfg.get("enabled", True):
            interval = roshan_cfg.get("interval", 480)
            if t > 0 and t % interval == 0:
                self._emit("roshan", "肉山可能已复活，注意查看！", "warning")

    def on_game_state_changed(self, old_state: str, new_state: str) -> None:
        if new_state == "DOTA_GAMERULES_STATE_GAME_IN_PROGRESS":
            self._emit("game_start", "游戏开始！祝你好运！", "info")
        elif new_state == "DOTA_GAMERULES_STATE_POST_GAME":
            self._emit("game_end", "游戏结束", "info")

    def on_kill(self, state: GameState) -> None:
        self._emit("kill", f"击杀！当前 KDA: {state.kills}/{state.deaths}/{state.assists}", "info")

    def on_death(self, state: GameState) -> None:
        self._emit("death", f"阵亡！复活时间: {state.respawn_seconds}s", "warning")

    def on_gold_spent(self, state: GameState, amount: int) -> None:
        self._emit("item", f"购买了物品（花费 {amount} 金），剩余 {state.gold} 金", "info")

    def on_daytime_changed(self, state: GameState) -> None:
        label = "白天" if state.daytime else "夜晚"
        self._emit("daytime", f"切换到{label}", "info")

    def on_level_up(self, state: GameState) -> None:
        self._emit("level_up", f"升级到 {state.level} 级！", "info")

    def _emit(self, event_type: str, message: str, priority: str) -> None:
        event = GSIEvent(event_type=event_type, message=message, priority=priority)
        self.event_queue.put(event)
        logger.debug(f"GSI 事件: [{priority}] {event_type} - {message}")

    @staticmethod
    def _fmt_time(seconds: int) -> str:
        m, s = divmod(abs(seconds), 60)
        return f"{m}:{s:02d}"
```

- [ ] **Step 2: Create `tests/gsi/test_event_handler.py`**

```python
"""GSI 事件处理器测试"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from gsi.models import GameState
from gsi.event_handler import GSIEventHandler
from gsi.event_queue import GSIEventQueue


class TestGSIEventHandler:
    def _make_state(self, game_time=0, **kwargs) -> GameState:
        return GameState(game_time=game_time, **kwargs)

    def test_stack_reminder(self):
        eq = GSIEventQueue()
        handler = GSIEventHandler(eq, {"stack": {"enabled": True, "offset": 53, "min_interval": 30}})
        handler.on_game_time_tick(self._make_state(game_time=53), self._make_state(game_time=52))
        events = eq.get_recent(1)
        assert len(events) == 1
        assert events[0].event_type == "stack"

    def test_stack_disabled(self):
        eq = GSIEventQueue()
        handler = GSIEventHandler(eq, {"stack": {"enabled": False}})
        handler.on_game_time_tick(self._make_state(game_time=53), self._make_state(game_time=52))
        assert len(eq.get_recent(1)) == 0

    def test_mid_rune(self):
        eq = GSIEventQueue()
        handler = GSIEventHandler(eq, {"mid_rune": {"enabled": True, "interval": 120}})
        handler.on_game_time_tick(self._make_state(game_time=120), self._make_state(game_time=119))
        events = eq.get_recent(1)
        assert events[0].event_type == "rune"
        assert "中符" in events[0].message

    def test_bounty_rune(self):
        eq = GSIEventQueue()
        handler = GSIEventHandler(eq, {"bounty_rune": {"enabled": True, "interval": 180}})
        handler.on_game_time_tick(self._make_state(game_time=180), self._make_state(game_time=179))
        assert "财神符" in eq.get_recent(1)[0].message

    def test_game_start(self):
        eq = GSIEventQueue()
        handler = GSIEventHandler(eq)
        handler.on_game_state_changed("", "DOTA_GAMERULES_STATE_GAME_IN_PROGRESS")
        assert eq.get_recent(1)[0].event_type == "game_start"

    def test_game_end(self):
        eq = GSIEventQueue()
        handler = GSIEventHandler(eq)
        handler.on_game_state_changed("", "DOTA_GAMERULES_STATE_POST_GAME")
        assert eq.get_recent(1)[0].event_type == "game_end"

    def test_kill_event(self):
        eq = GSIEventQueue()
        handler = GSIEventHandler(eq)
        handler.on_kill(self._make_state(kills=5, deaths=2, assists=8))
        assert "5/2/8" in eq.get_recent(1)[0].message

    def test_death_event(self):
        eq = GSIEventQueue()
        handler = GSIEventHandler(eq)
        handler.on_death(self._make_state(respawn_seconds=15))
        assert eq.get_recent(1)[0].priority == "warning"

    def test_daytime_change(self):
        eq = GSIEventQueue()
        handler = GSIEventHandler(eq)
        handler.on_daytime_changed(self._make_state(daytime=False))
        assert "夜晚" in eq.get_recent(1)[0].message

    def test_level_up(self):
        eq = GSIEventQueue()
        handler = GSIEventHandler(eq)
        handler.on_level_up(self._make_state(level=6))
        assert "6" in eq.get_recent(1)[0].message

    def test_fmt_time(self):
        assert GSIEventHandler._fmt_time(0) == "0:00"
        assert GSIEventHandler._fmt_time(53) == "0:53"
        assert GSIEventHandler._fmt_time(120) == "2:00"
```

- [ ] **Step 3: Run tests**

Run: `cd d:\trae_projects\first-agent\DotaHelperAgent && python -m pytest tests/gsi/test_event_handler.py -v`
Expected: All tests PASS

- [ ] **Step 4: Commit**

```bash
git add gsi/event_handler.py tests/gsi/test_event_handler.py
git commit -m "feat(gsi): add event handler with game time-based reminders"
```

---

### Task 5: GSI 配置文件

**Files:**
- Create: `config/gsi_config.yaml`

- [ ] **Step 1: Create `config/gsi_config.yaml`**

```yaml
# GSI (Game State Integration) 配置文件

server:
  host: "127.0.0.1"
  port: 3000
  token: "dota_helper_gsi_token"

state:
  max_history: 100
  persistence_enabled: false

events:
  stack:
    enabled: true
    offset: 53
    min_interval: 30
  mid_rune:
    enabled: true
    interval: 120
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
    interval: 480
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
    threshold: 500

sse:
  heartbeat_interval: 30
  max_queue_size: 50

logging:
  level: "INFO"
```

- [ ] **Step 2: Commit**

```bash
git add config/gsi_config.yaml
git commit -m "feat(gsi): add GSI configuration file"
```

---

### Task 6: GSI HTTP 服务器

**Files:**
- Create: `gsi/server.py`
- Create: `tests/gsi/test_server.py`

- [ ] **Step 1: Create `gsi/server.py`**

```python
"""GSI HTTP 服务器 - 独立 Flask 实例"""

import threading
from typing import Optional

from utils.log_config import get_logger

logger = get_logger("gsi_server", component="gsi")


class GSIServer:
    """GSI HTTP 服务器"""

    def __init__(self, host: str, port: int, token: str,
                 state_manager, event_handler):
        self.host = host
        self.port = port
        self.token = token
        self.state_manager = state_manager
        self.event_handler = event_handler
        self._app = None
        self._thread: Optional[threading.Thread] = None

    def _create_app(self):
        """创建 Flask 应用"""
        from flask import Flask, request, jsonify
        import logging

        app = Flask(__name__)
        logging.getLogger('werkzeug').setLevel(logging.WARNING)

        @app.route('/', methods=['POST'])
        def handle_gsi():
            data = request.json
            if not data:
                return jsonify({"error": "No JSON data"}), 400
            if self.token:
                auth_token = data.get('auth', {}).get('token', '')
                if auth_token != self.token:
                    return jsonify({"error": "Invalid token"}), 403
            self.state_manager.update_state(data)
            return jsonify({"status": "ok"})

        @app.route('/health', methods=['GET'])
        def health():
            state = self.state_manager.get_state()
            return jsonify({
                "status": "ok",
                "connected": self.state_manager.connected,
                "hero": state.hero_name if state else None,
            })

        return app

    def start(self) -> None:
        """后台线程启动 GSI 服务器"""
        if self._thread is not None and self._thread.is_alive():
            return
        self._app = self._create_app()
        def run():
            self._app.run(host=self.host, port=self.port, threaded=True, debug=False, use_reloader=False)
        self._thread = threading.Thread(target=run, daemon=True)
        self._thread.start()
        logger.info(f"GSI 服务器已启动: http://{self.host}:{self.port}")
```

- [ ] **Step 2: Create `tests/gsi/test_server.py`**

```python
"""GSI 服务器测试"""

import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from gsi.server import GSIServer
from gsi.state_manager import GSIStateManager
from gsi.event_handler import GSIEventHandler
from gsi.event_queue import GSIEventQueue


class TestGSIServer:
    def _create_server(self, token="test_token"):
        eq = GSIEventQueue()
        handler = GSIEventHandler(eq)
        manager = GSIStateManager(event_handler=handler)
        server = GSIServer(host="127.0.0.1", port=0, token=token,
                           state_manager=manager, event_handler=handler)
        return server, manager

    def test_valid_token(self):
        server, manager = self._create_server("my_token")
        app = server._create_app()
        with app.test_client() as client:
            resp = client.post('/', json={"auth": {"token": "my_token"}, "hero": {"name": "pudge"}})
            assert resp.status_code == 200

    def test_invalid_token(self):
        server, _ = self._create_server("my_token")
        app = server._create_app()
        with app.test_client() as client:
            resp = client.post('/', json={"auth": {"token": "wrong"}})
            assert resp.status_code == 403

    def test_no_token_required(self):
        server, manager = self._create_server("")
        app = server._create_app()
        with app.test_client() as client:
            resp = client.post('/', json={"hero": {"name": "axe"}})
            assert resp.status_code == 200

    def test_no_json(self):
        server, _ = self._create_server()
        app = server._create_app()
        with app.test_client() as client:
            resp = client.post('/', data="not json", content_type="text/plain")
            assert resp.status_code == 400

    def test_health(self):
        server, _ = self._create_server()
        app = server._create_app()
        with app.test_client() as client:
            resp = client.get('/health')
            assert resp.status_code == 200
            assert json.loads(resp.data)["status"] == "ok"
```

- [ ] **Step 3: Run tests**

Run: `cd d:\trae_projects\first-agent\DotaHelperAgent && python -m pytest tests/gsi/test_server.py -v`
Expected: All tests PASS

- [ ] **Step 4: Commit**

```bash
git add gsi/server.py tests/gsi/test_server.py
git commit -m "feat(gsi): add GSI HTTP server with token auth"
```

---

### Task 7: GSI Agent 工具

**Files:**
- Create: `tools/gsi_tools.py`

- [ ] **Step 1: Create `tools/gsi_tools.py`**

```python
"""GSI Agent 工具 - 提供 Agent 可调用的 GSI 数据访问接口"""

from typing import Dict, Any, List

from tools.base import Tool
from utils.log_config import get_logger

logger = get_logger("gsi_tools", component="tools")


class GSIDataTool(Tool):
    """获取当前游戏实时状态"""

    def __init__(self, state_manager):
        self.state_manager = state_manager
        super().__init__(
            name="get_gsi_state",
            description="获取当前游戏的实时状态数据，包括英雄信息、金钱、血量、技能冷却、物品栏等。仅在游戏进行中可用。",
            parameters={},
            func=self._get_state,
            category="gsi",
            examples=["当前游戏状态怎么样", "我的英雄现在有多少钱"],
        )

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
        self.event_queue = event_queue
        super().__init__(
            name="get_gsi_events",
            description="获取最近的游戏事件列表，如堆野提醒、符文刷新、击杀/死亡等事件。",
            parameters={"count": int},
            func=self._get_events,
            category="gsi",
            examples=["最近有什么游戏事件"],
        )

    def _get_events(self, count: int = 10) -> Dict[str, Any]:
        events = self.event_queue.get_recent(count)
        return {
            "count": len(events),
            "events": [{"type": e.event_type, "message": e.message, "priority": e.priority} for e in events],
        }


def create_gsi_tools(state_manager=None, event_queue=None) -> List[Tool]:
    """创建 GSI 相关的 Agent Tools"""
    tools = []
    if state_manager:
        tools.append(GSIDataTool(state_manager))
    if event_queue:
        tools.append(GSIRecentEventsTool(event_queue))
    return tools
```

- [ ] **Step 2: Commit**

```bash
git add tools/gsi_tools.py
git commit -m "feat(gsi): add GSI agent tools for real-time data access"
```

---

### Task 8: 修改 `tools/agent_tools.py` — 注册 GSI 工具

**Files:**
- Modify: `tools/agent_tools.py`

- [ ] **Step 1: Add GSI parameters to `create_all_tools`**

Find the `create_all_tools` function and add `gsi_state_manager=None, gsi_event_queue=None` parameters, then add GSI tool creation at the end of the function body before `return all_tools`:

```python
    # GSI 工具（可选）
    if gsi_state_manager or gsi_event_queue:
        from tools.gsi_tools import create_gsi_tools
        all_tools.extend(create_gsi_tools(gsi_state_manager, gsi_event_queue))
```

- [ ] **Step 2: Commit**

```bash
git add tools/agent_tools.py
git commit -m "feat(gsi): register GSI tools in create_all_tools"
```

---

### Task 9: 修改 `web/app.py` — GSI 初始化 + SSE 路由

**Files:**
- Modify: `web/app.py`

- [ ] **Step 1: Add GSI imports after Langfuse import block**

After the `LANGFUSE_AVAILABLE` block, add:

```python
# GSI 游戏状态集成（可选）
try:
    import yaml
    from gsi.server import GSIServer
    from gsi.state_manager import GSIStateManager
    from gsi.event_handler import GSIEventHandler
    from gsi.event_queue import GSIEventQueue
    GSI_AVAILABLE = True
except ImportError:
    GSI_AVAILABLE = False
```

- [ ] **Step 2: Add GSI global variables**

After the existing global variables, add:

```python
# GSI 全局变量
gsi_state_manager = None
gsi_event_queue = None
gsi_server = None
```

- [ ] **Step 3: Add `initialize_gsi` function after `initialize_agent_controller`**

```python
def initialize_gsi() -> None:
    """初始化 GSI 游戏状态集成"""
    global gsi_state_manager, gsi_event_queue, gsi_server

    if not GSI_AVAILABLE:
        app_logger.info("GSI 模块不可用，跳过初始化")
        return

    try:
        gsi_config_path = project_root / "config" / "gsi_config.yaml"
        if gsi_config_path.exists():
            with open(gsi_config_path, 'r', encoding='utf-8') as f:
                gsi_config = yaml.safe_load(f)
        else:
            app_logger.warning("GSI 配置文件不存在，使用默认配置")
            gsi_config = {}

        gsi_event_queue = GSIEventQueue(
            max_history=gsi_config.get('state', {}).get('max_history', 100)
        )
        events_config = gsi_config.get('events', {})
        gsi_event_handler = GSIEventHandler(gsi_event_queue, events_config)
        gsi_state_manager = GSIStateManager(event_handler=gsi_event_handler)

        server_config = gsi_config.get('server', {})
        gsi_server = GSIServer(
            host=server_config.get('host', '127.0.0.1'),
            port=server_config.get('port', 3000),
            token=server_config.get('token', ''),
            state_manager=gsi_state_manager,
            event_handler=gsi_event_handler,
        )
        gsi_server.start()
        app_logger.info("GSI 初始化完成")
    except Exception as e:
        app_logger.warning(f"GSI 初始化失败: {e}")
        gsi_state_manager = None
        gsi_event_queue = None
```

- [ ] **Step 4: Call `initialize_gsi()` and pass GSI params in `initialize_agent_controller`**

In `initialize_agent_controller`, before the `tools = create_all_tools(...)` line, add:

```python
        # 初始化 GSI（可选）
        initialize_gsi()
```

And modify the `create_all_tools` call to include:

```python
        tools = create_all_tools(
            hero_analyzer=agent.hero_analyzer,
            item_recommender=agent.item_recommender,
            skill_builder=agent.skill_builder,
            client=agent.client,
            gsi_state_manager=gsi_state_manager,
            gsi_event_queue=gsi_event_queue,
        )
```

- [ ] **Step 5: Add GSI API routes after `/api/health`**

```python
@app.route('/api/gsi/events')
def gsi_event_stream():
    """SSE 推送 GSI 事件到前端"""
    if gsi_event_queue is None:
        return jsonify({"error": "GSI not available"}), 503

    def generate():
        subscriber = gsi_event_queue.subscribe()
        try:
            for event in gsi_event_queue.get_recent(5):
                yield f"event: {event.event_type}\ndata: {json.dumps(event.to_dict())}\n\n"
            while True:
                try:
                    event = subscriber.get(timeout=30)
                    yield f"event: {event.event_type}\ndata: {json.dumps(event.to_dict())}\n\n"
                except queue.Empty:
                    yield "event: heartbeat\ndata: {}\n\n"
        finally:
            gsi_event_queue.unsubscribe(subscriber)

    return Response(
        stream_with_context(generate()),
        mimetype='text/event-stream',
        headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'}
    )


@app.route('/api/gsi/state')
def gsi_state():
    """获取当前 GSI 状态"""
    if gsi_state_manager is None:
        return jsonify({"available": False, "message": "GSI not available"})
    state = gsi_state_manager.get_state()
    if not state:
        return jsonify({"available": False, "connected": gsi_state_manager.connected})
    return jsonify({"available": True, "connected": gsi_state_manager.connected, "state": state.to_dict()})
```

- [ ] **Step 6: Update index endpoint**

Add to the `endpoints` dict in the `index()` function:

```python
            "gsi_events": "/api/gsi/events",
            "gsi_state": "/api/gsi/state",
```

- [ ] **Step 7: Commit**

```bash
git add web/app.py
git commit -m "feat(gsi): integrate GSI initialization, SSE push, and REST API"
```

---

### Task 10: 前端 GSI 类型定义和 SSE 消费

**Files:**
- Create: `frontend/src/types/gsi.ts`
- Create: `frontend/src/composables/useGsiStream.ts`

- [ ] **Step 1: Create `frontend/src/types/gsi.ts`**

```typescript
export interface GSIAbility {
  name: string
  level: number
  can_cast: boolean
  passive: boolean
  cooldown: number
  ultimate: boolean
}

export interface GSIItem {
  name: string
  slot: string
  can_cast: boolean
  cooldown: number
  charges: number
}

export interface GSIGameState {
  map_name: string
  match_id: string
  game_time: number
  clock_time: number
  daytime: boolean
  radiant_score: number
  dire_score: number
  game_state: string
  paused: boolean
  win_team: string
  player_name: string
  steam_id: string
  kills: number
  deaths: number
  assists: number
  last_hits: number
  denies: number
  gold: number
  gold_reliable: number
  gpm: number
  xpm: number
  hero_name: string
  hero_id: number
  level: number
  alive: boolean
  respawn_seconds: number
  health: number
  max_health: number
  mana: number
  max_mana: number
  buyback_cost: number
  abilities: GSIAbility[]
  inventory: GSIItem[]
  updated_at: number
}

export interface GSIEvent {
  event_type: string
  message: string
  priority: 'info' | 'warning' | 'critical'
  data: Record<string, unknown>
  timestamp: number
}

export interface GSIStateResponse {
  available: boolean
  connected: boolean
  state?: GSIGameState
  message?: string
}
```

- [ ] **Step 2: Create `frontend/src/composables/useGsiStream.ts`**

```typescript
import { ref, onUnmounted } from 'vue'
import type { GSIEvent, GSIGameState, GSIStateResponse } from '@/types/gsi'

const baseURL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:5000'

export function useGsiStream() {
  const connected = ref(false)
  const currentState = ref<GSIGameState | null>(null)
  const events = ref<GSIEvent[]>([])
  let eventSource: EventSource | null = null

  const connect = () => {
    if (eventSource) {
      disconnect()
    }

    eventSource = new EventSource(`${baseURL}/api/gsi/events`)

    eventSource.onopen = () => {
      connected.value = true
    }

    // 监听所有 GSI 事件类型
    const eventTypes = [
      'stack', 'rune', 'neutral', 'roshan', 'daytime',
      'kill', 'death', 'item', 'level_up', 'game_start', 'game_end',
    ]

    eventTypes.forEach((type) => {
      eventSource!.addEventListener(type, (e: MessageEvent) => {
        try {
          const data = JSON.parse(e.data) as GSIEvent
          events.value.push(data)
          // 保留最近 100 条
          if (events.value.length > 100) {
            events.value = events.value.slice(-100)
          }
        } catch {
          // ignore parse errors
        }
      })
    })

    eventSource.onerror = () => {
      connected.value = false
    }
  }

  const disconnect = () => {
    if (eventSource) {
      eventSource.close()
      eventSource = null
    }
    connected.value = false
  }

  const fetchState = async () => {
    try {
      const response = await fetch(`${baseURL}/api/gsi/state`)
      const data: GSIStateResponse = await response.json()
      if (data.available && data.state) {
        currentState.value = data.state
        connected.value = data.connected
      } else {
        currentState.value = null
        connected.value = false
      }
    } catch {
      currentState.value = null
      connected.value = false
    }
  }

  onUnmounted(() => {
    disconnect()
  })

  return {
    connected,
    currentState,
    events,
    connect,
    disconnect,
    fetchState,
  }
}
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/types/gsi.ts frontend/src/composables/useGsiStream.ts
git commit -m "feat(gsi): add frontend GSI types and SSE stream composable"
```

---

### Task 11: 前端 TopStatusBar 添加 GSI 状态指示

**Files:**
- Modify: `frontend/src/components/TopStatusBar.vue`

- [ ] **Step 1: Add GSI connection status to TopStatusBar**

In the template, after the existing connection-status span, add:

```html
      <span class="gsi-status" :class="gsiConnected ? 'gsi-connected' : 'gsi-disconnected'" v-if="gsiConnected || gsiChecked">
        <span class="status-dot"></span>
        GSI {{ gsiConnected ? '已连接' : '未连接' }}
      </span>
```

In the script, add:

```typescript
import { useGsiStream } from '@/composables/useGsiStream'

const { connected: gsiConnected, fetchState } = useGsiStream()
const gsiChecked = ref(false)

// 检查 GSI 状态
onMounted(async () => {
  await fetchState()
  gsiChecked.value = true
})
```

Add the import for `onMounted` and `ref` if not already present.

In the style, add:

```css
.gsi-status {
  display: flex;
  align-items: center;
  gap: 5px;
  font-size: 11px;
  color: var(--text-disabled);
  margin-left: var(--gap-sm);
}

.gsi-connected .status-dot {
  background: var(--status-success);
  box-shadow: 0 0 6px rgba(74, 222, 128, 0.4);
}

.gsi-disconnected .status-dot {
  background: var(--text-disabled);
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/TopStatusBar.vue
git commit -m "feat(gsi): add GSI connection status indicator to TopStatusBar"
```

---

### Task 12: 运行全部测试验证

- [ ] **Step 1: Run all GSI tests**

Run: `cd d:\trae_projects\first-agent\DotaHelperAgent && python -m pytest tests/gsi/ -v`
Expected: All tests PASS

- [ ] **Step 2: Run existing tests to verify no regressions**

Run: `cd d:\trae_projects\first-agent\DotaHelperAgent && python -m pytest tests/ -v --ignore=tests/e2e -x`
Expected: No regressions

- [ ] **Step 3: Verify frontend builds**

Run: `cd d:\trae_projects\first-agent\DotaHelperAgent\frontend && npx vue-tsc -b && npx vite build`
Expected: Build succeeds with no errors
