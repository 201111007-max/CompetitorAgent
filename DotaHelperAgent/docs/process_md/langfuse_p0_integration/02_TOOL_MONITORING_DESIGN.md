# 工具调用层监控设计文档

> **优先级**: P0
> **创建时间**: 2026-05-21
> **预计工作量**: 中
> **影响范围**: 高

---

## 一、功能概述

### 1.1 目标

在 `tool_registry.py` 中集成 Langfuse，监控工具执行情况，实现工具调用的完整追踪。

### 1.2 核心功能

- ✅ 监控工具调用频率
- ✅ 统计工具执行耗时
- ✅ 追踪工具成功率
- ✅ 记录工具参数和返回值
- ✅ 分析工具性能瓶颈

### 1.3 预期收益

| 收益维度 | 具体效果 |
|---------|---------|
| **性能优化** | 识别慢工具，优化执行效率 |
| **质量评估** | 工具成功率分析，识别低质量工具 |
| **使用统计** | 工具使用频率分析，优化工具选择 |
| **调试效率** | 快速定位工具执行失败原因 |

---

## 二、实现方案

### 2.1 实现位置

**主要文件**: `core/tool_registry.py`

**相关文件**:
- `utils/langfuse_adapter.py` - Langfuse 客户端适配器
- `utils/trace_context.py` - Trace 上下文管理
- `tools/base.py` - 工具基类

### 2.2 架构设计

```
┌─────────────────────────────────────────────────────────────┐
│                   ToolRegistry                               │
│                                                             │
│  ┌─────────────────────────────────────────────────────────┐│
│  │  execute() - 创建工具 Span                               ││
│  │  - tool_name: 工具名称                                    ││
│  │  - trace_id: Trace ID（从上下文获取）                     ││
│  │  - parameters: 工具参数                                   ││
│  └─────────────────────────────────────────────────────────┘│
│         │                                                    │
│         ▼                                                    │
│  ┌─────────────────────────────────────────────────────────┐│
│  │  工具执行前记录                                           ││
│  │  - input: 工具参数                                        ││
│  │  - metadata: {category, description}                    ││
│  │  - start_time: 开始时间                                   ││
│  └─────────────────────────────────────────────────────────┘│
│         │                                                    │
│         ▼                                                    │
│  ┌─────────────────────────────────────────────────────────┐│
│  │  工具执行                                                 ││
│  │  - tool.execute(**kwargs)                               ││
│  │  - 捕获异常                                               ││
│  │  - 记录执行时间                                           ││
│  └─────────────────────────────────────────────────────────┘│
│         │                                                    │
│         ▼                                                    │
│  ┌─────────────────────────────────────────────────────────┐│
│  │  工具执行后记录                                           ││
│  │  - output: {success, data_preview}                      ││
│  │  - metadata: {execution_time_ms, error}                 ││
│  │  - score: 工具评分（可选）                                ││
│  └─────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────┘
```

---

## 三、详细实现步骤

### 3.1 步骤 1: 导入 Langfuse 客户端

```python
# core/tool_registry.py

# Langfuse 监控（可选）
try:
    from utils.langfuse_adapter import LangfuseClient, NoOpObservation
    LANGFUSE_AVAILABLE = True
except ImportError:
    LANGFUSE_AVAILABLE = False
    LangfuseClient = None
    NoOpObservation = lambda: None

# Trace 上下文
try:
    from utils.trace_context import get_current_trace
    TRACE_CONTEXT_AVAILABLE = True
except ImportError:
    TRACE_CONTEXT_AVAILABLE = False
    get_current_trace = lambda: None

logger = get_logger("tool_registry", component="core")
```

### 3.2 步骤 2: 在 execute() 方法中创建工具 Span

