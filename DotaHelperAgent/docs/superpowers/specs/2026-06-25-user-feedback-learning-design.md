# 用户反馈学习系统设计文档

> **版本**: v1.0  
> **日期**: 2026-06-25  
> **状态**: 待审核  
> **优先级**: P2  
> **所属阶段**: 第四阶段 — 个性化学习能力

---

## 一、问题陈述

### 1.1 当前问题

当前 DotaHelperAgent 的决策系统（`DecisionFusion`）使用**固定权重**融合三个引擎的推荐结果：

| 引擎 | 当前权重 | 来源 |
|------|---------|------|
| 规则引擎（RuleEngine） | 0.3 | 硬编码于 `decision_fusion.py` |
| 数据引擎（DataEngine） | 0.4 | 硬编码于 `decision_fusion.py` |
| LLM 引擎（LLMEngine） | 0.3 | 硬编码于 `decision_fusion.py` |

**核心痛点**：
- ❌ **权重不可调**：三个引擎的权重写死在代码中，无法根据实际效果动态调整
- ❌ **无反馈闭环**：用户对推荐结果的满意度没有被采集和利用
- ❌ **规则参数固化**：`RuleEngine` 中的阈值（如低血量 30%、堆野窗口 53-55秒）无法根据实际使用效果优化
- ❌ **无法衡量推荐质量**：推荐发出后，不知道用户是否采纳、是否有效

### 1.2 目标

建立用户反馈学习系统，实现：

1. **反馈采集**：显式（用户打分）+ 隐式（行为推断）双通道反馈
2. **效果评估**：量化每个引擎、每条规则的推荐效果
3. **全局策略优化**：根据反馈自动调整引擎权重和关键规则参数
4. **混合学习模式**：实时增量更新 + 定期批量校准

**预期收益**：
- ✅ 决策引擎权重自适应调整，推荐质量持续提升
- ✅ 关键规则参数根据实际效果优化
- ✅ 形成"推荐 → 反馈 → 学习 → 优化推荐"的完整闭环

---

## 二、技术决策

| 决策项 | 选择 | 理由 |
|--------|------|------|
| 反馈来源 | 显式 + 隐式双通道 | 显式反馈直观但稀疏，隐式反馈持续但需推断 |
| 作用范围 | 全局策略优化 | 聚焦系统级改进，暂不做用户级个性化 |
| 学习触发 | 混合模式（实时增量 + 定期批量） | 兼顾响应速度和稳定性 |
| 数据存储 | SQLite（复用现有模式） | 与记忆系统一致，轻量级、无需额外依赖 |
| 接口设计 | 接口 + 策略模式 | 符合项目工程规范 |
| 配置管理 | YAML 配置文件 | 与项目现有模式一致 |

---

## 三、系统架构

### 3.1 整体架构图

```
┌─────────────────────────────────────────────────────────────────────┐
│                        反馈采集层                                    │
│                                                                     │
│  ┌──────────────────┐              ┌──────────────────┐             │
│  │   显式反馈采集    │              │   隐式反馈采集    │             │
│  │  (用户打分/评价)  │              │  (行为推断)       │             │
│  └────────┬─────────┘              └────────┬─────────┘             │
│           │                                  │                       │
└───────────┼──────────────────────────────────┼──────────────────────┘
            │                                  │
            ▼                                  ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    反馈存储层 (FeedbackStore)                        │
│                                                                     │
│  ┌──────────────────────────────────────────────────────┐           │
│  │  SQLite: feedback_records 表                          │           │
│  │  (recommendation_id, feedback_type, score, context)   │           │
│  └──────────────────────────────────────────────────────┘           │
└────────────────────────────┬────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    效果评估层 (EffectEvaluator)                      │
│                                                                     │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐              │
│  │ 引擎级评估    │  │ 规则级评估    │  │ 场景级评估    │              │
│  │ (engine)     │  │ (rule)       │  │ (scenario)   │              │
│  └──────────────┘  └──────────────┘  └──────────────┘              │
└────────────────────────────┬────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    学习引擎层 (LearningEngine)                       │
│                                                                     │
│  ┌──────────────────────┐    ┌──────────────────────┐               │
│  │  实时增量学习器       │    │  定期批量校准器       │               │
│  │  (引擎权重微调)       │    │  (规则参数校准)       │               │
│  └──────────┬───────────┘    └──────────┬───────────┘               │
│             │                           │                            │
└─────────────┼───────────────────────────┼───────────────────────────┘
              │                           │
              ▼                           ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    策略参数存储 (StrategyParams)                      │
│                                                                     │
│  ┌──────────────────────────────────────────────────────┐           │
│  │  YAML: config/learned_strategy.yaml                   │           │
│  │  (引擎权重 + 规则参数 + 更新时间戳 + 置信度)           │           │
│  └──────────────────────────────────────────────────────┘           │
└────────────────────────────┬────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    决策系统集成点                                     │
│                                                                     │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐              │
│  │ DecisionFusion│  │ RuleEngine   │  │ EventTrigger │              │
│  │ (读取引擎权重) │  │ (读取规则参数) │  │ (触发反馈采集)│              │
│  └──────────────┘  └──────────────┘  └──────────────┘              │
└─────────────────────────────────────────────────────────────────────┘
```

