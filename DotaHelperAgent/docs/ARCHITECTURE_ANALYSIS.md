# DotaHelperAgent 待改进事项

> 最后更新：2026-06-11

## 一、待改进优先级

> 更新时间：2026-05-21

| 优先级 | 改进项 | 预计工作量 | 影响 | 状态 |
| --- | --- | --- | --- | --- |
| **P0** | **接入 Langfuse 监控系统** | 中 | 高 | ✅ 已完成 |
| **P0** | **Agent 执行层监控（Langfuse）** | 中 | 高 | ✅ 已完成 |
| **P0** | **工具调用层监控（Langfuse）** | 中 | 高 | ✅ 已完成 |
| **P0** | **Trace 定位与日志追踪体系** | 大 | 高 | ✅ 已完成 |
| **P1** | **GSI 实时游戏状态监控** | 大 | 高 | ❌ 待实现 |
| **P1** | **游戏事件提醒系统** | 中 | 中 | ❌ 待实现 |
| **P1** | **Agent主动推荐机制** | 大 | 高 | ❌ 待实现 |
| **P1** | **GSI数据与Agent结合方案** | 中 | 高 | ❌ 待实现 |
| **P1** | **GSI主动推荐功能PRD** | 大 | 高 | ❌ 待实现 |
| P1 | Prompt 版本管理（Langfuse） | 中 | 中 | ❌ 待实现 |
| P1 | 工具执行并行化 | 中 | 中 | ❌ 待实现 |
| P2 | 前端样式优化 | 中 | 中 | ❌ 待实现 |
| P2 | 用户反馈学习 | 大 | 中 | ❌ 待实现 |
| P2 | 语音提醒系统 | 中 | 低 | ❌ 待实现 |

### 已完成的改进项

| 优先级 | 改进项 | 完成时间 | 代码位置 |
| --- | --- | --- | --- |
| P0 | 工具选择智能化（LLM Function Calling） | 2026-05-17 | `core/llm_tool_selector.py` |
| P1 | 记忆系统深度集成 | 2026-05-17 | `memory/memory.py` |
| P1 | 多轮对话上下文 | 2026-05-17 | `core/conversation_manager.py` + `core/context_augmenter.py` |
| P2 | 反思结果驱动策略调整 | 2026-05-17 | `core/agent_controller.py#_adjust_strategy` |

---

## 二、P0：接入 Langfuse 监控系统 ✅

**实现状态**: ✅ 已完成（2026-05-21）

**代码位置**:
- `utils/langfuse_adapter.py` - Langfuse 适配器（单例模式，可选导入）
- `utils/langfuse_config.py` - 配置管理（支持环境变量 + YAML）
- `config/langfuse_config.yaml` - 配置文件
- `web/app.py` - 集成点（请求追踪、用户反馈）
- `tests/integration/test_langfuse_integration.py` - 集成测试

### 2.1 概述

Langfuse 是一个开源的 LLM 应用可观测性平台，提供：
- **Trace 追踪**：完整记录请求生命周期 ✅
- **Prompt 管理**：版本化 Prompt 模板（待集成）
- **评分系统**：用户反馈和自动评估 ✅
- **成本分析**：Token 使用量和成本统计（待集成）
- **会话分析**：多轮对话上下文追踪 ✅

**官方文档**：https://langfuse.com/docs

### 2.2 实际集成方案

**安装依赖**：
```bash
pip install langfuse
```

**配置文件** (`config/langfuse_config.yaml`):
```yaml
langfuse:
  enabled: true
  host: "http://localhost:3001"
  public_key: "${LANGFUSE_PUBLIC_KEY}"
  secret_key: "${LANGFUSE_SECRET_KEY}"
  trace:
    llm_calls: true
    agent_flow: true
    tool_calls: true
    api_calls: true
  sample_rate: 1.0
```

**核心实现**：

1. **适配器模式** - `utils/langfuse_adapter.py`
```python
class LangfuseClient:
    """Langfuse 客户端单例 - 可选导入"""
    
    @classmethod
    def get_instance(cls) -> "LangfuseClient":
        """获取单例实例"""
        return cls()
    
    def init(self, config: Optional[Dict[str, Any]] = None) -> None:
        """初始化客户端（支持环境变量）"""
        if not LANGFUSE_AVAILABLE:
            logger.info("langfuse SDK 未安装，监控功能已禁用")
            self._enabled = False
            return
        
        # 从配置或环境变量加载密钥
        public_key = config.get('public_key') or os.getenv('LANGFUSE_PUBLIC_KEY')
        secret_key = config.get('secret_key') or os.getenv('LANGFUSE_SECRET_KEY')
        
        # 初始化 Langfuse 客户端
        self._client = Langfuse(
            public_key=public_key,
            secret_key=secret_key,
            host=host
        )
        
        # 认证检查
        if self._client.auth_check():
            self._enabled = True
            logger.info(f"Langfuse 客户端初始化成功")
```