```python
def execute(self, tool_name: str, **kwargs) -> ToolResult:
    """执行工具调用（带 Langfuse 监控）"""
    
    # 获取 Langfuse 客户端
    langfuse_client = LangfuseClient.get_instance() if LANGFUSE_AVAILABLE else None
    
    # 获取 Trace 上下文
    trace_ctx = get_current_trace() if TRACE_CONTEXT_AVAILABLE else None
    
    # 创建工具 Span
    if langfuse_client and langfuse_client.enabled:
        tool_span = langfuse_client.observation(
            name=f"tool_{tool_name}",
            as_type="tool",
            input=kwargs,
            metadata={
                "trace_id": trace_ctx.trace_id if trace_ctx else None,
                "tool_name": tool_name,
                "category": self.tools.get(tool_name).category if tool_name in self.tools else None,
                "description": self.tools.get(tool_name).description if tool_name in self.tools else None,
                "start_time": datetime.now().isoformat()
            }
        )
    else:
        tool_span = NoOpObservation()
    
    # 执行工具
    with tool_span:
        start_time = time.time()
        
        try:
            # 获取工具实例
            tool = self.tools.get(tool_name)
            if not tool:
                raise ValueError(f"工具 '{tool_name}' 不存在")
            
            # 执行工具
            result = tool.execute(**kwargs)
            
            # 记录执行结果
            execution_time = time.time() - start_time
            
            tool_span.update(
                output={
                    "success": result.is_success(),
                    "status": result.status.value,
                    "data_preview": str(result.data)[:200] if result.data else None
                },
                metadata={
                    "execution_time_ms": execution_time * 1000,
                    "end_time": datetime.now().isoformat(),
                    "error": result.error if result.error else None
                }
            )
            
            # 记录工具评分（可选）
            if result.is_success():
                tool_span.score(
                    name="tool_success",
                    value=1.0,
                    comment="工具执行成功"
                )
            else:
                tool_span.score(
                    name="tool_success",
                    value=0.0,
                    comment=f"工具执行失败: {result.error}"
                )
            
            logger.info(f"工具 {tool_name} 执行完成，耗时 {execution_time:.2f}s")
            
            return result
            
        except Exception as e:
            # 记录异常
            execution_time = time.time() - start_time
            
            tool_span.update(
                output={"success": False, "error": str(e)},
                metadata={
                    "execution_time_ms": execution_time * 1000,
                    "end_time": datetime.now().isoformat(),
                    "error_type": type(e).__name__
                }
            )
            
            tool_span.score(
                name="tool_success",
                value=0.0,
                comment=f"工具执行异常: {str(e)}"
            )
            
            logger.error(f"工具 {tool_name} 执行失败: {e}")
            
            return ToolResult(
                status=ToolStatus.ERROR,
                data=None,
                error=str(e)
            )
```

### 3.3 步骤 3: 在工具基类中添加监控支持

```python
# tools/base.py

class BaseTool:
    """工具基类"""
    
    def execute(self, **kwargs) -> ToolResult:
        """执行工具（子类实现）"""
        raise NotImplementedError
    
    def get_metadata(self) -> Dict:
        """获取工具元数据"""
        return {
            "name": self.name,
            "category": self.category,
            "description": self.description,
            "parameters": self.parameters
        }
```

### 3.4 步骤 4: 在 ToolRegistry 中添加统计功能

```python
# core/tool_registry.py

class ToolRegistry:
    """工具注册中心"""
    
    def __init__(self):
        self.tools = {}
        self.execution_stats = {}  # 工具执行统计
    
    def get_tool_stats(self, tool_name: str) -> Dict:
        """获取工具执行统计"""
        return self.execution_stats.get(tool_name, {
            "total_calls": 0,
            "success_calls": 0,
            "failed_calls": 0,
            "avg_execution_time": 0.0,
            "max_execution_time": 0.0,
            "min_execution_time": 0.0
        })
    
    def update_tool_stats(self, tool_name: str, execution_time: float, success: bool):
        """更新工具执行统计"""
        stats = self.execution_stats.get(tool_name, {
            "total_calls": 0,
            "success_calls": 0,
            "failed_calls": 0,
            "avg_execution_time": 0.0,
            "max_execution_time": 0.0,
            "min_execution_time": float('inf')
        })
        
        stats["total_calls"] += 1
        if success:
            stats["success_calls"] += 1
        else:
            stats["failed_calls"] += 1
        
        # 更新执行时间统计
        stats["avg_execution_time"] = (
            (stats["avg_execution_time"] * (stats["total_calls"] - 1) + execution_time) 
            / stats["total_calls"]
        )
        stats["max_execution_time"] = max(stats["max_execution_time"], execution_time)
        stats["min_execution_time"] = min(stats["min_execution_time"], execution_time)
        
        self.execution_stats[tool_name] = stats
    
    def get_all_tool_stats(self) -> Dict:
        """获取所有工具执行统计"""
        return self.execution_stats
```

