# DotaHelperAgent Test Suite

模块化的测试套件，按功能和测试类型组织。

## 📁 目录结构

```
tests/
├── api/                    # API 层测试
│   ├── test_web_api.py    # Web API 端点测试
│   ├── test_api_client.py # OpenDota API 客户端测试
│   └── README.md
│
├── core/                   # 核心组件测试
│   ├── test_agent.py      # Agent 基本功能测试
│   ├── test_agent_architecture.py
│   ├── test_analyzers.py  # 分析器测试
│   ├── test_react.py      # ReAct 循环测试
│   ├── test_strategies.py # 策略测试
│   └── README.md
│
├── unit/                   # 单元测试
│   ├── test_cache.py      # 缓存系统测试
│   ├── test_config.py     # 配置模块测试
│   └── README.md
│
├── e2e/                    # 端到端测试
│   ├── test_e2e_workflow.py
│   └── README.md
│
├── integration/            # 集成测试
│   └── README.md
│
├── conftest.py             # pytest 配置和共享 fixtures
├── run_tests.py            # 运行所有测试
├── run_api_e2e_tests.py    # 运行 API 和 E2E 测试
└── README.md               # 本文件
```

## 🚀 快速开始

### 运行所有测试

```bash
# 方式 1: 使用测试脚本
cd tests
python run_tests.py

# 方式 2: 直接使用 pytest
pytest tests/ -v
```

### 按模块运行测试

```bash
# API 层测试
pytest api/ -v

# 核心组件测试
pytest core/ -v

# 单元测试
pytest unit/ -v

# 端到端测试
pytest e2e/ -v
```

### 运行特定测试

```bash
# 运行 Web API 测试
pytest api/test_web_api.py -v

# 运行特定测试类
pytest api/test_web_api.py::TestChatEndpoint -v

# 运行特定测试方法
pytest api/test_web_api.py::TestChatEndpoint::test_chat_empty_query -v
```

## 📊 测试覆盖

| 模块 | 测试文件数 | 测试用例数 | 覆盖率目标 |
|------|-----------|-----------|-----------|
| api/ | 2 | 25+ | > 90% |
| core/ | 5 | 40+ | > 85% |
| unit/ | 2 | 20+ | > 90% |
| e2e/ | 1 | 12+ | > 80% |
| **总计** | **10** | **100+** | **> 85%** |

## 🧪 测试类型

### 单元测试 (unit/)
- 测试独立的函数、类和模块
- 不依赖外部服务
- 快速执行（< 1 秒）
- 高覆盖率（> 90%）

### 核心组件测试 (core/)
- 测试 Agent 核心逻辑
- 测试 Tool Registry 和 Tools
- 测试 ReAct 循环
- 使用 Mock 对象

### API 层测试 (api/)
- 测试 Flask 端点
- 测试请求/响应处理
- 测试英雄/物品解析
- 使用 Flask test client

### 端到端测试 (e2e/)
- 模拟真实用户场景
- 测试完整业务流程
- 多组件协作
- 性能测试

## 🔧 配置

### pytest.ini

```ini
[pytest]
testpaths = tests
python_files = test_*.py
python_classes = Test*
python_functions = test_*
addopts = -v --tb=short
```

### conftest.py

共享 fixtures:
- `temp_dir` - 临时目录
- `cache_config` - 缓存配置
- `agent_config` - Agent 配置
- `mock_api_response` - 模拟 API 响应

## 📈 覆盖率

```bash
# 生成覆盖率报告
pytest --cov=agents/DotaHelperAgent tests/ --cov-report=html

# 在浏览器中打开
start htmlcov/index.html  # Windows
open htmlcov/index.html   # Mac/Linux
```

## 🐛 调试技巧

```bash
# 显示 print 输出
pytest tests/ -v -s

# 遇到失败立即停止
pytest tests/ -x

# 失败后进入调试器
pytest tests/ --pdb

# 显示日志
pytest tests/ --log-cli-level=DEBUG
```

## 📝 添加新测试

1. 确定测试类型（unit/core/api/e2e）
2. 在对应目录下创建 `test_*.py` 文件
3. 使用 pytest 规范命名测试函数
4. 使用 fixtures 提供测试数据
5. 运行测试验证

### 示例

```python
# tests/api/test_new_feature.py
"""新功能的 API 测试"""

def test_new_feature(client):
    """测试新功能的 API 端点"""
    response = client.post('/api/new_feature', json={'data': 'test'})
    assert response.status_code == 200
    assert 'result' in response.get_json()
```

## 🎯 最佳实践

1. **命名规范**: 使用 `test_*.py` 文件名和 `test_*` 函数名
2. **Fixtures**: 使用 conftest.py 中的共享 fixtures
3. **Mock**: 对外部依赖使用 Mock 对象
4. **独立**: 测试之间相互独立，不依赖顺序
5. **快速**: 单元测试要快速，E2E 测试可以稍慢
6. **覆盖**: 覆盖正常情况和边界情况
7. **文档**: 每个模块添加 README.md 说明

## 🔗 相关文档

- [TESTING_GUIDE.md](TESTING_GUIDE.md) - 详细测试指南
- [api/README.md](api/README.md) - API 测试说明
- [core/README.md](core/README.md) - 核心测试说明
- [e2e/README.md](e2e/README.md) - E2E 测试说明
- [unit/README.md](unit/README.md) - 单元测试说明

---

**最后更新**: 2026-04-24  
**维护者**: DotaHelperAgent Team
