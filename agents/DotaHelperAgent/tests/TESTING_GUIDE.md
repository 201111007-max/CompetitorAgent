# DotaHelperAgent 全流程测试指南

## 📋 测试架构

本项目采用**前后端分离的 Agent 架构**，测试覆盖以下 5 个层面：

```
┌─────────────────────────────────────────┐
│  1. 前端 UI 层 (web/index.html)          │
│     - 用户界面交互                       │
│     - API 调用测试                       │
└─────────────────────────────────────────┘
              ↓
┌─────────────────────────────────────────┐
│  2. API 层 (web/app.py)                  │
│     - HTTP 端点测试                      │
│     - 请求/响应验证                      │
│     - 英雄/物品解析测试                  │
└─────────────────────────────────────────┘
              ↓
┌─────────────────────────────────────────┐
│  3. Agent 控制器层 (core/agent_controller)│
│     - ReAct 循环测试                     │
│     - Tool Registry 测试                 │
│     - Memory 测试                        │
└─────────────────────────────────────────┘
              ↓
┌─────────────────────────────────────────┐
│  4. 核心业务层                           │
│     - Hero Analyzer 测试                │
│     - Item Recommender 测试             │
│     - Skill Builder 测试                │
└─────────────────────────────────────────┘
              ↓
┌─────────────────────────────────────────┐
│  5. 数据层                               │
│     - OpenDota API 客户端测试            │
│     - 缓存系统测试                       │
│     - 配置加载测试                       │
└─────────────────────────────────────────┘
```

## 📁 测试文件结构

```
tests/
├── conftest.py                      # pytest 配置和共享 fixtures
├── run_tests.py                     # 运行所有单元测试
├── run_api_e2e_tests.py            # 运行 API 和 E2E 测试 (新增)
├── test_web_api.py                  # API 集成测试 (新增)
├── test_e2e_workflow.py             # 端到端全流程测试 (新增)
├── test_agent.py                    # Agent 核心测试
├── test_agent_architecture.py       # Agent 架构测试
├── test_analyzers.py                # 分析器测试
├── test_api_client.py               # API 客户端测试
├── test_cache.py                    # 缓存测试
├── test_config.py                   # 配置测试
├── test_react.py                    # ReAct Agent 测试
└── test_strategies.py               # 策略测试
```

## 🚀 快速开始

### 1. 安装依赖

```bash
pip install pytest pytest-cov pytest-mock
```

### 2. 运行 API 集成测试和 E2E 测试

```bash
# 方式 1: 使用快速运行脚本
cd agents/DotaHelperAgent/tests
python run_api_e2e_tests.py

# 方式 2: 直接使用 pytest
pytest tests/test_web_api.py -v
pytest tests/test_e2e_workflow.py -v

# 方式 3: 运行所有测试
pytest tests/ -v
```

### 3. 运行特定测试

```bash
# 运行特定测试类
pytest tests/test_web_api.py::TestChatEndpoint -v

# 运行特定测试方法
pytest tests/test_web_api.py::TestChatEndpoint::test_chat_empty_query -v

# 运行英雄解析测试
pytest tests/test_web_api.py::TestHeroParsing -v

# 运行 E2E 英雄克制测试
pytest tests/test_e2e_workflow.py::TestEndToEndHeroCounter -v
```

## 📊 测试覆盖的功能

### API 集成测试 (test_web_api.py)

| 测试类 | 功能 | 测试点 |
|--------|------|--------|
| `TestHealthEndpoints` | 健康检查 | `/api/health` 端点响应 |
| `TestChatEndpoint` | 聊天接口 | 空查询、正常查询、带 session_id、带上下文 |
| `TestHeroParsing` | 英雄解析 | 规则解析、LLM 解析、混合语言、拼写错误 |
| `TestItemParsing` | 物品解析 | LLM 解析物品名称 |
| `TestFormatAnswer` | 答案格式化 | 推荐结果格式化、空数据处理 |
| `TestStaticFiles` | 静态文件 | 首页、CSS/JS 文件访问 |
| `TestEdgeCases` | 边界情况 | 超长查询、特殊字符、缺失 JSON |
| `TestIntegration` | 集成测试 | 完整聊天工作流 |

### 端到端测试 (test_e2e_workflow.py)

| 测试类 | 功能 | 测试场景 |
|--------|------|----------|
| `TestEndToEndHeroCounter` | 英雄克制推荐 | 完整流程、混合语言英雄名 |
| `TestEndToEndItemRecommendation` | 出装推荐 | 装备建议流程 |
| `TestEndToEndSkillBuild` | 技能加点 | 技能加点顺序 |
| `TestEndToEndMultiTurnConversation` | 多轮对话 | 上下文连续性 |
| `TestEndToEndErrorHandling` | 错误处理 | LLM 不可用回退、Controller 未初始化 |
| `TestEndToEndPerformance` | 性能测试 | 响应时间、并发请求 |
| `TestEndToEndCacheIntegration` | 缓存集成 | 缓存预热、重复查询 |
| `TestEndToEndMemorySystem` | 记忆系统 | 记忆存储 |

## 🔍 测试示例

### 1. 英雄克制推荐全流程