### 3.2 数据流

```
1. 推荐产生
   DecisionFusion.generate_recommendation()
   → 生成 recommendation_id
   → 记录推荐上下文（引擎、参数、场景）

2. 反馈采集
   显式：用户在前端对推荐打分（👍/👎 或 1-5 星）
   隐式：系统检测用户行为（是否采纳推荐出装、是否忽略建议等）
   → 写入 FeedbackStore

3. 效果评估
   EffectEvaluator.aggregate()
   → 按引擎/规则/场景维度聚合反馈
   → 计算各维度的效果指标

4. 学习更新
   实时：每次收到反馈后微调引擎权重（小步长）
   定期：每天批量分析反馈数据，校准规则参数
   → 更新 learned_strategy.yaml

5. 决策应用
   DecisionFusion 读取 learned_strategy.yaml 中的引擎权重
   RuleEngine 读取 learned_strategy.yaml 中的规则参数
```

---

## 四、核心组件设计

### 4.1 反馈数据模型

```python
@dataclass
class FeedbackRecord:
    """反馈记录"""
    feedback_id: str                    # 唯一标识
    recommendation_id: str              # 关联的推荐 ID
    feedback_type: str                  # "explicit" | "implicit"
    score: float                        # 评分（显式: 1-5, 隐式: -1.0 ~ 1.0）
    engine: str                         # 产生推荐的引擎 ("rule" | "data" | "llm")
    event_type: str                     # 触发推荐的事件类型
    rule_name: Optional[str]            # 关联的规则名称（如有）
    context: Dict[str, Any]             # 推荐时的上下文快照
    timestamp: float                    # 反馈时间
    metadata: Dict[str, Any]            # 附加信息
```

### 4.2 反馈采集器（FeedbackCollector）

**职责**：采集显式和隐式反馈，生成 `FeedbackRecord` 并存储

**文件位置**：`feedback/collector.py`

#### 4.2.1 显式反馈

通过前端 UI 采集，提供两种交互方式：
- **快捷反馈**：对每条推荐显示 👍/👎 按钮
- **详细评价**：点击后展开 1-5 星评分 + 可选文字备注

**API 接口**：
```
POST /api/feedback/explicit
{
    "recommendation_id": "rec_xxx",
    "score": 4,              # 1-5 星
    "comment": "出装建议不错"  # 可选
}
```

#### 4.2.2 隐式反馈

从用户行为中推断推荐效果，定义以下隐式信号：

| 信号类型 | 检测方式 | 评分映射 |
|---------|---------|---------|
| **采纳推荐** | 用户购买了推荐物品 | score = 1.0 |
| **部分采纳** | 用户购买了推荐列表中的部分物品 | score = 0.5 |
| **忽略推荐** | 推荐发出后长时间（>3分钟）无相关行为 | score = -0.2 |
| **反向操作** | 用户购买了明确不推荐的物品 | score = -0.5 |
| **主动询问** | 用户就推荐内容追问细节 | score = 0.3（表示感兴趣） |

**检测机制**：在 GSI 事件流中监听物品购买事件，与最近的推荐记录进行匹配。

### 4.3 反馈存储（FeedbackStore）

**职责**：持久化存储反馈记录，提供查询和聚合接口

**文件位置**：`feedback/store.py`

**存储方案**：SQLite（与记忆系统一致）

**数据库表**：
```sql
CREATE TABLE feedback_records (
    feedback_id TEXT PRIMARY KEY,
    recommendation_id TEXT NOT NULL,
    feedback_type TEXT NOT NULL,        -- "explicit" | "implicit"
    score REAL NOT NULL,
    engine TEXT NOT NULL,
    event_type TEXT NOT NULL,
    rule_name TEXT,
    context TEXT,                       -- JSON
    timestamp REAL NOT NULL,
    metadata TEXT                       -- JSON
);

CREATE INDEX idx_engine ON feedback_records(engine);
CREATE INDEX idx_event_type ON feedback_records(event_type);
CREATE INDEX idx_timestamp ON feedback_records(timestamp);
CREATE INDEX idx_recommendation_id ON feedback_records(recommendation_id);
```