2. **请求级追踪** - `web/app.py`
```python
# 初始化 Langfuse 客户端
if LANGFUSE_AVAILABLE:
    langfuse_config = LangfuseConfig(config_path="config/langfuse_config.yaml")
    langfuse_client = LangfuseClient.get_instance()
    langfuse_client.init(config=langfuse_config.to_dict())

# 在请求中创建 trace
@app.before_request
def before_request():
    if langfuse_client and langfuse_client.enabled:
        g.langfuse_trace = langfuse_client.observation(
            name=f"request_{request.path.replace('/', '_')}",
            as_type="chain",
            metadata={"trace_id": trace_id, "session_id": session_id}
        )

# 请求结束后刷新数据
@app.after_request
def after_request(response):
    if langfuse_client:
        langfuse_client.flush()
    return response
```

3. **用户反馈评分** - `web/app.py`
```python
@app.route('/api/feedback', methods=['POST'])
def submit_feedback():
    """接收用户反馈并记录到 Langfuse"""
    data = request.get_json()
    trace_id = data.get('trace_id')
    score = data.get('score')
    comment = data.get('comment', '')
    
    if langfuse_client and langfuse_client.enabled:
        langfuse_client.score(
            name="user_feedback",
            value=float(score),
            comment=comment
        )
        langfuse_client.flush()
```

### 2.3 已实现的集成点

| 模块 | 集成内容 | 状态 |
| --- | --- | --- |
| `utils/langfuse_adapter.py` | Langfuse 客户端适配器（单例、可选导入） | ✅ 已完成 |
| `utils/langfuse_config.py` | 配置管理（环境变量 + YAML） | ✅ 已完成 |
| `config/langfuse_config.yaml` | 配置文件 | ✅ 已完成 |
| `web/app.py` | 请求追踪、用户反馈收集 | ✅ 已完成 |
| `utils/llm_client.py` | LLM 调用追踪、Token 统计 | ✅ 已完成 |
| `utils/api_client.py` | API 调用追踪（OpenDota） | ✅ 已完成 |
| `tests/integration/test_langfuse_integration.py` | 集成测试 | ✅ 已完成 |
| `core/tool_registry.py` | 工具执行追踪、耗时统计 | ❌ 未集成 |
| `core/agent_controller.py` | ReAct 循环追踪、会话关联 | ❌ 未集成 |
| Prompt 管理 | 版本化 Prompt 模板 | ❌ 未集成 |

### 2.4 特性亮点

1. **可选导入设计** - SDK 未安装时自动降级为 NoOpObservation，不影响项目运行
   ```python
   try:
       from langfuse import Langfuse
       LANGFUSE_AVAILABLE = True
   except ImportError:
       LANGFUSE_AVAILABLE = False
       Langfuse = None
   ```

2. **配置化管理** - 支持环境变量和 YAML 配置文件，灵活切换环境
   ```python
   # 从环境变量加载
   if os.getenv('LANGFUSE_PUBLIC_KEY'):
       config['public_key'] = os.getenv('LANGFUSE_PUBLIC_KEY')
   
   # 从 YAML 文件加载
   with open(config_path, 'r') as f:
       yaml_config = yaml.safe_load(f)
   ```

3. **完整的测试覆盖** - 单元测试 + 集成测试
   - `tests/utils/test_langfuse_adapter.py` - 适配器测试
   - `tests/utils/test_langfuse_config.py` - 配置测试
   - `tests/integration/test_langfuse_integration.py` - 集成测试

### 2.5 预期收益

1. **调试效率提升**：快速定位问题请求 ✅
2. **性能优化**：识别慢查询和瓶颈 ✅（通过 API 调用追踪）
3. **成本控制**：Token 使用量可视化 ✅（在 llm_client.py 中记录 prompt_tokens, completion_tokens, total_tokens）
4. **质量评估**：用户评分 + 自动评估 ✅
5. **Prompt 优化**：版本管理和 A/B 测试 ❌（未集成）

