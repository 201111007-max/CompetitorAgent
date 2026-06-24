# Agent 主动推荐机制设计文档

> **版本**: v1.0  
> **日期**: 2026-06-22  
> **状态**: 待审核  
> **优先级**: P1  
> **所属阶段**: 第三阶段 — 推理和决策能力增强

---

## 一、问题陈述

### 1.1 当前问题

当前 DotaHelperAgent 采用**被动查询模式**：

```
用户提问 → AgentController.solve() → 工具调用 → 返回结果
```

**核心痛点**：
- ❌ 即使 GSI 事件队列中已有堆野/符文等事件，也不会主动触发推荐
- ❌ 用户需要手动提问才能获得建议，错过最佳时机
- ❌ 无法基于实时局势变化主动预警（如低血量、敌方消失等）
- ❌ 缺乏数据驱动的决策支持（胜率预测、出装对比等）

### 1.2 目标

将 Agent 从"被动查询助手"升级为"智能决策推荐系统"：

```
GSI 事件流 → 事件触发器 → 决策引擎 → 决策融合 → 主动推送给用户
                                                    ↑
                              知识库 + 历史数据 + LLM 推理
```

**预期收益**：
- ✅ 实时局势感知，主动提供建议
- ✅ 关键事件及时预警（低血量、敌方消失等）
- ✅ 数据驱动决策（胜率预测、出装对比）
- ✅ 个性化推荐（基于用户历史对局）

---

## 二、技术决策

| 决策项 | 选择 | 理由 |
|--------|------|------|
| 触发机制 | 事件驱动（订阅 GSI 事件队列） | 复用已有基础设施，低延迟 |
| 决策引擎 | 混合推理（规则 + 数据 + LLM） | 兼顾速度、准确性和灵活性 |
| 融合策略 | 加权融合 + 冲突解决 | 多源决策互补，提高可靠性 |
| 推送通道 | SSE（Server-Sent Events） | 复用已有 SSE 基础设施 |
| 配置管理 | YAML 配置文件 | 与项目现有模式一致 |

---

## 三、系统架构

### 3.1 整体架构图

```
┌─────────────────────────────────────────────────────────────────────┐
│                        GSI 事件流                                    │
│  (堆野、符文、击杀、死亡、购买、低血量、敌方消失等)                      │
└────────────────────────────┬────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│                   事件触发器 (EventTrigger)                          │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐              │
│  │ 事件过滤      │→│ 阈值判断      │→│ 冷却控制      │              │
│  └──────────────┘  └──────────────┘  └──────────────┘              │
└────────────────────────────┬────────────────────────────────────────┘
                             │ 触发推荐请求
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      决策引擎层 (Decision Engines)                   │
│                                                                     │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐              │
│  │ 规则推理引擎  │  │ 数据驱动引擎  │  │ LLM 增强引擎  │              │
│  │              │  │              │  │              │              │
│  │ - 领域知识   │  │ - 胜率预测   │  │ - 知识检索   │              │
│  │ - 专家规则   │  │ - 出装对比   │  │ - 复杂推理   │              │
│  │ - 快速响应   │  │ - 个性化推荐  │  │ - 长尾场景   │              │
│  └──────────────┘  └──────────────┘  └──────────────┘              │
│         │                  │                  │                     │
│         └──────────────────┼──────────────────┘                     │
└────────────────────────────┼────────────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    决策融合器 (DecisionFusion)                       │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐              │
│  │ 置信度评估    │→│ 加权融合      │→│ 冲突解决      │              │
│  └──────────────┘  └──────────────┘  └──────────────┘              │
└────────────────────────────┬────────────────────────────────────────┘
                             │
                    ┌────────┴────────┐
                    ▼                 ▼
┌───────────────────────────┐  ┌───────────────────────────────────┐
│  SSE 推送通道              │  │  Agent 工具层                      │
│  (/api/gsi/recommendations│  │  (RecommendationQueryTool)        │
│   → 前端实时展示)          │  │  Agent 推理时获取推荐建议          │
└───────────────────────────┘  └───────────────────────────────────┘
```

### 3.2 数据流

