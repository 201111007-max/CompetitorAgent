# 日志系统测试

本目录包含日志系统的完整测试用例，包括单元测试、集成测试和API测试。

## 测试文件说明

### 1. test_log_api.py - 日志API接口测试

测试日志相关的REST API接口：

- **GET /api/logs** - 获取日志列表
  - 基础功能测试
  - 按session_id筛选
  - 按level筛选
  - 按component筛选
  - 限制返回数量
  - 组合筛选条件

- **GET /api/logs/files** - 获取日志文件列表
  - 验证文件信息结构
  - 日期和分片信息

- **GET /api/logs/files/<path>** - 获取日志文件内容
  - 正常读取
  - tail参数支持
  - 文件不存在处理
  - 路径遍历防护

- **POST /api/logs/clear** - 清空日志
  - 清空所有日志
  - 按session清空

- **GET /api/logs/stream** - SSE流式日志
  - SSE格式验证
  - 会话筛选

### 2. test_log_config.py - 日志配置模块测试

测试日志配置相关功能：

- **SessionFilter** - 会话过滤器
  - 添加session_id属性
  - 保留现有session_id
  - 添加component属性

- **JSONFormatter** - JSON格式化器
  - 基本格式化功能
  - 带session信息的格式化
  - 带额外数据的格式化

- **get_logger** - 获取日志记录器
  - 返回正确的logger对象
  - 上下文方法存在性
  - 上下文方法可调用性

- **setup_logging** - 设置日志系统
  - 返回根日志记录器
  - 创建处理器
  - 控制台输出控制
  - 日志级别设置

- **DailyTimedRotatingHandler** - 按日期轮转处理器
  - 创建日期目录
  - 创建part目录
  - 创建日志文件
  - 写入日志

- **日志文件辅助函数**
  - get_latest_log_files
  - get_log_files_by_date

### 3. test_memory_log_handler.py - 内存日志处理器测试

测试内存日志处理器功能：

- **基本功能**
  - 处理器初始化
  - emit方法存储日志
  - 格式化器支持

- **筛选功能**
  - 按级别筛选
  - 按组件筛选
  - 按会话ID筛选
  - 限制返回数量
  - 组合筛选条件

- **限制功能**
  - 最大条目数限制
  - FIFO行为

- **清空功能**
  - 清空所有日志
  - 按会话清空

- **线程安全**
  - 并发emit
  - 并发get_logs

- **订阅功能**
  - 订阅日志
  - 取消订阅

- **会话日志**
  - 获取会话日志
  - 不存在会话处理

### 4. test_log_integration.py - 日志系统集成测试

测试日志系统的完整工作流程：

- **完整工作流程**
  - 设置日志系统
  - 获取组件日志记录器
  - 记录不同级别日志
  - 验证内存日志
  - 验证文件日志

- **日志轮转**
  - 按大小轮转
  - 多part目录创建

- **会话隔离**
  - 不同会话日志隔离
  - 会话筛选验证

- **并发测试**
  - 多线程日志记录
  - 线程安全性验证

- **API集成**
  - API返回正确日志
  - API筛选功能
  - API清空功能

- **文件结构**
  - 目录结构验证
  - README文件创建

## 运行测试

### 运行所有日志测试

```bash
cd tests
pytest log/ -v
```

### 运行特定测试文件

```bash
# API测试
pytest log/test_log_api.py -v

# 配置测试
pytest log/test_log_config.py -v

# 内存处理器测试
pytest log/test_memory_log_handler.py -v

# 集成测试
pytest log/test_log_integration.py -v
```

### 运行特定测试类

```bash
# 只测试API接口
pytest log/test_log_api.py::TestLogAPI -v

# 只测试错误处理
pytest log/test_log_api.py::TestLogAPIErrorHandling -v
```

### 运行特定测试方法

```bash
pytest log/test_log_api.py::TestLogAPI::test_get_logs_success -v
```

### 生成测试报告

```bash
# HTML报告
pytest log/ -v --html=report.html

# XML报告（用于CI/CD）
pytest log/ -v --junitxml=report.xml

# 覆盖率报告
pytest log/ -v --cov=utils.log_config --cov=utils.memory_log_handler --cov-report=html
```

## 测试环境要求

- Python 3.8+
- pytest
- pytest-flask（用于API测试）
- pytest-cov（用于覆盖率）

## 安装依赖

```bash
pip install pytest pytest-flask pytest-cov
```

## 测试数据

测试使用临时目录和内存存储，不会污染实际日志文件。所有测试用例都是独立的，可以并行运行。

## 注意事项

1. **并发测试**：部分测试使用多线程，可能需要调整等待时间
2. **文件系统**：测试创建临时文件，确保有足够的磁盘空间
3. **时区**：日志时间戳使用系统时区
4. **编码**：测试使用UTF-8编码

## 调试技巧

```bash
# 显示详细的错误信息
pytest log/ -v --tb=long

# 在第一个错误处停止
pytest log/ -v -x

# 进入pdb调试模式
pytest log/ -v --pdb

# 显示print输出
pytest log/ -v -s
```