---

## 三、P0：Agent 执行层监控 ✅

**实现状态**: ✅ 已完成（2026-05-26）

**目标**: 在 `agent_controller.py` 中集成 Langfuse，监控 ReAct 循环的每个阶段

**实现位置**: `core/agent_controller.py`

**已实现功能**:
- ✅ 创建 Agent Trace（`langfuse_client.observation(name="react_agent", as_type="agent")`）
- ✅ 监控 solve() 方法的整体执行流程
- ✅ 记录输入参数（query, context）和元数据（session_id, max_turns, trace_id）
- ✅ 创建 Langfuse Span 用于各阶段追踪
- ✅ 与现有 TraceSpan 系统协同工作

**核心代码**:
```python
# core/agent_controller.py - solve() 方法
# 获取 Langfuse 客户端
langfuse_client = LangfuseClient.get_instance() if LANGFUSE_AVAILABLE else None

# 创建 Agent Trace (Langfuse)
if langfuse_client and langfuse_client.enabled:
    agent_trace = langfuse_client.observation(
        name="react_agent",
        as_type="agent",
        input={"query": query, "context": context},
        metadata={
            "session_id": session_id,
            "max_turns": self.max_turns,
            "start_time": datetime.now().isoformat(),
            "trace_id": trace_ctx.trace_id if trace_ctx else None
        }
    )
else:
    agent_trace = NoOpObservation() if NoOpObservation else None
```

**预期收益**:
- ✅ Agent 推理过程可视化
- ✅ 精确定位推理瓶颈
- ✅ 推理质量评估

---

## 四、P0：工具调用层监控 ✅

**实现状态**: ✅ 已完成（2026-05-26）

**目标**: 在 `tool_registry.py` 中集成 Langfuse，监控工具执行情况

**实现位置**: `core/tool_registry.py`

**已实现功能**:
- ✅ 创建工具 Span（`langfuse_client.observation(name=f"tool_{tool_name}", as_type="tool")`）
- ✅ 监控工具调用频率
- ✅ 统计工具执行耗时
- ✅ 追踪工具成功率（通过 `tool_span.score()`）
- ✅ 记录工具参数和返回值预览
- ✅ 异常处理和错误记录

**核心代码**:
```python
# core/tool_registry.py - execute() 方法
# 获取 Langfuse 客户端
langfuse_client = LangfuseClient.get_instance() if LANGFUSE_AVAILABLE else None

# 创建工具 Span (Langfuse)
if langfuse_client and langfuse_client.enabled:
    tool_span = langfuse_client.observation(
        name=f"tool_{tool_name}",
        as_type="tool",
        input=kwargs,
        metadata={
            "trace_id": trace_ctx.trace_id if trace_ctx else None,
            "tool_name": tool_name,
            "category": self._tools.get(tool_name).category if tool_name in self._tools else None,
            "start_time": datetime.now().isoformat()
        }
    )
else:
    tool_span = NoOpObservation() if NoOpObservation else None

# 执行工具后更新 Span
if tool_span and hasattr(tool_span, 'update'):
    tool_span.update(
        output={
            "success": result.is_success(),
            "status": result.status.value,
            "data_preview": str(result.data)[:200] if result.data else None
        },
        metadata={
            "execution_time_ms": round(execution_time * 1000, 2),
            "end_time": datetime.now().isoformat()
        }
    )

# 记录工具评分
if hasattr(tool_span, 'score'):
    tool_span.score(
        name="tool_success",
        value=1.0 if result.is_success() else 0.0,
        comment="工具执行成功" if result.is_success() else f"工具执行失败: {result.error}"
    )
```

**预期收益**:
- ✅ 工具性能分析
- ✅ 工具使用统计
- ✅ 工具优化依据

---

## 五、P0：Trace 定位与日志追踪体系 ✅

**实现状态**: ✅ 已完成（2026-05-26）

**目标**: 建立完整的日志追踪方案，支持根据 trace ID 快速获取完整调用链日志

**实现位置**: 
- `utils/trace_context.py` - Trace 上下文管理（TraceContext, TraceSpan, @traced 装饰器）
- `utils/log_config.py` - TraceJSONFormatter 日志格式化器
- `web/app.py` - Flask 请求级 Trace 初始化与清理、Trace 查询 API
- `core/agent_controller.py` - Agent 执行流程 Span 追踪