```
GSI 事件队列 (gsi/event_queue.py)
    │ 订阅事件流
    ▼
事件触发器 (core/event_trigger.py)
    │ 过滤 + 阈值判断 + 冷却控制
    ├─→ 堆野事件 → 触发堆野推荐
    ├─→ 符文事件 → 触发控符推荐
    ├─→ 低血量事件 → 触发回城/买活推荐
    ├─→ 敌方消失事件 → 触发谨慎/插眼推荐
    └─→ 购买事件 → 触发应对策略推荐
        │
        ▼
    决策引擎层
        │
    ├─→ 规则引擎 (core/decision/rule_engine.py)
    │       └─→ 基于专家规则快速响应
    │
    ├─→ 数据引擎 (core/decision/data_engine.py)
    │       └─→ 基于历史数据胜率预测
    │
    └─→ LLM 引擎 (core/decision/llm_engine.py)
            └─→ 基于知识库 + 实时状态复杂推理
        │
        ▼
    决策融合器 (core/decision/decision_fusion.py)
        │ 加权融合 + 冲突解决
        ▼
    推荐结果
        │
    ├─→ SSE 推送 (/api/gsi/recommendations) → 前端实时展示
    └─→ Agent 工具查询 (RecommendationQueryTool) → Agent 推理时获取
```

---

## 四、模块设计

### 4.1 模块清单

| 模块 | 文件路径 | 职责 |
|------|---------|------|
| 事件触发器 | `core/event_trigger.py` | 订阅 GSI 事件，判断是否触发推荐 |
| 规则推理引擎 | `core/decision/rule_engine.py` | 基于领域专家规则快速推荐 |
| 数据驱动引擎 | `core/decision/data_engine.py` | 基于历史数据胜率预测和推荐 |
| LLM 增强引擎 | `core/decision/llm_engine.py` | 结合知识库 + 实时状态复杂推理 |
| 决策融合器 | `core/decision/decision_fusion.py` | 多源决策融合 + 冲突解决 |
| 推荐查询工具 | `tools/recommendation_tools.py` | Agent 可调用的推荐查询接口 |
| SSE 推送端 | `web/app.py` (新增路由) | 推荐结果 SSE 推送接口 |
| 前端消费 | `frontend/src/composables/useRecommendationStream.ts` | 前端 SSE 消费 |
| 配置文件 | `config/recommendation_config.yaml` | 推荐系统配置管理 |

### 4.2 模块依赖关系

```
core/event_trigger.py
    ├── gsi/event_queue.py (订阅事件)
    ├── core/decision/rule_engine.py
    ├── core/decision/data_engine.py
    ├── core/decision/llm_engine.py
    └── core/decision/decision_fusion.py

core/decision/rule_engine.py
    ├── knowledge/ (查询攻略知识)
    └── utils/localization.py (本地化)

core/decision/data_engine.py
    ├── utils/api_client.py (OpenDota API)
    └── cache/ (缓存历史数据)

core/decision/llm_engine.py
    ├── utils/llm_client.py (LLM 调用)
    ├── knowledge/ (知识检索)
    └── tools/gsi_tools.py (实时状态)

core/decision/decision_fusion.py
    ├── core/decision/rule_engine.py
    ├── core/decision/data_engine.py
    └── core/decision/llm_engine.py

tools/recommendation_tools.py
    └── core/decision/decision_fusion.py (查询推荐)

web/app.py
    └── core/event_trigger.py (SSE 推送)

frontend/src/composables/useRecommendationStream.ts
    └── (HTTP SSE 消费)
```

---

## 五、详细设计

### 5.1 事件触发器 (`core/event_trigger.py`)

**职责**: 订阅 GSI 事件队列，判断哪些事件需要触发主动推荐

