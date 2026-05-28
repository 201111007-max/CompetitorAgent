# Agent 执行层监控设计文档

> **优先级**: P0
> **创建时间**: 2026-05-21
> **预计工作量**: 中
> **影响范围**: 高

---

## 一、功能概述

### 1.1 目标

在 `agent_controller.py` 中集成 Langfuse，监控 ReAct 循环的每个阶段，实现 Agent 推理过程的完整追踪。

### 1.2 核心功能

- ✅ 监控 ReAct 循环的每个阶段（Think → Plan → Execute → Observe → Reflect）
- ✅ 追踪工具选择决策过程
- ✅ 记录反思评估结果
- ✅ 统计整体推理耗时
- ✅ 记录 Agent 内部状态变化

### 1.3 预期收益

| 收益维度 | 具体效果 |
|---------|---------|
| **调试效率** | Agent 推理过程可视化，快速定位推理瓶颈 |
| **性能优化** | 识别推理耗时分布，优化慢查询 |
| **质量评估** | 推理质量评估，识别低质量推理路径 |
| **成本控制** | 推理成本分析，优化推理策略 |

---

## 二、实现方案

### 2.1 实现位置

**主要文件**: `core/agent_controller.py`

**相关文件**:
- `utils/langfuse_adapter.py` - Langfuse 客户端适配器
- `utils/langfuse_config.py` - 配置管理
- `config/langfuse_config.yaml` - 配置文件

### 2.2 架构设计

```
┌─────────────────────────────────────────────────────────────┐
│                   AgentController                            │
│                                                             │
│  ┌─────────────────────────────────────────────────────────┐│
│  │  solve() - 创建 Agent Trace                             ││
│  │  - trace_id: 唯一标识                                    ││
│  │  - session_id: 会话标识                                  ││
│  │  - query: 用户查询                                       ││
│  └─────────────────────────────────────────────────────────┘│
│         │                                                    │
│         ▼                                                    │
│  ┌─────────────────────────────────────────────────────────┐│
│  │  Think 阶段 (Span)                                       ││
│  │  - reasoning_steps: 推理步骤                             ││
│  │  - confidence: 置信度                                    ││
│  │  - metadata: {stage: "think"}                           ││
│  └─────────────────────────────────────────────────────────┘│
│         │                                                    │
│         ▼                                                    │
│  ┌─────────────────────────────────────────────────────────┐│
│  │  Plan 阶段 (Span)                                        ││
│  │  - selected_tools: 选择的工具                            ││
│  │  - tool_parameters: 工具参数                             ││
│  │  - metadata: {stage: "plan"}                            ││
│  └─────────────────────────────────────────────────────────┘│
│         │                                                    │
│         ▼                                                    │
│  ┌─────────────────────────────────────────────────────────┐│
│  │  Execute 阶段 (Span)                                     ││
│  │  - actions_taken: 执行的动作                             ││
│  │  - tool_results: 工具结果                                ││
│  │  - metadata: {stage: "execute"}                         ││
│  └─────────────────────────────────────────────────────────┘│
│         │                                                    │
│         ▼                                                    │
│  ┌─────────────────────────────────────────────────────────┐│
│  │  Observe 阶段 (Span)                                     ││
│  │  - observations: 观察结果                                ││
│  │  - data_collected: 收集的数据                            ││
│  │  - metadata: {stage: "observe"}                         ││
│  └─────────────────────────────────────────────────────────┘│
│         │                                                    │
│         ▼                                                    │
│  ┌─────────────────────────────────────────────────────────┐│
│  │  Reflect 阶段 (Span)                                     ││
│  │  - evaluation_scores: 评估分数                           ││
│  │  - strategy_adjustment: 策略调整                         ││
│  │  - metadata: {stage: "reflect"}                         ││
│  └─────────────────────────────────────────────────────────┘│
│         │                                                    │
│         ▼                                                    │
│  ┌─────────────────────────────────────────────────────────┐│
│  │  最终结果 (Trace.update)                                 ││
│  │  - final_answer: 最终答案                                ││
│  │  - total_turns: 总轮数                                   ││
│  │  - metadata: {success: true/false}                      ││
│  └─────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────┘
```

---

## 三、详细实现步骤