```python
# 用户查询
query = "对面有军团，我们选什么英雄克制？"

# 预期流程
1. ✅ API 接收请求
2. ✅ LLM 解析英雄名称 (军团 -> legion_commander)
3. ✅ Agent Controller 执行 ReAct 循环
4. ✅ 调用 analyze_counter_picks 工具
5. ✅ 返回推荐结果 (Axe, Legion Commander, Spirit Breaker)
```

### 2. 出装推荐流程

```python
# 用户查询
query = "敌法应该出什么装备？"

# 预期流程
1. ✅ API 接收请求
2. ✅ 解析英雄名称 (敌法 -> anti-mage)
3. ✅ Agent 调用 recommend_items 工具
4. ✅ 返回出装建议 (狂战斧、分身斧、深渊之刃)
```

### 3. 多轮对话测试

```python
# 第一轮
query1 = "对面有军团，选什么英雄克制？"
# 第二轮 (基于上一轮推荐)
query2 = "那这个英雄怎么出装？"

# 预期：保持 session_id，上下文连续
```

## 📈 测试覆盖率

### 查看覆盖率报告

```bash
# 生成 HTML 报告
pytest --cov=agents/DotaHelperAgent --cov-report=html tests/

# 在浏览器中打开
# Windows: start htmlcov/index.html
# Linux: open htmlcov/index.html
```

### 覆盖率目标

- API 层：> 90%
- Agent 控制器层：> 85%
- 核心业务层：> 80%
- 数据层：> 75%

## 🐛 调试技巧

### 1. 显示详细输出

```bash
# 使用 -s 显示 print 输出
pytest tests/test_web_api.py -v -s

# 显示日志
pytest tests/test_e2e_workflow.py -v --log-cli-level=DEBUG
```

### 2. 运行失败后进入调试

```bash
# 失败后进入 pdb 调试
pytest tests/test_web_api.py --pdb

# 失败后进入 IPython 调试
pytest tests/test_web_api.py --pdbcls=IPython.terminal.debugger:TerminalPdb
```

### 3. 只运行失败的测试

```bash
# 使用 --lf 只运行上次失败的测试
pytest tests/ --lf

# 使用 -x 遇到失败立即停止
pytest tests/ -x
```

## 🔧 Mock 和 Fixtures

### 常用 Fixtures

```python
# conftest.py 中定义的共享 fixtures
@pytest.fixture
def client():
    """Flask 测试客户端"""
    
@pytest.fixture
def mock_agent_controller():
    """模拟 Agent Controller"""
    
@pytest.fixture
def mock_llm_client():
    """模拟 LLM 客户端"""
```

### 使用示例

```python
def test_chat_with_mock(client, mock_agent_controller):
    """使用模拟对象的测试"""
    # 设置模拟响应
    mock_agent_controller.solve.return_value = {
        'success': True,
        'answer': {'answer': '测试响应'}
    }
    
    # 发送请求
    response = client.post('/api/chat', json={'query': '测试'})
    
    # 验证响应
    assert response.status_code == 200
```

## 📝 测试检查清单

在提交代码前，确保：

- [ ] 所有单元测试通过
- [ ] API 集成测试通过
- [ ] E2E 全流程测试通过
- [ ] 覆盖率达标 (>80%)
- [ ] 没有警告信息
- [ ] 错误处理测试通过
- [ ] 性能测试通过（响应时间 < 2s）

## 🎯 新增测试用例

当添加新功能时，需要：

1. **单元测试**: 测试核心逻辑
2. **API 测试**: 测试新的 API 端点
3. **E2E 测试**: 测试完整用户流程
4. **边界测试**: 测试异常情况和边界条件

### 示例：添加新的物品解析功能

```python
# 1. 单元测试 - tests/test_analyzers.py
def test_new_item_parser():
    # 测试解析逻辑
    pass

# 2. API 测试 - tests/test_web_api.py
def test_new_item_api(client):
    # 测试 API 端点
    response = client.post('/api/items', json={'hero': 'axe'})
    assert response.status_code == 200

# 3. E2E 测试 - tests/test_e2e_workflow.py
def test_new_item_e2e(e2e_client):
    # 测试完整流程
    response = e2e_client.post('/api/chat', json={
        'query': '斧王出什么新装备？'
    })
    assert response.status_code == 200
```

## 🚨 常见问题

### Q: 测试失败 "Agent Controller not initialized"

**A**: 确保在测试前初始化 Agent Controller：

```python
from web.app import initialize_agent_controller
initialize_agent_controller()
```

### Q: LLM 客户端未配置

**A**: 测试使用 Mock 对象，不需要真实 LLM：

```python
@patch('web.app.get_llm_client')
def test_with_mock(mock_get):
    mock_get.return_value = None  # 模拟 LLM 不可用
    # 测试会回退到规则解析
```

### Q: 测试运行很慢

**A**: 使用 `-n auto` 并行运行测试：

```bash
pip install pytest-xdist
pytest tests/ -n auto
```

## 📚 参考资源

- [pytest 官方文档](https://docs.pytest.org/)
- [Flask 测试文档](https://flask.palletsprojects.com/testing/)
- [unittest.mock 文档](https://docs.python.org/3/library/unittest.mock.html)

---

**最后更新**: 2026-04-24  
**维护者**: DotaHelperAgent Team