**核心逻辑**:
```python
class EventTrigger:
    """事件触发器"""
    
    def __init__(self, event_queue: GSIEventQueue, config: Dict):
        self.event_queue = event_queue
        self.config = config
        self._cooldowns: Dict[str, float] = {}  # 事件类型 → 上次触发时间
        self._subscriber: Optional[queue.Queue] = None
    
    def start(self):
        """启动事件监听"""
        self._subscriber = self.event_queue.subscribe()
        threading.Thread(target=self._listen_loop, daemon=True).start()
    
    def _listen_loop(self):
        """事件监听循环"""
        while True:
            event = self._subscriber.get(timeout=1.0)
            if event and self._should_trigger(event):
                self._trigger_recommendation(event)
    
    def _should_trigger(self, event: GSIEvent) -> bool:
        """判断是否应该触发推荐"""
        # 1. 检查事件类型是否在配置中启用
        event_type = event.event_type
        if not self.config.get(f"triggers.{event_type}.enabled", False):
            return False
        
        # 2. 检查冷却时间
        cooldown = self.config.get(f"triggers.{event_type}.cooldown", 60)
        last_trigger = self._cooldowns.get(event_type, 0)
        if time.time() - last_trigger < cooldown:
            return False
        
        # 3. 检查阈值（如血量 < 20%）
        threshold = self.config.get(f"triggers.{event_type}.threshold")
        if threshold and not self._check_threshold(event, threshold):
            return False
        
        return True
    
    def _trigger_recommendation(self, event: GSIEvent):
        """触发推荐"""
        self._cooldowns[event.event_type] = time.time()
        
        # 调用决策融合器
        recommendation = self.decision_fusion.generate_recommendation(
            event=event,
            game_state=self.state_manager.get_state()
        )
        
        # 推送到 SSE
        self._push_to_sse(recommendation)
```

**配置示例** (`config/recommendation_config.yaml`):
```yaml
recommendation:
  enabled: true
  
  triggers:
    stack:
      enabled: true
      cooldown: 60  # 60秒冷却
      threshold: null
    
    rune:
      enabled: true
      cooldown: 30
      threshold: null
    
    low_health:
      enabled: true
      cooldown: 10
      threshold: 0.2  # 血量 < 20% 触发
    
    enemy_missing:
      enabled: true
      cooldown: 120
      threshold: null
    
    item_purchase:
      enabled: true
      cooldown: 30
      threshold: null
  
  decision_engines:
    rule:
      enabled: true
      weight: 0.3
    
    data:
      enabled: true
      weight: 0.4
    
    llm:
      enabled: true
      weight: 0.3
  
  fusion:
    conflict_resolution: "weighted_average"  # 或 "max_confidence"
    min_confidence: 0.5  # 低于此置信度不推荐
```

---

### 5.2 规则推理引擎 (`core/decision/rule_engine.py`)

**职责**: 基于领域专家规则快速推荐

**核心规则**:
```python
class RuleEngine:
    """规则推理引擎"""
    
    def __init__(self, config: Dict):
        self.config = config
        self.rules = self._load_rules()
    
    def _load_rules(self) -> List[Dict]:
        """加载规则"""
        return [
            {
                "name": "low_health_return",
                "condition": lambda state: state.health_percent < 0.2,
                "recommendation": "血量过低，建议回城补给或购买回复道具",
                "confidence": 0.9
            },
            {
                "name": "no_bkb_late_game",
                "condition": lambda state: state.game_time > 2400 and "black_king_bar" not in state.inventory,
                "recommendation": "游戏时间较长，建议购买黑皇杖（BKB）防止被控制",
                "confidence": 0.8
            },
            {
                "name": "enemy_invisible",
                "condition": lambda state: state.has_enemy_invisible() and "gem" not in state.inventory,
                "recommendation": "敌方有隐身英雄，建议购买宝石或真眼",
                "confidence": 0.85
            },
            {
                "name": "stack_timing",
                "condition": lambda state: state.game_time % 60 >= 53,
                "recommendation": "堆野时间到了，可以拉野堆积中立生物",
                "confidence": 0.7
            },
            # ... 更多规则
        ]
    
    def generate_recommendation(
        self,
        event: GSIEvent,
        game_state: GameState
    ) -> Optional[Dict]:
        """生成推荐"""
        for rule in self.rules:
            if rule["condition"](game_state):
                return {
                    "engine": "rule",
                    "recommendation": rule["recommendation"],
                    "confidence": rule["confidence"],
                    "reason": rule["name"]
                }
        return None
```

**优势**:
- ✅ 延迟低（< 10ms）
- ✅ 可解释性强
- ✅ 不需要训练数据

**局限**:
- ❌ 覆盖面有限（只能处理预定义场景）
- ❌ 无法量化决策效果