**已实现功能**:
- ✅ Trace ID 生成与传递（`generate_trace_id()`, `generate_span_id()`, `generate_session_id()`）
- ✅ 日志与 Trace 关联（TraceJSONFormatter 自动注入 trace_id, span_id, parent_span_id）
- ✅ Span 嵌套追踪（TraceSpan 上下文管理器，支持父子 Span 关系）
- ✅ Trace 查询接口（`GET /api/trace/<trace_id>`, `GET /api/trace/<trace_id>/spans`）
- ✅ 前端 TraceID 传递（X-Trace-ID Header）
- ✅ @traced 装饰器（自动为函数添加 Trace 支持）

**核心代码示例**:
```python
# utils/trace_context.py
@dataclass
class TraceContext:
    """Trace 上下文 - 贯穿请求全生命周期"""
    trace_id: str           # 全局唯一追踪ID
    span_id: str            # 当前操作SpanID
    parent_span_id: Optional[str] = None  # 父SpanID
    session_id: str         # 业务会话ID
    operation: str          # 操作名称
    start_time: float      # 开始时间戳

# 使用 TraceSpan 上下文管理器
with TraceSpan("my_operation"):
    do_something()

# 使用 @traced 装饰器
@traced("my_function")
def my_function():
    do_something()

# 获取当前 Trace 信息
current = get_current_trace()
print(f"Trace ID: {current.trace_id}")
```

**日志输出示例**:
```json
{
    "timestamp": "2026-05-12T10:30:45.123456",
    "level": "INFO",
    "logger": "agent_controller",
    "message": "开始处理查询",
    "trace": {
        "trace_id": "trace_a1b2c3d4e5f67890",
        "span_id": "agent_solve",
        "parent_span_id": null,
        "session_id": "sess_abc123",
        "operation": "agent_solve",
        "duration_ms": 1250
    }
}
```

**预期收益**:
- ✅ 快速定位问题（通过 trace_id 一键查询相关日志）
- ✅ 完整调用链追踪（Span 树结构展示嵌套关系）
- ✅ 日志分析效率提升（JSON 格式便于解析）

---

## 六、P1：Prompt 版本管理 ❌

**目标**: 使用 Langfuse 管理 Prompt 模板，支持版本化和 A/B 测试

**实现位置**: 
- `utils/prompt_manager.py` - Prompt 管理器（新建）
- `config/prompts/` - Prompt 配置目录

**核心功能**:
- Prompt 模板版本管理
- A/B 测试支持
- Prompt 性能追踪
- 自动回滚机制

**示例代码**:
```python
# utils/prompt_manager.py
from langfuse import Langfuse

class PromptManager:
    """Prompt 管理器 - 基于 Langfuse"""
    
    def __init__(self):
        self.client = Langfuse()
    
    def get_prompt(self, name: str, version: str = None) -> str:
        """获取 Prompt 模板"""
        prompt = self.client.get_prompt(name, version=version)
        return prompt.prompt
    
    def create_prompt(self, name: str, prompt: str, config: Dict = None):
        """创建新 Prompt"""
        self.client.create_prompt(
            name=name,
            prompt=prompt,
            config=config
        )
    
    def compare_prompts(self, name: str, versions: List[str], test_cases: List[Dict]):
        """A/B 测试 Prompt"""
        results = []
        for version in versions:
            prompt = self.get_prompt(name, version)
            # 执行测试...
            results.append({"version": version, "score": score})
        return results
```

**预期收益**:
- Prompt 优化有据可依
- 降低 Prompt 变更风险
- 提升 Prompt 质量

---

## 七、P1：GSI 实时游戏状态监控 ❌

**目标**: 集成 Dota 2 游戏状态集成（Game State Integration, GSI）功能，实时监控游戏状态

**参考项目**:
- `dota2gsipy` - GSI HTTP 服务器实现（轻量级、无外部依赖）
- `dota2-game-helper` - 游戏状态处理器实现

**实现位置**: 
- `utils/gsi_client.py` - GSI 客户端（新建）
- `core/gsi_handler.py` - 游戏状态处理器（新建）
- `model/gsi/` - GSI 数据模型（新建）

**核心功能**:
- GSI HTTP 服务器实现（接收 Dota 2 客户端发送的实时游戏数据）
- 游戏状态数据解析（地图、玩家、英雄、技能、物品）
- Token 认证机制（确保数据来源安全）
- 实时数据更新（每次收到请求时更新 game_state 对象）
- Null 值处理（使用 `defaultdict(lambda: None)` 处理缺失数据）

