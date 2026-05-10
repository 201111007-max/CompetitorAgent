# API Layer Tests

测试 Web API 层，包括 Flask 端点、请求/响应处理等。

## 测试文件

- `test_web_api.py` - Web API 端点集成测试
- `test_api_client.py` - OpenDota API 客户端测试

## 运行测试

```bash
# 运行所有 API 测试
pytest api/ -v

# 运行特定测试
pytest api/test_web_api.py -v
pytest api/test_api_client.py -v

# 运行特定测试类
pytest api/test_web_api.py::TestHealthEndpoints -v
```

## 测试覆盖

- ✅ 健康检查端点 (`/api/health`)
- ✅ 聊天接口 (`/api/chat`)
- ✅ 英雄解析功能
- ✅ 物品解析功能
- ✅ 静态文件服务
- ✅ 错误处理
- ✅ API 客户端速率限制
- ✅ API 客户端缓存机制

## 依赖

- Flask test client
- pytest fixtures (来自根目录 conftest.py)
