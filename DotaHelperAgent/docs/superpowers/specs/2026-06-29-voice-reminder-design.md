# 语音提醒系统设计文档

> **版本**: v1.0  
> **创建时间**: 2026-06-29  
> **状态**: 设计中

---

## 一、概述

### 1.1 目标

为 DotaHelperAgent 添加语音提醒功能，在游戏事件发生时播放对应的语音提示，增强用户的游戏体验。

### 1.2 核心需求

- 在 GSI EventHandler 层触发语音播放（与推荐系统解耦）
- 支持 13 种游戏事件的语音提醒
- 配置文件控制默认开关和音量
- Web API 支持运行时动态调整
- pygame 未安装时静默降级

### 1.3 设计原则

- **独立模块**：VoicePlayer 是独立工具类，不依赖 GSI 模块
- **依赖注入**：EventHandler 通过构造函数接收 VoicePlayer 实例
- **降级策略**：pygame 导入失败时，所有方法变为空操作
- **可配置性**：语音文件路径可配置，支持后续替换自定义语音

---

## 二、架构设计

### 2.1 模块架构

```
┌─────────────────────────────────────────────────────────┐
│                  GSIEventHandler                        │
│  - 检测游戏事件                                         │
│  - 调用 VoicePlayer.play(event_type)                   │
│  - 调用 EventQueue.put(event)                          │
└─────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────┐
│                  VoicePlayer                            │
│  - pygame.mixer 初始化                                  │
│  - 事件类型 → wav 文件映射                              │
│  - 音量控制                                             │
│  - 启用/禁用控制                                        │
└─────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────┐
│              resources/voice/*.wav                      │
│  - alarm_stack.wav, alarm_mid_runes.wav, ...           │
│  - 可配置路径，支持后续替换                             │
└─────────────────────────────────────────────────────────┘
```

### 2.2 数据流

```
游戏状态变化
    ↓
GSIEventHandler.on_game_time_tick() / on_game_state_changed()
    ↓
检测事件（堆野、符文、肉山等）
    ↓
├─→ VoicePlayer.play(event_type)  [语音播放]
└─→ EventQueue.put(event)         [事件入队，供推荐系统使用]
```

---

## 三、VoicePlayer 接口设计

### 3.1 类定义

```python
class VoicePlayer:
    """语音播放器 - 负责音频播放"""
    
    def __init__(self, config: Dict[str, Any] = None):
        """
        初始化播放器
        
        Args:
            config: 配置字典，包含：
                - enabled: 是否启用语音（默认 True）
                - volume: 音量 0.0-1.0（默认 0.7）
                - resources_dir: 语音文件目录（默认 "resources/voice"）
                - events: 各事件类型的启用状态字典
        """
        pass
    
    def play(self, event_type: str) -> None:
        """
        播放指定事件类型的语音
        
        Args:
            event_type: 事件类型（如 "stack", "rune_mid", "roshan"）
        
        行为：
        - 检查全局启用状态
        - 检查该事件类型是否启用
        - 查找对应的 wav 文件
        - 异步播放（不阻塞调用线程）
        - pygame 未安装时静默跳过
        """
        pass
    
    def set_enabled(self, enabled: bool) -> None:
        """运行时设置全局启用状态"""
        pass
    
    def set_volume(self, volume: float) -> None:
        """运行时设置音量（0.0-1.0）"""
        pass
    
    def set_event_enabled(self, event_type: str, enabled: bool) -> None:
        """运行时设置指定事件类型的启用状态"""
        pass
    
    def get_status(self) -> Dict[str, Any]:
        """
        获取播放器状态
        
        Returns:
            {
                "enabled": bool,
                "volume": float,
                "pygame_available": bool,
                "event_settings": Dict[str, bool]
            }
        """
        pass
```

### 3.2 关键设计点

- **异步播放**：pygame 的 `Sound.play()` 本身是非阻塞的
- **降级策略**：pygame 导入失败时，`_PYGAME_AVAILABLE = False`，所有方法变为空操作
- **线程安全**：pygame.mixer 内部已处理线程同步

---

## 四、事件类型映射

### 4.1 事件类型 → 语音文件映射表

| 事件类型 | 语音文件 | 说明 |
|---------|---------|------|
| `game_start` | `prologue.wav` | 游戏开始 |
| `stack` | `alarm_stack.wav` | 堆野 |
| `rune_mid` | `alarm_mid_runes.wav` | 中符 |
| `rune_bounty` | `alarm_bounty_runes.wav` | 财神符 |
| `rune_wisdom` | `alarm_wisdom_runes.wav` | 智慧符 |
| `rune_lotus` | `alarm_lotus.wav` | 莲花 |
| `neutral` | `alarm_neutral_items.wav` | 中立物品 |
| `daytime` | `alarm_daytime.wav` | 白天 |
| `nighttime` | `alarm_night_time.wav` | 夜晚 |
| `roshan` | `alarm_roshan.wav` | 肉山 |
| `tormentor` | `alarm_first_tormentor.wav` | Tormentor |
| `shard` | `alarm_shard.wav` | Shard |
| `ward_purchase` | `alarm_ward_purchase.wav` | 眼购买 |