**数据模型**:

| 模块 | 数据字段 | 说明 |
|------|---------|------|
| **Map** | `name`, `match_id`, `game_time`, `clock_time`, `daytime`, `radiant_score`, `dire_score`, `game_state`, `paused`, `win_team`, `ward_purchase_cooldown` | 地图/比赛信息 |
| **Player** | `steam_id`, `name`, `kills`, `deaths`, `assists`, `last_hits`, `denies`, `gold`, `gold_reliable`, `gold_unreliable`, `gold_from_*`, `gpm`, `xpm` | 玩家数据 |
| **Hero** | `pos`, `id`, `name`, `level`, `alive`, `respawn_seconds`, `buyback_cost`, `health`, `mana`, `silenced`, `stunned`, `disarmed`, `aghanims_scepter`, `aghanims_shard`, `talents`, `abilities`, `inventory` | 英雄数据 |
| **Ability** | `name`, `level`, `can_cast`, `passive`, `cooldown`, `ultimate`, `charges` | 技能数据 |
| **Item** | `name`, `purchaser`, `can_cast`, `cooldown`, `passive`, `charges` | 物品数据 |

**集成方案**:

1. **Agent 工具层新增 GSI 数据访问工具**
   ```python
   # tools/gsi_tools.py
   class GSIDataTool:
       """GSI 数据访问工具"""
       
       def get_current_game_state(self) -> Dict[str, Any]:
           """获取当前游戏状态"""
           return self.gsi_client.game_state.to_dict()
       
       def get_hero_position(self) -> Tuple[int, int]:
           """获取英雄当前位置"""
           return self.gsi_client.game_state.hero.pos
       
       def get_hero_health(self) -> Dict[str, int]:
           """获取英雄生命值"""
           return {
               "health": self.gsi_client.game_state.hero.health,
               "max_health": self.gsi_client.game_state.hero.max_health,
               "health_percent": self.gsi_client.game_state.hero.health_percent
           }
   ```

2. **实时游戏状态监控**
   ```python
   # core/gsi_handler.py
   class GSIHandler:
       """游戏状态处理器"""
       
       def on_game_state_update(self, game_state: GameState):
           """游戏状态更新回调"""
           # 检查游戏状态变化
           if game_state.map.game_state == GameStateEnum.DOTA_GAMERULES_STATE_GAME_IN_PROGRESS:
               # 游戏进行中，触发事件提醒
               self.check_game_events(game_state)
   ```

**预期收益**:
- 实时游戏状态监控（了解当前游戏情况）
- 基于实时数据的智能推荐（根据当前英雄状态推荐出装、技能加点）
- 游戏事件提醒（堆野、符文、中立物品等）
- 增强用户体验（实时交互）

---

## 八、P1：游戏事件提醒系统 ❌

**目标**: 基于游戏状态监控，提供游戏事件提醒功能

**参考项目**: `dota2-game-helper` - 游戏事件处理器实现

**实现位置**: `core/gsi_handler.py` - 游戏状态处理器（扩展）

**核心功能**:
- 堆野提醒（每分钟堆野时间点提醒）
- 符文提醒（中符、赏金符、智慧符、莲花）
- 中立物品提醒（中立物品刷新时间点提醒）
- 白天/夜晚切换提醒（昼夜切换提醒）
- 肉山复活提醒（肉山死亡后复活时间提醒）
- Tormentor 提醒（第一波 Tormentor 时间点提醒）
- Shard 提醒（Shard 可用时间点提醒）
- Ward purchase 提醒（眼购买冷却结束提醒）

**事件处理逻辑**:

```python
# core/gsi_handler.py
class GameStateHandler:
    """游戏状态处理器"""
    
    def __init__(self):
        self.game_start_alarmed = False
        self.daytime_alarmed = False
        self.nighttime_alarmed = False
        self.last_roshan_dead_time = None
        self.past_event_keys = set()
    
    def handle_stack(self, game_time: int):
        """堆野提醒"""
        stack_time = 60  # 每分钟堆野
        stack_alarm_time = stack_time - self.config.stack_delay
        if (game_time - stack_alarm_time) % stack_time == 0:
            self.trigger_event("stack")
    
    def handle_mid_runes(self, game_time: int):
        """中符提醒"""
        mid_runes_time = 120  # 每2分钟中符
        mid_runes_alarm_time = mid_runes_time - self.config.mid_runes_delay
        if (game_time - mid_runes_alarm_time) % mid_runes_time == 0:
            self.trigger_event("mid_runes")
    
    def handle_roshan(self, game_time: int):
        """肉山复活提醒"""
        if self.last_roshan_dead_time is not None:
            roshan_respawn_time = self.last_roshan_dead_time + random.randint(480, 720)  # 8-12分钟
            if game_time >= roshan_respawn_time:
                self.trigger_event("roshan_respawn")
                self.last_roshan_dead_time = None
```

