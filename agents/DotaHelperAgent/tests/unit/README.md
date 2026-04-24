# Unit Tests

单元测试，测试独立的函数、类和模块。

## 测试文件

- `test_cache.py` - 缓存系统单元测试
- `test_config.py` - 配置模块单元测试

## 运行测试

```bash
# 运行所有单元测试
pytest unit/ -v

# 运行特定测试
pytest unit/test_cache.py -v
pytest unit/test_config.py -v

# 运行特定测试类
pytest unit/test_cache.py::TestCacheManagerInit -v
```

## 测试覆盖

### test_cache.py
- ✅ CacheManager 初始化
- ✅ 内存缓存操作
- ✅ 文件缓存操作
- ✅ 缓存过期机制
- ✅ 缓存大小限制
- ✅ 缓存键生成

### test_config.py
- ✅ AgentConfig 加载
- ✅ RateLimitConfig 配置
- ✅ CacheConfig 配置
- ✅ MatchupConfig 配置
- ✅ YAML 配置解析
- ✅ 配置验证

## 依赖

- 被测试的模块（cache, config 等）
- pytest fixtures (来自根目录 conftest.py)
- tempfile (临时目录创建)

## 特点

- 测试独立，不依赖外部服务
- 使用临时目录避免污染
- 快速执行（< 1 秒）
- 高覆盖率（> 90%）