### 4.2 EventHandler 事件类型拆分

当前 EventHandler 的符文事件统一用 `event_type="rune"`，需要拆分为四个子类型：

**改动前**：
```python
self._emit("rune", "中符刷新了！", "info")
```

**改动后**：
```python
self._emit("rune_mid", "中符刷新了！", "info")
self._emit("rune_bounty", "财神符刷新了！", "info")
self._emit("rune_wisdom", "智慧符刷新了！", "info")
self._emit("rune_lotus", "莲花刷新了！", "info")
```

昼夜事件同理，拆分为 `daytime` 和 `nighttime`：

**改动前**：
```python
label = "白天" if state.daytime else "夜晚"
self._emit("daytime", f"切换到{label}", "info")
```

**改动后**：
```python
if state.daytime:
    self._emit("daytime", "切换到白天", "info")
else:
    self._emit("nighttime", "切换到夜晚", "info")
```

---

## 五、配置设计

### 5.1 配置文件 `config/gsi_config.yaml` 新增部分

```yaml
voice:
  enabled: true
  volume: 0.7
  resources_dir: "resources/voice"
  events:
    game_start: true
    stack: true
    rune_mid: true
    rune_bounty: true
    rune_wisdom: true
    rune_lotus: true
    neutral: true
    daytime: true
    nighttime: true
    roshan: true
    tormentor: true
    shard: true
    ward_purchase: true
    kill: false
    death: true
    level_up: true
```

### 5.2 配置项说明

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `enabled` | bool | true | 全局语音开关 |
| `volume` | float | 0.7 | 音量（0.0-1.0） |
| `resources_dir` | string | "resources/voice" | 语音文件目录路径 |
| `events` | dict | - | 各事件类型的启用状态 |

---

## 六、Web API 设计

### 6.1 API 端点

| 端点 | 方法 | 功能 | 请求体 | 响应 |
|------|------|------|--------|------|
| `/api/voice/status` | GET | 获取语音播放器状态 | - | `{"enabled": bool, "volume": float, "pygame_available": bool, "event_settings": dict}` |
| `/api/voice/toggle` | POST | 全局开关 | `{"enabled": bool}` | `{"success": true, "enabled": bool}` |
| `/api/voice/volume` | POST | 设置音量 | `{"volume": float}` | `{"success": true, "volume": float}` |
| `/api/voice/event` | POST | 设置单个事件类型开关 | `{"event_type": str, "enabled": bool}` | `{"success": true, "event_type": str, "enabled": bool}` |

### 6.2 API 示例

**获取状态**：
```bash
curl http://localhost:5000/api/voice/status
```

**全局开关**：
```bash
curl -X POST http://localhost:5000/api/voice/toggle \
  -H "Content-Type: application/json" \
  -d '{"enabled": false}'
```

**设置音量**：
```bash
curl -X POST http://localhost:5000/api/voice/volume \
  -H "Content-Type: application/json" \
  -d '{"volume": 0.5}'
```

**设置事件开关**：
```bash
curl -X POST http://localhost:5000/api/voice/event \
  -H "Content-Type: application/json" \
  -d '{"event_type": "stack", "enabled": true}'
```

---

## 七、集成方案

### 7.1 EventHandler 改造

**改动点**：
1. 构造函数新增 `voice_player` 参数（可选）
2. 在 `_emit()` 方法中调用 `voice_player.play(event_type)`
3. 拆分事件类型（rune → rune_mid/rune_bounty/rune_wisdom/rune_lotus）
4. 拆分昼夜事件（daytime → daytime/nighttime）

**代码示例**：
```python
class GSIEventHandler:
    def __init__(self, event_queue: GSIEventQueue, config: Dict[str, Any] = None, 
                 voice_player: 'VoicePlayer' = None):
        self.event_queue = event_queue
        self.config = config or {}
        self.voice_player = voice_player
        # ... 其他初始化代码
    
    def _emit(self, event_type: str, message: str, priority: str) -> None:
        # 播放语音
        if self.voice_player:
            self.voice_player.play(event_type)
        
        # 事件入队
        event = GSIEvent(event_type=event_type, message=message, priority=priority)
        self.event_queue.put(event)
        logger.debug(f"GSI 事件: [{priority}] {event_type} - {message}")
```

### 7.2 web/app.py 集成