**配置化管理**:

```python
# config/gsi_config.yaml
gsi:
  enabled: true
  events:
    stack_active: true
    stack_delay: 10  # 提前10秒提醒
    mid_runes_active: true
    mid_runes_delay: 15
    bounty_runes_active: true
    wisdom_runes_active: true
    lotus_active: true
    neutral_items_active: [true, true, true]  # 三波中立物品
    daytime_active: true
    roshan_active: true
    first_tormentor_active: true
    shard_active: true
    ward_purchase_active: true
```

**预期收益**:
- 游戏节奏提醒（帮助玩家掌握游戏节奏）
- 资源获取提醒（符文、中立物品、肉山等）
- 时间管理优化（堆野、昼夜切换等）

---

## 九、P1：Agent主动推荐机制 ❌

**目标**: 在游戏过程中，Agent自动推送建议，无需用户主动输入问题

**核心思路**:

| 推荐模式 | 触发条件 | 推送内容示例 |
|---------|---------|-------------|
| **基于游戏事件** | 堆野、符文、肉山等关键事件 | "堆野时间到了！建议前往野区堆野" |
| **基于状态变化** | 血量<30%、金钱>=装备价格、技能冷却结束 | "血量过低！建议立即回城补给" |
| **基于游戏阶段** | 对线期、中期、后期、决胜期 | "中期！建议参团，协助团队推进" |
| **基于团队状态** | 团队领先/劣势、团队状态良好/不佳 | "团队领先！建议主动推塔，扩大优势" |
| **基于用户行为** | 用户连续3次错过堆野/符文 | "你最近3次都忘记堆野了，建议这次去堆野" |

**技术实现**:
- WebSocket实时推送（双向通信）
- SSE流式推送（单向推送）
- 桌面通知推送（Windows通知）

**预期变化**:
- Agent从"被动响应"升级为"主动推送"
- 用户无需主动输入问题，Agent自动推送建议
- 实时游戏状态监控，主动推送策略建议
- 基于用户行为模式提供个性化建议
- 大幅提升用户体验和实用性

---

## 十、P1：GSI数据与Agent结合方案 ❌

**目标**: 将GSI实时数据与Agent工具结合，提供实时问答和策略建议

**核心思路**:

| 结合方式 | 用户查询示例 | Agent回答示例（基于GSI数据） |
|---------|-------------|----------------------------|
| **实时数据驱动** | "我血量只有30%，该怎么办？" | "建议回城补给，或使用治疗药膏/魔瓶" |
| **游戏事件策略** | "堆野时间到了！" | "建议前往野区堆野，优先堆大野点（距离500码）" |
| **实时问答** | "我现在等级多少？" | "你当前等级：12级，经验值：8500/10000" |
| **整体策略建议** | "我现在应该做什么？" | "根据当前状态（等级12、金钱2500、血量80%），建议：1.购买BKB；2.前往中符位置；3.准备团战" |

**新增工具**:
- `GSIDataTool` - 获取英雄状态、游戏时间、玩家数据、技能冷却、物品状态
- `GameEventStrategyTool` - 堆野策略、符文策略、肉山策略建议
- `OverallStrategyTool` - 根据综合状态提供整体策略建议

**预期变化**:
- Agent从"静态问答助手"升级为"实时游戏助手"
- 实时交互能力增强，根据游戏状态回答问题
- 个性化建议，根据用户当前状态提供建议
- 游戏节奏掌握优化，帮助用户掌握游戏节奏

---

## 十一、P1：GSI主动推荐功能PRD ❌

**目标**: 实现基于GSI的Agent主动推荐系统，提供游戏过程中的智能建议推送

### Problem Statement

**问题**: 在Dota 2游戏过程中，用户很少会主动打字或语音输入问题，导致Agent无法及时提供帮助。用户需要一种机制，让Agent能够自动感知游戏状态并主动推送建议，而不是等待用户触发。