---

### 5.3 数据驱动引擎 (`core/decision/data_engine.py`)

**职责**: 基于历史数据胜率预测和推荐

**核心功能**:
```python
class DataEngine:
    """数据驱动引擎"""
    
    def __init__(self, config: Dict):
        self.config = config
        self.api_client = OpenDotaAPIClient()
        self.cache = HeroMatchupCache()
    
    def generate_recommendation(
        self,
        event: GSIEvent,
        game_state: GameState
    ) -> Optional[Dict]:
        """生成推荐"""
        if event.event_type == "item_purchase":
            return self._recommend_item_build(game_state)
        elif event.event_type == "game_start":
            return self._recommend_strategy(game_state)
        return None
    
    def _recommend_item_build(self, state: GameState) -> Dict:
        """推荐出装方案"""
        hero_id = state.hero_id
        enemy_hero_ids = state.get_enemy_hero_ids()
        
        # 查询历史数据
        matchups = self.cache.get_matchups(hero_id, enemy_hero_ids)
        
        # 分析胜率最高的出装
        best_build = self._analyze_best_build(matchups)
        
        return {
            "engine": "data",
            "recommendation": f"根据 {len(matchups)} 场对局数据，推荐出装：{best_build['items']}",
            "confidence": best_build["win_rate"],
            "data": {
                "matches_analyzed": len(matchups),
                "win_rate": best_build["win_rate"],
                "items": best_build["items"]
            }
        }
    
    def _recommend_strategy(self, state: GameState) -> Dict:
        """推荐对局策略"""
        hero_id = state.hero_id
        enemy_hero_ids = state.get_enemy_hero_ids()
        
        # 预测胜率
        win_rate = self._predict_win_rate(hero_id, enemy_hero_ids)
        
        # 分析对线策略
        lane_strategy = self._analyze_lane_strategy(hero_id, enemy_hero_ids)
        
        return {
            "engine": "data",
            "recommendation": f"预测胜率 {win_rate:.1%}，建议 {lane_strategy}",
            "confidence": 0.75,
            "data": {
                "win_rate": win_rate,
                "lane_strategy": lane_strategy
            }
        }
```

**优势**:
- ✅ 量化决策（胜率预测）
- ✅ 数据支撑（基于真实对局）

**局限**:
- ❌ 依赖数据质量
- ❌ 需要缓存管理

---

### 5.4 LLM 增强引擎 (`core/decision/llm_engine.py`)

**职责**: 结合知识库 + 实时状态复杂推理

**核心功能**:
```python
class LLMEngine:
    """LLM 增强引擎"""
    
    def __init__(self, config: Dict, llm_client, knowledge_system):
        self.config = config
        self.llm_client = llm_client
        self.knowledge_system = knowledge_system
    
    def generate_recommendation(
        self,
        event: GSIEvent,
        game_state: GameState
    ) -> Optional[Dict]:
        """生成推荐"""
        # 1. 检索相关知识
        knowledge = self.knowledge_system.query(
            query=f"{game_state.hero_name} 对局策略",
            top_k=3
        )
        
        # 2. 构建 Prompt
        prompt = self._build_prompt(event, game_state, knowledge)
        
        # 3. 调用 LLM
        response = self.llm_client.chat_completion(
            messages=[
                {"role": "system", "content": "你是 Dota 2 专业助手..."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7
        )
        
        return {
            "engine": "llm",
            "recommendation": response["content"],
            "confidence": 0.6,  # LLM 置信度较低
            "knowledge_sources": [k["title"] for k in knowledge]
        }
    
    def _build_prompt(
        self,
        event: GSIEvent,
        game_state: GameState,
        knowledge: List[Dict]
    ) -> str:
        """构建 Prompt"""
        return f"""
当前游戏状态：
- 英雄：{game_state.hero_name}
- 血量：{game_state.health}/{game_state.max_health}
- 金钱：{game_state.gold}
- 游戏时间：{game_state.game_time // 60}分钟

触发事件：{event.message}

相关知识：
{self._format_knowledge(knowledge)}

请基于以上信息，给出专业的游戏建议。
"""
```

**优势**:
- ✅ 灵活性强（可处理长尾场景）
- ✅ 知识融合（结合攻略文档）