---

## 四、测试方案

### 4.1 单元测试

**文件**: `tests/core/test_tool_registry_langfuse.py`

```python
import pytest
from unittest.mock import Mock, patch
from core.tool_registry import ToolRegistry
from utils.langfuse_adapter import LangfuseClient

class TestToolRegistryLangfuse:
    
    @pytest.fixture
    def tool_registry(self):
        """创建 ToolRegistry 实例"""
        registry = ToolRegistry()
        # 注册测试工具
        registry.register(MockTool())
        return registry
    
    @pytest.fixture
    def mock_langfuse_client(self):
        """模拟 Langfuse 客户端"""
        client = Mock(spec=LangfuseClient)
        client.enabled = True
        client.observation = Mock()
        return client
    
    def test_tool_span_creation(self, tool_registry, mock_langfuse_client):
        """测试工具 Span 创建"""
        with patch('core.tool_registry.LangfuseClient.get_instance', return_value=mock_langfuse_client):
            result = tool_registry.execute("mock_tool", param1="value1")
            
            # 验证 Span 创建
            assert mock_langfuse_client.observation.called
            call_args = mock_langfuse_client.observation.call_args
            assert call_args[1]['name'] == 'tool_mock_tool'
            assert call_args[1]['as_type'] == 'tool'
    
    def test_tool_execution_stats(self, tool_registry):
        """测试工具执行统计"""
        # 执行多次
        for i in range(5):
            tool_registry.execute("mock_tool", param1=f"value{i}")
        
        # 获取统计
        stats = tool_registry.get_tool_stats("mock_tool")
        
        assert stats["total_calls"] == 5
        assert stats["success_calls"] > 0
        assert stats["avg_execution_time"] > 0
    
    def test_langfuse_disabled(self, tool_registry):
        """测试 Langfuse 禁用时的行为"""
        with patch('core.tool_registry.LANGFUSE_AVAILABLE', False):
            result = tool_registry.execute("mock_tool", param1="value1")
            
            # 验证正常执行（无监控）
            assert result is not None
            assert result.is_success()

class MockTool(BaseTool):
    """模拟工具"""
    name = "mock_tool"
    category = "test"
    description = "测试工具"
    
    def execute(self, **kwargs):
        return ToolResult(
            status=ToolStatus.SUCCESS,
            data={"result": "mock_data"},
            error=None
        )
```

### 4.2 集成测试

**文件**: `tests/integration/test_tool_langfuse_integration.py`

```python
import pytest
from core.tool_registry import ToolRegistry
from utils.langfuse_adapter import LangfuseClient

class TestToolLangfuseIntegration:
    
    @pytest.fixture
    def tool_registry(self):
        """创建 ToolRegistry 实例"""
        registry = ToolRegistry()
        # 注册所有工具
        registry.register_all_tools()
        return registry
    
    def test_real_tool_execution(self, tool_registry):
        """测试真实工具执行监控"""
        # 初始化 Langfuse
        langfuse_client = LangfuseClient.get_instance()
        langfuse_client.init()
        
        if not langfuse_client.enabled:
            pytest.skip("Langfuse 未启用")
        
        # 执行工具
        result = tool_registry.execute("analyze_counter_picks", enemy_heroes=["帕吉"])
        
        # 验证结果
        assert result is not None
        assert result.is_success()
        
        # 刷新数据
        langfuse_client.flush()
        
        # 验证统计
        stats = tool_registry.get_tool_stats("analyze_counter_picks")
        assert stats["total_calls"] > 0
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
  
  # 工具监控配置
  tool_monitoring:
    enabled: true
    trace_all_tools: true  # 追踪所有工具
    record_parameters: true  # 记录工具参数
    record_results: true  # 记录工具结果
    max_data_preview_size: 200  # 数据预览最大长度
    
  # 性能配置
  performance:
    sample_rate: 1.0  # 采样率
    max_span_size: 5000  # 最大 Span 大小
```