**用户视角**: "我在游戏时很忙，没时间打字问问题。我希望Agent能自动告诉我什么时候该堆野、什么时候该去抢符、什么时候该参团，而不是我每次都要主动问。"

### Solution

**核心思路**: Agent主动感知游戏状态，基于LLM生成个性化建议，通过桌面通知和语音提醒推送给用户。

**关键特性**:
- 实时游戏状态监控（GSI集成）
- LLM驱动的个性化建议生成
- 多渠道推送（桌面通知 + 语音提醒）
- 用户行为模式学习
- 可配置化的提醒设置

### User Stories

**游戏事件提醒**:
1. As a Dota 2 player, I want Agent to remind me when to stack camps (every minute), so that I can maximize my farm efficiency.
2. As a Dota 2 player, I want Agent to remind me when runes spawn (mid runes every 2 minutes, bounty/wisdom/lotus every 3 minutes), so that I can contest them.
3. As a Dota 2 player, I want Agent to remind me when neutral items spawn (5/15/25/35/45 minutes), so that I can get the best items for my hero.

**游戏阶段提醒**:
4. As a Dota 2 player, I want Agent to remind me during laning phase (0-10 minutes) to focus on farming and buying core items.
5. As a Dota 2 player, I want Agent to remind me during mid game (10-20 minutes) to participate in teamfights and push towers.

### Implementation Decisions

**模块设计**:
- **GSI HTTP Server**: Flask-based HTTP server to receive GSI data from Dota 2 client (port: 5001)
- **GSI Data Parser**: Parse raw GSI JSON data into structured GameState object
- **Game Event Detector**: Detect game events (stack, runes, neutral items, Roshan, Tormentor) based on game time
- **LLM Suggestion Generator**: **核心模块** - Use LLM to generate natural language suggestions based on context
- **Personalization Engine**: Personalize suggestions based on user behavior pattern, current state, hero type, and playstyle
- **Desktop Notification Sender**: Send Windows desktop notifications with configurable duration and icons
- **Voice Player**: Play voice reminders in multiple languages (Chinese, English, custom)

**建议生成流程**:
```
游戏事件触发
    │
    ▼
┌─────────────────┐
│  事件检测器      │
│  - 检测事件类型  │
│  - 提取游戏时间  │
└─────────────────┘
    │
    ▼
┌─────────────────┐
│  上下文构建器    │
│  - 游戏状态数据  │
│  - 用户行为模式  │
│  - 英雄类型      │
│  - 游戏风格      │
└─────────────────┘
    │
    ▼
┌─────────────────┐
│  LLM建议生成器   │  ⭐ 核心模块
│  - 构造Prompt    │
│  - 调用LLM       │
│  - 解析建议内容  │
└─────────────────┘
    │
    ▼
┌─────────────────┐
│  个性化引擎      │
│  - 调整建议语气  │
│  - 优化建议内容  │
└─────────────────┘
    │
    ▼
┌─────────────────┐
│  推送调度器      │
│  - 确定优先级    │
│  - 设置延迟      │
│  - 调度推送      │
└─────────────────┘
    │
    ▼
┌─────────────────┐
│  推送执行        │
│  - 桌面通知      │
│  - 语音播放      │
└─────────────────┘
```

**LLM Prompt示例**:
```python
# 堆野建议Prompt
STACK_PROMPT = """你是一个Dota 2游戏教练，正在指导玩家堆野。

## 当前游戏状态
- 游戏时间：{game_time}秒
- 英雄：{hero_name}（{hero_type}）
- 血量：{health_percent}%
- 金钱：{gold}
- 位置：{hero_position}

## 用户行为模式
- 最近3次堆野：{stack_behavior}（成功/失败/错过）
- 游戏风格：{playstyle}（打钱型/参团型）

## 任务
根据以上信息，生成一个堆野建议（不超过20字），要求：
1. 根据用户行为模式提供针对性建议
2. 根据英雄类型调整建议重点
3. 根据游戏风格优化建议语气
4. 使用自然、流畅的语言

## 示例输出
- "堆野时间到了！你最近3次都错过堆野了，建议这次去堆野提升经济"
- "堆野提醒！作为核心英雄，建议优先堆大野点，提升打钱效率"
- "堆野时间！血量充足（80%），建议前往野区堆野"
"""
```

### Out of Scope