**核心接口**：
```python
class FeedbackStore:
    def save(self, record: FeedbackRecord) -> None: ...
    def get_by_engine(self, engine: str, since: float = None) -> List[FeedbackRecord]: ...
    def get_by_rule(self, rule_name: str, since: float = None) -> List[FeedbackRecord]: ...
    def get_by_event_type(self, event_type: str, since: float = None) -> List[FeedbackRecord]: ...
    def get_aggregate(self, group_by: str, since: float = None) -> Dict[str, AggregateStats]: ...
    def cleanup(self, max_age_days: int = 30) -> int: ...
```

### 4.4 效果评估器（EffectEvaluator）

**职责**：聚合反馈数据，计算各维度的效果指标

**文件位置**：`feedback/evaluator.py`

**评估维度**：

| 维度 | 指标 | 计算方式 |
|------|------|---------|
| **引擎级** | 平均得分、反馈数量、正反馈率 | 按 engine 分组聚合 |
| **规则级** | 平均得分、反馈数量、正反馈率 | 按 rule_name 分组聚合 |
| **场景级** | 平均得分、反馈数量 | 按 event_type 分组聚合 |
| **时间趋势** | 滚动平均分 | 按时间窗口聚合 |

**核心数据结构**：
```python
@dataclass
class AggregateStats:
    """聚合统计"""
    count: int              # 反馈总数
    avg_score: float        # 平均得分
    positive_rate: float    # 正反馈率（score > 0 的比例）
    std_score: float        # 得分标准差（衡量稳定性）
    last_updated: float     # 最后更新时间
```

### 4.5 学习引擎（LearningEngine）

**职责**：根据效果评估结果，更新策略参数

**文件位置**：`feedback/learning_engine.py`

#### 4.5.1 实时增量学习器

**触发条件**：每次收到新反馈后

**更新目标**：引擎权重（`engine_weights`）

**算法**：基于反馈得分的微调

```python
def update_engine_weights(self, feedback: FeedbackRecord) -> Dict[str, float]:
    """
    实时微调引擎权重
    
    算法：
    1. 计算反馈得分对应的权重调整方向
       - score > 0: 该引擎权重增加
       - score < 0: 该引擎权重减少
    2. 调整步长 = learning_rate * score（小步长，避免剧烈波动）
    3. 归一化权重（确保总和为 1.0）
    4. 边界检查（确保权重在 [min_weight, max_weight] 范围内）
    """
```

**关键参数**：
- `learning_rate`: 0.01（实时学习率，小步长）
- `min_weight`: 0.1（引擎最小权重，防止完全忽略某引擎）
- `max_weight`: 0.7（引擎最大权重，防止过度依赖某引擎）

#### 4.5.2 定期批量校准器

**触发条件**：每天定时执行（通过 `schedule` 库，复用 `web/app.py` 中已有的定时任务模式）

**更新目标**：规则参数（`rule_params`）

**校准流程**：
1. 聚合过去 24 小时的反馈数据
2. 按规则维度计算效果指标
3. 对效果差的规则（正反馈率 < 阈值）进行参数调整
4. 对效果好的规则（正反馈率 > 阈值）给予小幅奖励
5. 写入 `learned_strategy.yaml`

**可校准的规则参数**（来自 `RuleEngine`）：

| 参数 | 当前值 | 调整方向 | 调整依据 |
|------|--------|---------|---------|
| `low_health_threshold` | 0.3 | 用户觉得太频繁→降低，觉得太少→升高 | 低血量提醒的正反馈率 |
| `stack_window_start` | 53 | 根据反馈调整窗口 | 堆野提醒的正反馈率 |
| `rune_check_interval` | 30 | 根据反馈调整频率 | 符文提醒的正反馈率 |
| `recommendation_cooldown` | 10 | 推荐太频繁→增大，太少→减小 | 整体推荐的正反馈率 |

### 4.6 策略参数存储（StrategyParams）

**职责**：管理学习到的策略参数，提供读取接口

**文件位置**：`feedback/strategy_params.py`

**存储文件**：`config/learned_strategy.yaml`