**启动时初始化**：
```python
from utils.voice_player import VoicePlayer

# 初始化语音播放器
voice_config = app.config.get('GSI_CONFIG', {}).get('voice', {})
voice_player = VoicePlayer(voice_config)

# 注入到 EventHandler
event_handler = GSIEventHandler(event_queue, gsi_config, voice_player=voice_player)

# 注册 API 端点
@app.route('/api/voice/status', methods=['GET'])
def get_voice_status():
    return jsonify(voice_player.get_status())

@app.route('/api/voice/toggle', methods=['POST'])
def toggle_voice():
    data = request.get_json()
    enabled = data.get('enabled', True)
    voice_player.set_enabled(enabled)
    return jsonify({"success": True, "enabled": enabled})

@app.route('/api/voice/volume', methods=['POST'])
def set_volume():
    data = request.get_json()
    volume = data.get('volume', 0.7)
    voice_player.set_volume(volume)
    return jsonify({"success": True, "volume": volume})

@app.route('/api/voice/event', methods=['POST'])
def set_event_enabled():
    data = request.get_json()
    event_type = data.get('event_type')
    enabled = data.get('enabled', True)
    voice_player.set_event_enabled(event_type, enabled)
    return jsonify({"success": True, "event_type": event_type, "enabled": enabled})
```

---

## 八、语音资源

### 8.1 资源来源

从参考项目 `out_project/dota2-game-helper-main/resources/` 复制 13 个 wav 文件到 `DotaHelperAgent/resources/voice/`：

- `prologue.wav`
- `alarm_stack.wav`
- `alarm_mid_runes.wav`
- `alarm_bounty_runes.wav`
- `alarm_wisdom_runes.wav`
- `alarm_lotus.wav`
- `alarm_neutral_items.wav`
- `alarm_daytime.wav`
- `alarm_night_time.wav`
- `alarm_roshan.wav`
- `alarm_first_tormentor.wav`
- `alarm_shard.wav`
- `alarm_ward_purchase.wav`

### 8.2 可配置路径

配置文件中的 `resources_dir` 支持相对路径和绝对路径，方便后续替换自定义语音文件。

---

## 九、测试策略

### 9.1 单元测试 `tests/utils/test_voice_player.py`

**测试用例**：
1. 初始化测试（默认配置、自定义配置）
2. pygame 可用时的播放测试
3. pygame 不可用时的降级测试
4. 全局开关测试
5. 音量控制测试
6. 事件类型开关测试
7. 状态查询测试
8. 文件不存在时的处理测试

### 9.2 集成测试 `tests/integration/test_voice_integration.py`

**测试用例**：
1. EventHandler 与 VoicePlayer 集成测试
2. 事件触发语音播放链路测试
3. Web API 控制语音播放器测试
4. 配置文件加载测试

---

## 十、依赖管理

### 10.1 requirements.txt 新增

```
pygame>=2.0.0
```

### 10.2 requirements-optional.txt 新增

```
# 语音提醒系统（可选）
pygame>=2.0.0
```

---

## 十一、实施计划

### 11.1 任务分解

1. **创建 VoicePlayer 模块**（utils/voice_player.py）
   - 实现初始化、播放、控制方法
   - 实现降级策略
   - 添加类型提示

2. **复制语音资源**
   - 创建 `resources/voice/` 目录
   - 从参考项目复制 13 个 wav 文件

3. **改造 EventHandler**
   - 新增 `voice_player` 参数
   - 在 `_emit()` 中调用语音播放
   - 拆分事件类型（rune、daytime）

4. **更新配置文件**
   - 在 `config/gsi_config.yaml` 中新增 voice 配置段

5. **集成到 web/app.py**
   - 初始化 VoicePlayer
   - 注入到 EventHandler
   - 注册 4 个 API 端点

6. **编写测试**
   - 单元测试（test_voice_player.py）
   - 集成测试（test_voice_integration.py）

7. **更新依赖文件**
   - requirements.txt
   - requirements-optional.txt

### 11.2 验收标准

- [ ] VoicePlayer 可独立初始化和播放
- [ ] pygame 未安装时静默降级
- [ ] EventHandler 事件触发语音播放
- [ ] 配置文件控制默认开关和音量
- [ ] Web API 支持运行时调整
- [ ] 单元测试覆盖率 > 80%
- [ ] 集成测试通过

---

## 十二、未来扩展

### 12.1 可能的增强方向

- 支持 TTS（文本转语音）动态生成语音
- 支持多语言语音包
- 支持自定义语音文件映射
- 前端语音设置面板
- 语音播放历史记录

---

## 附录

### A. 参考项目

- 路径：`out_project/dota2-game-helper-main/`
- 关键文件：`gsi/speaker.py`（VoiceManager 实现）
- 语音文件：`resources/*.wav`

### B. 相关文档

- [ARCHITECTURE_ANALYSIS.md](../../ARCHITECTURE_ANALYSIS.md) - 第十五章：语音提醒系统
- [2026-06-22-proactive-recommendation-design.md](./2026-06-22-proactive-recommendation-design.md) - 主动推荐系统设计
