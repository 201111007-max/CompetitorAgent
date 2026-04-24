# Core Component Tests

测试 Agent 核心组件，包括 Agent 本身、Tool Registry、ReAct 循环等。

## 测试文件

- `test_agent.py` - Agent 基本功能测试
- `test_agent_architecture.py` - Agent 架构测试
- `test_analyzers.py` - Hero Analyzer、Item Recommender 等分析器测试
- `test_react.py` - ReAct Agent 循环测试
- `test_strategies.py` - 策略模块测试

## 运行测试

```bash
# 运行所有核心测试
pytest core/ -v

# 运行特定测试
pytest core/test_agent.py -v
pytest core/test_react.py -v
pytest core/test_analyzers.py -v

# 运行特定测试类
pytest core/test_agent.py::TestAgentInit -v
```

## 测试覆盖

- ✅ Agent 初始化和配置
- ✅ Agent 架构完整性
- ✅ Hero Analyzer 功能
- ✅ Item Recommender 功能
- ✅ Skill Builder 功能
- ✅ ReAct 循环（Think-Plan-Act）
- ✅ Tool Registry 和 Tool 执行
- ✅ 策略评分和排序

## 依赖

- 核心模块：`core.agent`, `core.tool_registry`, `core.react_agent`
- 分析器模块：`analyzers.hero_analyzer`, `analyzers.item_recommender`
- pytest fixtures (来自根目录 conftest.py)