```yaml
# 学习到的策略参数（自动生成，勿手动编辑）
version: 1
last_updated: "2026-06-25T12:00:00"
calibration_count: 42

engine_weights:
  rule:
    weight: 0.28
    confidence: 0.85    # 基于反馈数量，越高越可信
    last_updated: "2026-06-25T12:00:00"
  data:
    weight: 0.45
    confidence: 0.92
    last_updated: "2026-06-25T11:30:00"
  llm:
    weight: 0.27
    confidence: 0.78
    last_updated: "2026-06-25T12:00:00"

rule_params:
  low_health_threshold:
    value: 0.28
    default: 0.30
    confidence: 0.70
    last_updated: "2026-06-25T03:00:00"
  recommendation_cooldown:
    value: 12
    default: 10
    confidence: 0.65
    last_updated: "2026-06-25T03:00:00"

stats:
  total_feedback_count: 1234
  avg_score: 3.8
  positive_rate: 0.72
```

**核心接口**：
```python
class StrategyParams:
    def get_engine_weights(self) -> Dict[str, float]: ...
    def get_rule_param(self, param_name: str, default: Any = None) -> Any: ...
    def update_engine_weight(self, engine: str, weight: float) -> None: ...
    def update_rule_param(self, param_name: str, value: float) -> None: ...
    def save(self) -> None: ...
    def load(self) -> None: ...
    def get_stats(self) -> Dict[str, Any]: ...
```

---

## 五、集成方案

### 5.1 与 DecisionFusion 集成

修改 `DecisionFusion._fuse_by_weighted_average()` 方法，从 `StrategyParams` 读取引擎权重：

```python
# 当前（硬编码）
engine_weights = {"rule": 0.3, "data": 0.4, "llm": 0.3}

# 修改后（动态读取）
engine_weights = self.strategy_params.get_engine_weights()
```

### 5.2 与 RuleEngine 集成

修改 `RuleEngine` 中硬编码的阈值，从 `StrategyParams` 读取：

```python
# 当前（硬编码）
LOW_HEALTH_THRESHOLD = 0.3

# 修改后（动态读取）
threshold = self.strategy_params.get_rule_param("low_health_threshold", default=0.3)
```

### 5.3 与 EventTrigger 集成

在 `EventTrigger` 推送推荐时，记录 `recommendation_id` 和推荐上下文，供后续反馈关联：

```python
recommendation_id = generate_recommendation_id()
# 推送推荐时附带 recommendation_id
# 前端可通过此 ID 提交反馈
```

### 5.4 与 Web API 集成

新增 API 接口：

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/feedback/explicit` | POST | 提交显式反馈 |
| `/api/feedback/stats` | GET | 查询反馈统计 |
| `/api/feedback/strategy` | GET | 查询当前策略参数 |
| `/api/feedback/strategy/reset` | POST | 重置策略参数为默认值 |

### 5.5 与 Langfuse 集成

反馈数据同步上报至 Langfuse：
- 每条反馈作为 Langfuse Score 关联到对应的 Trace
- 便于在 Langfuse 面板中查看推荐质量趋势

---

## 六、文件清单

| 文件路径 | 说明 |
|---------|------|
| `feedback/__init__.py` | 模块初始化 |
| `feedback/collector.py` | 反馈采集器（显式 + 隐式） |
| `feedback/store.py` | 反馈存储（SQLite） |
| `feedback/evaluator.py` | 效果评估器 |
| `feedback/learning_engine.py` | 学习引擎（实时增量 + 定期批量） |
| `feedback/strategy_params.py` | 策略参数管理 |
| `config/learned_strategy.yaml` | 学习到的策略参数（自动生成） |
| `config/feedback_config.yaml` | 反馈学习配置 |
| `tests/feedback/test_collector.py` | 采集器单元测试 |
| `tests/feedback/test_store.py` | 存储单元测试 |
| `tests/feedback/test_evaluator.py` | 评估器单元测试 |
| `tests/feedback/test_learning_engine.py` | 学习引擎单元测试 |
| `tests/feedback/test_strategy_params.py` | 策略参数单元测试 |
| `tests/integration/test_feedback_integration.py` | 集成测试 |

**修改的现有文件**：

| 文件路径 | 修改内容 |
|---------|---------|
| `core/decision/decision_fusion.py` | 从 StrategyParams 读取引擎权重 |
| `core/decision/rule_engine.py` | 从 StrategyParams 读取规则参数 |
| `core/event_trigger.py` | 推荐时记录 recommendation_id |
| `web/app.py` | 新增反馈 API 接口、初始化反馈系统 |
| `frontend/src/components/` | 新增反馈 UI 组件 |

---

## 七、配置文件

### 7.1 feedback_config.yaml

```yaml
# 反馈学习系统配置