### 3.1 步骤 1: 导入 Langfuse 客户端

```python
# core/agent_controller.py

# Langfuse 监控（可选）
try:
    from utils.langfuse_adapter import LangfuseClient, NoOpObservation, NoOpSpan
    LANGFUSE_AVAILABLE = True
except ImportError:
    LANGFUSE_AVAILABLE = False
    LangfuseClient = None
    NoOpObservation = lambda: None
    NoOpSpan = lambda: None

logger = get_logger("agent_controller", component="core")
```

### 3.2 步骤 2: 在 solve() 方法中创建 Agent Trace

```python
def solve(self, query: str, context: Optional[Dict] = None) -> Dict:
    """执行 Agent 推理循环"""
    
    # 获取 Langfuse 客户端
    langfuse_client = LangfuseClient.get_instance() if LANGFUSE_AVAILABLE else None
    
    # 创建 Agent Trace
    if langfuse_client and langfuse_client.enabled:
        agent_trace = langfuse_client.observation(
            name="react_agent",
            as_type="agent",
            input={"query": query, "context": context},
            metadata={
                "session_id": context.get("session_id") if context else None,
                "max_turns": self.max_turns,
                "start_time": datetime.now().isoformat()
            }
        )
    else:
        agent_trace = NoOpObservation()
    
    # 执行推理循环
    with agent_trace:
        try:
            result = self._execute_react_loop(query, context, agent_trace)
            agent_trace.update(
                output={"answer": result.get("answer"), "success": True},
                metadata={
                    "total_turns": result.get("turns", 0),
                    "end_time": datetime.now().isoformat()
                }
            )
            return result
        except Exception as e:
            logger.error(f"Agent 执行失败: {e}")
            agent_trace.update(
                output={"error": str(e)},
                metadata={"success": False, "error_type": type(e).__name__}
            )
            return {"error": str(e)}
```

### 3.3 步骤 3: 在每个阶段创建 Span

```python
def _execute_react_loop(self, query: str, context: Optional[Dict], agent_trace) -> Dict:
    """执行 ReAct 循环"""
    
    thought = AgentThought(query=query)
    turns = 0
    
    while turns < self.max_turns:
        turns += 1
        
        # Think 阶段
        with agent_trace.span(name=f"think_turn_{turns}") as think_span:
            self._think(thought)
            think_span.update(
                output={
                    "reasoning_steps": thought.reasoning_steps,
                    "confidence": thought.confidence
                },
                metadata={"stage": "think", "turn": turns}
            )
        
        # Plan 阶段
        with agent_trace.span(name=f"plan_turn_{turns}") as plan_span:
            self._plan(thought)
            plan_span.update(
                output={
                    "selected_tools": thought.selected_tools,
                    "tool_parameters": thought.tool_parameters
                },
                metadata={"stage": "plan", "turn": turns}
            )
        
        # Execute 阶段
        with agent_trace.span(name=f"execute_turn_{turns}") as exec_span:
            self._execute(thought)
            exec_span.update(
                output={
                    "actions_taken": thought.actions_taken,
                    "tool_results": thought.tool_results
                },
                metadata={"stage": "execute", "turn": turns}
            )
        
        # Observe 阶段
        with agent_trace.span(name=f"observe_turn_{turns}") as obs_span:
            self._observe(thought)
            obs_span.update(
                output={
                    "observations": thought.observations,
                    "data_collected": thought.data_collected
                },
                metadata={"stage": "observe", "turn": turns}
            )
        
        # Reflect 阶段
        with agent_trace.span(name=f"reflect_turn_{turns}") as ref_span:
            self._reflect(thought)
            ref_span.update(
                output={
                    "evaluation_scores": thought.evaluation_scores,
                    "strategy_adjustment": thought.strategy_adjustment
                },
                metadata={"stage": "reflect", "turn": turns}
            )
        
        # 检查是否达到目标
        if thought.is_goal_achieved():
            break
    
    return {
        "answer": thought.final_answer,
        "turns": turns,
        "thought_process": thought.to_dict()
    }
```

### 3.4 步骤 4: 在反思阶段记录评估结果