### 5.2 工具配置

**文件**: `config/tools_config.yaml`

```yaml
tools:
  analyze_counter_picks:
    enabled: true
    timeout: 30  # 超时时间（秒）
    retry_count: 2  # 重试次数
    
  recommend_items:
    enabled: true
    timeout: 20
    retry_count: 1
    
  recommend_skills:
    enabled: true
    timeout: 15
    retry_count: 1
```

---

## 六、预期收益分析

### 6.1 性能优化

**场景**: 工具执行耗时过长，需要优化

**当前状态**:
- ❌ 只能看到总耗时
- ❌ 无法识别慢工具
- ❌ 无法分析耗时分布

**集成后**:
- ✅ 可查看每个工具的耗时
- ✅ 可识别慢工具（如 `analyze_counter_picks` 耗时 2 秒）
- ✅ 可分析耗时分布（工具 A 30%, 工具 B 40%, 工具 C 30%）

**优化效果**: 工具执行耗时从 5 秒 → 3 秒（优化慢工具）

---

### 6.2 质量评估

**场景**: 工具执行失败率高，需要评估

**当前状态**:
- ❌ 只能看到最终错误
- ❌ 无法统计工具成功率
- ❌ 无法识别低质量工具

**集成后**:
- ✅ 可查看每个工具的成功率
- ✅ 可识别低质量工具（如 `recommend_items` 成功率 60%）
- ✅ 可分析失败原因

**质量提升**: 工具成功率从 70% → 90%

---

### 6.3 使用统计

**场景**: 工具使用频率分析，优化工具选择

**当前状态**:
- ❌ 无法统计工具使用频率
- ❌ 无法分析工具选择合理性
- ❌ 无法优化工具选择策略

**集成后**:
- ✅ 可查看工具使用频率（如 `analyze_counter_picks` 使用 50 次）
- ✅ 可分析工具选择合理性
- ✅ 可优化工具选择策略

**优化效果**: 工具选择准确率从 60% → 80%

---

## 七、风险评估

### 7.1 性能影响

**风险**: Langfuse 监控可能影响工具执行性能

**缓解措施**:
- 使用异步记录（`flush()` 在请求结束后调用）
- 设置采样率（如 10% 采样）
- 使用 NoOpObservation 作为降级方案
- 限制数据预览大小（200 字符）

**预期影响**: 性能损耗 < 3%

---

### 7.2 数据隐私

**风险**: 记录工具参数可能涉及隐私

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
| **第 1 天** | 导入 Langfuse 客户端，创建工具 Span | 2 小时 |
| **第 2 天** | 添加工具执行统计功能 | 2 小时 |
| **第 3 天** | 编写单元测试和集成测试 | 2 小时 |
| **第 4 天** | 配置优化和性能测试 | 2 小时 |
| **第 5 天** | 文档编写和验收测试 | 1 小时 |

**总预计时间**: 9 小时（约 2 个工作日）

---

### 8.2 验收标准

| 标准 | 验收方法 |
|------|---------|
| ✅ 工具 Span 创建成功 | 查看 Langfuse Dashboard |
| ✅ 工具执行统计功能正常 | 查看统计数据 |
| ✅ 性能损耗 < 3% | 性能测试 |
| ✅ 单元测试通过 | pytest 运行 |
| ✅ 集成测试通过 | pytest 运行 |

---

## 九、总结

工具调用层监控是 Langfuse 集成的关键功能，将显著提升工具系统的可观测性、性能优化能力和质量评估能力。

**关键收益**:
- ✅ 工具性能分析
- ✅ 工具使用统计
- ✅ 工具优化依据
- ✅ 快速定位工具失败原因

**下一步**: 继续实现 Trace 定位与日志追踪体系（P0-3）