**局限**:
- ❌ 延迟高（1-3秒）
- ❌ 成本较高（LLM 调用）

---

### 5.5 决策融合器 (`core/decision/decision_fusion.py`)

**职责**: 多源决策融合 + 冲突解决

**核心逻辑**:
```python
class DecisionFusion:
    """决策融合器"""
    
    def __init__(self, config: Dict):
        self.config = config
        self.rule_engine = RuleEngine(config)
        self.data_engine = DataEngine(config)
        self.llm_engine = LLMEngine(config)
    
    def generate_recommendation(
        self,
        event: GSIEvent,
        game_state: GameState
    ) -> Optional[Dict]:
        """生成融合推荐"""
        # 1. 并行调用三个引擎
        results = []
        
        if self.config["decision_engines.rule.enabled"]:
            rule_result = self.rule_engine.generate_recommendation(event, game_state)
            if rule_result:
                results.append(rule_result)
        
        if self.config["decision_engines.data.enabled"]:
            data_result = self.data_engine.generate_recommendation(event, game_state)
            if data_result:
                results.append(data_result)
        
        if self.config["decision_engines.llm.enabled"]:
            llm_result = self.llm_engine.generate_recommendation(event, game_state)
            if llm_result:
                results.append(llm_result)
        
        if not results:
            return None
        
        # 2. 加权融合
        fused = self._weighted_fusion(results)
        
        # 3. 冲突解决
        if self._has_conflict(results):
            fused = self._resolve_conflict(fused, results)
        
        # 4. 置信度过滤
        if fused["confidence"] < self.config["fusion.min_confidence"]:
            return None
        
        return fused
    
    def _weighted_fusion(self, results: List[Dict]) -> Dict:
        """加权融合"""
        weights = {
            "rule": self.config["decision_engines.rule.weight"],
            "data": self.config["decision_engines.data.weight"],
            "llm": self.config["decision_engines.llm.weight"]
        }
        
        # 计算加权置信度
        total_weight = sum(weights.get(r["engine"], 0) for r in results)
        weighted_confidence = sum(
            weights.get(r["engine"], 0) * r["confidence"]
            for r in results
        ) / total_weight
        
        # 选择置信度最高的推荐
        best_result = max(results, key=lambda r: r["confidence"])
        
        return {
            "recommendation": best_result["recommendation"],
            "confidence": weighted_confidence,
            "sources": [r["engine"] for r in results],
            "all_recommendations": results
        }
    
    def _has_conflict(self, results: List[Dict]) -> bool:
        """检测冲突"""
        if len(results) <= 1:
            return False
        
        # 简单冲突检测：推荐内容差异过大
        # 实际可以使用更复杂的语义相似度检测
        recommendations = [r["recommendation"] for r in results]
        return len(set(recommendations)) > 1
    
    def _resolve_conflict(self, fused: Dict, results: List[Dict]) -> Dict:
        """解决冲突"""
        strategy = self.config["fusion.conflict_resolution"]
        
        if strategy == "max_confidence":
            # 选择置信度最高的
            best = max(results, key=lambda r: r["confidence"])
            fused["recommendation"] = best["recommendation"]
            fused["confidence"] = best["confidence"]
        
        elif strategy == "weighted_average":
            # 加权平均（已在 _weighted_fusion 中处理）
            pass
        
        return fused
```

---

### 5.6 推荐查询工具 (`tools/recommendation_tools.py`)

**职责**: Agent 可调用的推荐查询接口

```python
class RecommendationQueryTool(Tool):
    """查询主动推荐"""
    
    def __init__(self, decision_fusion: DecisionFusion, state_manager, event_queue):
        self.decision_fusion = decision_fusion
        self.state_manager = state_manager
        self.event_queue = event_queue
        
        super().__init__(
            name="get_recommendation",
            description="获取基于当前游戏局势的主动推荐建议，包括出装、策略、局势分析等。",
            parameters={},
            func=self._get_recommendation,
            category="recommendation"
        )
    
    def _get_recommendation(self) -> Dict[str, Any]:
        """获取推荐"""
        game_state = self.state_manager.get_state()
        if not game_state:
            return {"available": False, "message": "当前不在游戏中"}
        
        # 获取最近事件
        recent_events = self.event_queue.get_recent(5)
        if not recent_events:
            return {"available": False, "message": "暂无游戏事件"}
        
        # 生成推荐
        recommendation = self.decision_fusion.generate_recommendation(
            event=recent_events[-1],
            game_state=game_state
        )
        
        if not recommendation:
            return {"available": False, "message": "暂无推荐建议"}
        
        return {
            "available": True,
            "recommendation": recommendation["recommendation"],
            "confidence": recommendation["confidence"],
            "sources": recommendation["sources"]
        }
```