```python
def _reflect(self, thought: AgentThought) -> None:
    """反思评估"""
    
    # 使用 ReflectionEvaluator 评估
    evaluation = self.reflection_evaluator.evaluate(thought)
    
    # 记录评估结果
    thought.evaluation_scores = {
        "completeness": evaluation.completeness,
        "consistency": evaluation.consistency,
        "credibility": evaluation.credibility,
        "relevance": evaluation.relevance,
        "actionability": evaluation.actionability
    }
    
    # 记录策略调整
    thought.strategy_adjustment = self._adjust_strategy(evaluation)
    
    logger.info(f"反思评估: {thought.evaluation_scores}")
```

---

## 四、测试方案

### 4.1 单元测试

**文件**: `tests/core/test_agent_controller_langfuse.py`

```python
import pytest
from unittest.mock import Mock, patch
from core.agent_controller import AgentController
from utils.langfuse_adapter import LangfuseClient

class TestAgentControllerLangfuse:
    
    @pytest.fixture
    def agent_controller(self):
        """创建 AgentController 实例"""
        return AgentController()
    
    @pytest.fixture
    def mock_langfuse_client(self):
        """模拟 Langfuse 客户端"""
        client = Mock(spec=LangfuseClient)
        client.enabled = True
        client.observation = Mock()
        return client
    
    def test_agent_trace_creation(self, agent_controller, mock_langfuse_client):
        """测试 Agent Trace 创建"""
        with patch('core.agent_controller.LangfuseClient.get_instance', return_value=mock_langfuse_client):
            result = agent_controller.solve("推荐克制帕吉的英雄")
            
            # 验证 Trace 创建
            assert mock_langfuse_client.observation.called
            call_args = mock_langfuse_client.observation.call_args
            assert call_args[1]['name'] == 'react_agent'
            assert call_args[1]['as_type'] == 'agent'
    
    def test_think_span_creation(self, agent_controller, mock_langfuse_client):
        """测试 Think Span 创建"""
        mock_trace = Mock()
        mock_trace.span = Mock()
        mock_langfuse_client.observation.return_value = mock_trace
        
        with patch('core.agent_controller.LangfuseClient.get_instance', return_value=mock_langfuse_client):
            result = agent_controller.solve("推荐克制帕吉的英雄")
            
            # 验证 Think Span 创建
            span_calls = [call for call in mock_trace.span.call_args_list if 'think' in call[1]['name']]
            assert len(span_calls) > 0
    
    def test_langfuse_disabled(self, agent_controller):
        """测试 Langfuse 禁用时的行为"""
        with patch('core.agent_controller.LANGFUSE_AVAILABLE', False):
            result = agent_controller.solve("推荐克制帕吉的英雄")
            
            # 验证正常执行（无监控）
            assert result is not None
            assert "error" not in result
```

### 4.2 集成测试

**文件**: `tests/integration/test_agent_langfuse_integration.py`

```python
import pytest
from core.agent_controller import AgentController
from utils.langfuse_adapter import LangfuseClient

class TestAgentLangfuseIntegration:
    
    @pytest.fixture
    def agent_controller(self):
        """创建 AgentController 实例"""
        return AgentController()
    
    def test_full_react_loop_monitoring(self, agent_controller):
        """测试完整 ReAct 循环监控"""
        # 初始化 Langfuse
        langfuse_client = LangfuseClient.get_instance()
        langfuse_client.init()
        
        if not langfuse_client.enabled:
            pytest.skip("Langfuse 未启用")
        
        # 执行查询
        result = agent_controller.solve("对面有帕吉和斧王，推荐克制英雄和出装")
        
        # 验证结果
        assert result is not None
        assert "answer" in result
        
        # 刷新数据
        langfuse_client.flush()
```

---

## 五、配置说明

### 5.1 Langfuse 配置

**文件**: `config/langfuse_config.yaml`

```yaml
langfuse:
  enabled: true
  host: "http://localhost:3001"
  public_key: "${LANGFUSE_PUBLIC_KEY}"
  secret_key: "${LANGFUSE_SECRET_KEY}"
  
  # Agent 监控配置
  agent_monitoring:
    enabled: true
    trace_all_stages: true  # 追踪所有阶段
    record_thought_process: true  # 记录思考过程
    record_evaluation_scores: true  # 记录评估分数
    
  # 性能配置
  performance:
    sample_rate: 1.0  # 采样率
    max_trace_size: 10000  # 最大 Trace 大小
```