- **WebSocket Push**: Not implementing WebSocket push (using desktop notifications and voice instead)
- **SSE Push**: Not implementing SSE push (using desktop notifications and voice instead)
- **State Change Reminders**: Not implementing state change reminders (health, gold, skill cooldown, level up) - focusing on game events, game phases, and team states only
- **STRATZ API Integration**: Not integrating STRATZ API for game data (using Dota 2 client GSI only)
- **Mobile Notifications**: Not implementing mobile notifications (Windows desktop only)
- **Multi-user Support**: Not implementing multi-user support (single-user mode only)
- **Cloud Storage**: Not implementing cloud storage for behavior history (SQLite local storage only)

---

## 十二、P1：工具执行并行化 ❌

**目标**: 实现工具并行执行，提升Agent响应速度

**实现位置**: `core/agent_controller.py` - 并行执行器

**核心功能**:
- 依赖分析（识别哪些工具可以并行执行）
- 拓扑排序（确定执行顺序）
- 并发控制（限制并发数量，避免资源耗尽）
- 超时管理（防止单个工具阻塞整个流程）

**预期收益**:
- 性能提升 50-80%
- 响应时间缩短
- 资源利用率提高

---

## 十三、P2：前端样式优化 ❌

**目标**: 优化前端界面样式，提升用户体验

**实现位置**: `frontend/src/` - 前端源码

**核心功能**:
- 响应式布局适配
- 暗色主题支持
- 交互反馈优化（加载动画、hover 效果）
- 消息展示美化（Markdown 渲染、代码高亮）
- 英雄/物品卡片样式优化

**预期收益**:
- 用户体验提升
- 视觉效果优化
- 交互流畅度提升

---

## 十四、P2：用户反馈学习 ❌

**目标**: 基于用户反馈优化Agent表现

**实现位置**: 
- `core/feedback_learner.py` - 反馈学习器（新建）
- `memory/feedback_store.py` - 反馈存储（新建）

**核心功能**:
- 用户反馈收集（评分、评论）
- 反馈分析（识别常见问题）
- 自动优化（调整工具权重、Prompt模板）
- A/B测试（验证优化效果）

**预期收益**:
- Agent表现持续优化
- 用户满意度提升
- 问题自动识别与修复

---

## 十五、P2：语音提醒系统 ❌

**目标**: 提供语音提醒功能，增强游戏事件提醒的感知度

**参考项目**: `dota2-game-helper` - 语音播放实现

**实现位置**: `utils/voice_player.py` - 语音播放器（新建）

**核心功能**:
- 语音播放功能（播放预录制的语音文件）
- 可配置化的提醒开关（用户可选择开启/关闭特定提醒）
- 多语言支持（中文、英文）

**语音资源**:

| 事件类型 | 语音文件 | 说明 |
|---------|---------|------|
| 游戏开始 | `prologue.wav` | 游戏开始提醒 |
| 堆野 | `alarm_stack.wav` | 堆野提醒 |
| 中符 | `alarm_mid_runes.wav` | 中符刷新提醒 |
| 财神符 | `alarm_bounty_runes.wav` | 财神符刷新提醒 |
| 智慧符 | `alarm_wisdom_runes.wav` | 智慧符刷新提醒 |
| 莲花 | `alarm_lotus.wav` | 莲花刷新提醒 |
| 中立物品 | `alarm_neutral_items.wav` | 中立物品刷新提醒 |
| 白天 | `alarm_daytime.wav` | 白天切换提醒 |
| 夜晚 | `alarm_night_time.wav` | 夜晚切换提醒 |
| 肉山 | `alarm_roshan.wav` | 肉山复活提醒 |
| Tormentor | `alarm_first_tormentor.wav` | Tormentor 提醒 |
| Shard | `alarm_shard.wav` | Shard 提醒 |
| 眼购买 | `alarm_ward_purchase.wav` | 眼购买冷却结束提醒 |

**实现方案**:

```python
# utils/voice_player.py
import pygame
import os

class VoicePlayer:
    """语音播放器"""
    
    def __init__(self, resources_dir: str = "resources/"):
        self.resources_dir = resources_dir
        pygame.mixer.init()
    
    def play(self, voice_type: str):
        """播放语音"""
        voice_file = os.path.join(self.resources_dir, f"{voice_type}.wav")
        if os.path.exists(voice_file):
            pygame.mixer.Sound(voice_file).play()
        else:
            logging.warning(f"Voice file not found: {voice_file}")
```

**预期收益**:
- 提醒感知度增强（语音比文字更直观）
- 游戏节奏掌握优化（及时响应游戏事件）
- 用户体验提升（多感官交互）