feedback:
  # 显式反馈
  explicit:
    enabled: true
    score_range: [1, 5]         # 评分范围
    allow_comment: true          # 是否允许文字备注

  # 隐式反馈
  implicit:
    enabled: true
    adopt_score: 1.0             # 采纳推荐得分
    partial_adopt_score: 0.5     # 部分采纳得分
    ignore_score: -0.2           # 忽略推荐得分
    ignore_timeout: 180          # 忽略判定超时（秒）
    reverse_score: -0.5          # 反向操作得分

  # 存储
  store:
    db_path: "feedback/feedback.db"
    max_age_days: 30             # 反馈数据保留天数
    cleanup_interval: 86400      # 清理间隔（秒）

learning:
  # 实时增量学习
  realtime:
    enabled: true
    learning_rate: 0.01          # 实时学习率
    min_weight: 0.1              # 引擎最小权重
    max_weight: 0.7              # 引擎最大权重

  # 定期批量校准
  calibration:
    enabled: true
    schedule_time: "03:00"       # 每天校准时间
    lookback_hours: 24           # 回溯时长
    min_feedback_count: 10       # 最少反馈数（低于此数不校准）
    positive_rate_threshold: 0.6 # 正反馈率阈值
    adjustment_step: 0.05        # 校准步长

  # 策略参数
  strategy:
    config_path: "config/learned_strategy.yaml"
    auto_save: true
    backup_count: 3              # 保留历史版本数

# Langfuse 集成
langfuse:
  enabled: true                  # 是否上报反馈到 Langfuse
  score_name: "user_feedback"    # Langfuse Score 名称
```

---

## 八、安全与边界

### 8.1 学习边界保护

| 保护机制 | 说明 |
|---------|------|
| **权重边界** | 引擎权重限制在 [0.1, 0.7]，防止某引擎被完全忽略或过度主导 |
| **参数边界** | 规则参数调整范围限制在默认值的 ±50% 内 |
| **最小样本量** | 校准需要至少 10 条反馈才执行，避免小样本误导 |
| **学习率衰减** | 随着反馈数量增加，学习率逐步降低，趋于稳定 |
| **重置机制** | 提供 API 重置策略参数为默认值，应对异常情况 |

### 8.2 降级策略

| 场景 | 降级方案 |
|------|---------|
| `learned_strategy.yaml` 不存在 | 使用硬编码默认值（当前行为） |
| 反馈数据库损坏 | 清空数据库，使用默认策略 |
| 学习引擎异常 | 捕获异常，保持当前策略不变，记录日志 |
| 反馈系统整体不可用 | 决策系统正常运行，使用默认权重和参数 |

---

## 九、测试策略

### 9.1 单元测试

| 测试文件 | 测试内容 |
|---------|---------|
| `test_collector.py` | 显式/隐式反馈采集、评分映射、上下文记录 |
| `test_store.py` | 存储/查询/聚合/清理、索引有效性 |
| `test_evaluator.py` | 引擎级/规则级/场景级评估、边界情况 |
| `test_learning_engine.py` | 实时权重更新、批量校准、边界保护 |
| `test_strategy_params.py` | 加载/保存/更新、默认值回退 |

### 9.2 集成测试

| 测试场景 | 验证内容 |
|---------|---------|
| 反馈 → 评估 → 学习 → 权重更新 | 完整闭环流程 |
| DecisionFusion 读取动态权重 | 权重变化影响推荐融合 |
| RuleEngine 读取动态参数 | 参数变化影响规则判断 |
| 降级场景 | 策略文件不存在时回退默认值 |
| 并发安全 | 多请求同时写入反馈 |

---

## 十、实施计划

### 10.1 分步实施

| 步骤 | 内容 | 依赖 |
|------|------|------|
| **Step 1** | 反馈数据模型 + 存储层（FeedbackStore） | 无 |
| **Step 2** | 反馈采集器（FeedbackCollector） | Step 1 |
| **Step 3** | 效果评估器（EffectEvaluator） | Step 1 |
| **Step 4** | 策略参数管理（StrategyParams） | 无 |
| **Step 5** | 学习引擎（LearningEngine） | Step 3, Step 4 |
| **Step 6** | 集成 DecisionFusion + RuleEngine | Step 4 |
| **Step 7** | Web API + 前端反馈 UI | Step 2 |
| **Step 8** | Langfuse 集成 | Step 2 |
| **Step 9** | 配置文件 + 定时任务 | Step 5 |
| **Step 10** | 测试 + 文档 | 全部 |

### 10.2 关键依赖

- 复用 `web/app.py` 中的 `schedule` 定时任务机制（用于批量校准）
- 复用 `utils/trace_context.py` 中的 ID 生成工具
- 复用 `utils/langfuse_adapter.py` 的 Score 上报能力