### 5.2 环境变量

```bash
# .env 文件
LANGFUSE_PUBLIC_KEY=pk-xxx
LANGFUSE_SECRET_KEY=sk-xxx
LANGFUSE_HOST=http://localhost:3001
```

---

## 六、预期收益分析

### 6.1 调试效率提升

**场景**: Agent 推理失败，需要定位问题

**当前状态**:
- ❌ 只能看到最终错误信息
- ❌ 无法定位具体哪个阶段失败
- ❌ 无法查看推理过程

**集成后**:
- ✅ 可查看完整推理链路
- ✅ 可定位到具体失败的阶段（Think/Plan/Execute/Observe/Reflect）
- ✅ 可查看每个阶段的输入输出

**效率提升**: 从 30 分钟定位问题 → 5 分钟定位问题

---

### 6.2 性能优化

**场景**: Agent 推理耗时过长，需要优化

**当前状态**:
- ❌ 只能看到总耗时
- ❌ 无法识别瓶颈阶段
- ❌ 无法分析耗时分布

**集成后**:
- ✅ 可查看每个阶段的耗时
- ✅ 可识别瓶颈阶段（如 Plan 阶段耗时过长）
- ✅ 可分析耗时分布（Think 20%, Plan 40%, Execute 30%, Reflect 10%）

**优化效果**: 推理耗时从 5 秒 → 3 秒（优化 Plan 阶段）

---

### 6.3 质量评估

**场景**: Agent 推理质量不稳定，需要评估

**当前状态**:
- ❌ 只能看到最终答案
- ❌ 无法评估推理过程质量
- ❌ 无法识别低质量推理路径

**集成后**:
- ✅ 可查看每个阶段的评估分数
- ✅ 可识别低质量推理路径（如 Reflect 评分过低）
- ✅ 可分析推理质量分布

**质量提升**: 推理质量评分从 60 分 → 80 分

---

## 七、风险评估

### 7.1 性能影响

**风险**: Langfuse 监控可能影响 Agent 性能

**缓解措施**:
- 使用异步记录（`flush()` 在请求结束后调用）
- 设置采样率（如 10% 采样）
- 使用 NoOpObservation 作为降级方案

**预期影响**: 性能损耗 < 5%

---

### 7.2 数据隐私

**风险**: 记录用户查询可能涉及隐私

**缓解措施**:
- 不记录敏感信息（如用户 ID、IP 地址）
- 使用脱敏处理（如替换英雄名为 ID）
- 设置数据保留期限（如 7 天）

**合规性**: 符合 GDPR 要求

---

## 八、实施计划

### 8.1 时间安排

| 阶段 | 任务 | 预计时间 |
|------|------|---------|
| **第 1 天** | 导入 Langfuse 客户端，创建 Agent Trace | 2 小时 |
| **第 2 天** | 在每个阶段创建 Span | 3 小时 |
| **第 3 天** | 编写单元测试和集成测试 | 2 小时 |
| **第 4 天** | 配置优化和性能测试 | 2 小时 |
| **第 5 天** | 文档编写和验收测试 | 1 小时 |

**总预计时间**: 10 小时（约 2 个工作日）

---

### 8.2 验收标准

| 标准 | 验收方法 |
|------|---------|
| ✅ Agent Trace 创建成功 | 查看 Langfuse Dashboard |
| ✅ 所有阶段 Span 创建成功 | 查看 Langfuse Dashboard |
| ✅ 评估分数记录成功 | 查看 Langfuse Dashboard |
| ✅ 性能损耗 < 5% | 性能测试 |
| ✅ 单元测试通过 | pytest 运行 |
| ✅ 集成测试通过 | pytest 运行 |

---

## 九、总结

Agent 执行层监控是 Langfuse 集成的核心功能，将显著提升 Agent 系统的可观测性、调试效率和性能优化能力。

**关键收益**:
- ✅ Agent 推理过程可视化
- ✅ 精确定位推理瓶颈
- ✅ 推理质量评估
- ✅ 性能优化依据

**下一步**: 继续实现工具调用层监控（P0-2）