---

## 六、实施步骤

### Phase 1: 事件触发器（1周）

**任务**:
1. 实现 `core/event_trigger.py`
2. 实现配置管理 `config/recommendation_config.yaml`
3. 编写单元测试

**交付物**:
- `core/event_trigger.py`
- `config/recommendation_config.yaml`
- `tests/unit/test_event_trigger.py`

---

### Phase 2: 规则推理引擎（1周）

**任务**:
1. 实现 `core/decision/rule_engine.py`
2. 定义 10-15 条核心规则
3. 编写单元测试

**交付物**:
- `core/decision/rule_engine.py`
- `tests/unit/test_rule_engine.py`

---

### Phase 3: 决策融合器（1周）

**任务**:
1. 实现 `core/decision/decision_fusion.py`
2. 集成规则引擎
3. 实现冲突解决逻辑
4. 编写单元测试

**交付物**:
- `core/decision/decision_fusion.py`
- `tests/unit/test_decision_fusion.py`

---

### Phase 4: LLM 增强引擎（0.5周）

**任务**:
1. 实现 `core/decision/llm_engine.py`
2. 设计 Prompt 模板
3. 集成知识库
4. 编写单元测试

**交付物**:
- `core/decision/llm_engine.py`
- `tests/unit/test_llm_engine.py`

---

### Phase 5: 数据驱动引擎（1.5周）

**任务**:
1. 实现 `core/decision/data_engine.py`
2. 集成 OpenDota API
3. 实现胜率预测模型
4. 编写单元测试

**交付物**:
- `core/decision/data_engine.py`
- `tests/unit/test_data_engine.py`

---

### Phase 6: Agent 工具 + SSE 推送（1周）

**任务**:
1. 实现 `tools/recommendation_tools.py`
2. 在 `web/app.py` 新增 SSE 端点
3. 集成到 AgentController
4. 编写集成测试

**交付物**:
- `tools/recommendation_tools.py`
- `web/app.py` (新增路由)
- `tests/integration/test_recommendation_integration.py`

---

### Phase 7: 前端展示（0.5周）

**任务**:
1. 实现 `useRecommendationStream.ts`
2. 在 `GsiStatusPanel.vue` 新增推荐展示区域
3. 联调测试

**交付物**:
- `frontend/src/composables/useRecommendationStream.ts`
- `frontend/src/components/GsiStatusPanel.vue` (更新)

---

## 七、预期收益

| 指标 | 当前 | 升级后 | 提升 |
|------|------|--------|------|
| 响应及时性 | 被动等待用户提问 | 主动推送建议 | 实时性 +100% |
| 决策准确性 | 75% | 90% | +20% |
| 用户满意度 | 中等 | 高 | +50% |
| 关键事件覆盖率 | 0%（无主动提醒） | 95% | +95% |

---

## 八、风险和注意事项

1. **信息轰炸**: 需要合理设置触发阈值和冷却机制，避免频繁推送打扰用户
2. **延迟控制**: LLM 引擎延迟较高（1-3秒），需要考虑异步推送
3. **成本控制**: LLM 调用有成本，需要限制调用频率
4. **冲突解决**: 多源决策可能冲突，需要有效的冲突解决策略
5. **数据质量**: 数据驱动引擎依赖历史数据质量，需要数据清洗和验证

---

## 九、参考资料

- [推理和决策能力增强方案](../../architecture_upgrade/REASONING_DECISION_UPGRADE.md)
- [GSI 实时数据监控设计文档](2026-06-14-gsi-realtime-monitoring-design.md)
- [知识管理能力升级设计文档](2026-06-12-knowledge-management-upgrade-design.md)
