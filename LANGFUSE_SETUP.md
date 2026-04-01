# Langfuse 配置指南

## 1. 什么是 Langfuse？

Langfuse 是一个**开源**的 LLM 工程平台，提供：
- ✅ 完整的调用追踪
- ✅ 评估和测试
- ✅ Prompt 管理
- ✅ 指标和仪表板
- ✅ 完全自托管（数据自主）

## 2. 安装 Langfuse

### 方式 1：Docker（推荐）

```bash
docker run -d \
  -p 3000:3000 \
  -e DATABASE_URL="postgresql://postgres:postgres@db:5432/postgres" \
  -e SALT="random-salt" \
  -e NEXTAUTH_SECRET="random-secret" \
  -e NEXTAUTH_URL="http://localhost:3000" \
  langfuse/langfuse
```

### 方式 2：Docker Compose

创建 `docker-compose.yml`：

```yaml
version: '3.8'

services:
  langfuse:
    image: langfuse/langfuse:latest
    ports:
      - "3000:3000"
    environment:
      - DATABASE_URL=postgresql://postgres:postgres@db:5432/postgres
      - SALT=random-salt
      - NEXTAUTH_SECRET=random-secret
      - NEXTAUTH_URL=http://localhost:3000
    depends_on:
      - db

  db:
    image: postgres:15
    environment:
      - POSTGRES_USER=postgres
      - POSTGRES_PASSWORD=postgres
      - POSTGRES_DB=postgres
    volumes:
      - postgres_data:/var/lib/postgresql/data

volumes:
  postgres_data:
```

启动：
```bash
docker-compose up -d
```

## 3. 配置环境变量

复制 `.env.example` 为 `.env`：

```bash
cp .env.example .env
```

编辑 `.env` 文件：

```env
# Langfuse Configuration
LANGFUSE_PUBLIC_KEY=pk-lf-your-public-key-here
LANGFUSE_SECRET_KEY=sk-lf-your-secret-key-here
LANGFUSE_HOST=http://localhost:3000
```

### 获取 API Keys

1. 访问 `http://localhost:3000`
2. 注册/登录账号
3. 进入 Settings → API Keys
4. 创建新的 API Key

## 4. 在代码中使用

### 方式 1：初始化配置

```python
from config.settings import Config

# 初始化 Langfuse
Config.init_langfuse()
```

### 方式 2：使用装饰器追踪函数

```python
from langfuse import observe

@observe(name="my_function")
def my_function(input: str) -> str:
    # 你的业务逻辑
    return result
```

### 方式 3：手动追踪

```python
from langfuse import Langfuse

langfuse = Langfuse(
    public_key=Config.LANGFUSE_PUBLIC_KEY,
    secret_key=Config.LANGFUSE_SECRET_KEY,
    host=Config.LANGFUSE_HOST
)

trace = langfuse.trace(name="my-trace")
span = trace.span(name="my-span")
span.end(output={"result": "success"})
```

## 5. 运行示例

```bash
# 运行简单示例
python app/langfuse_example.py

# 运行 LangChain 集成示例
python app/langchain_with_langfuse.py
```

## 6. 查看监控数据

访问 `http://localhost:3000` 查看：

- ✅ 完整的调用追踪
- ✅ 延迟和性能指标
- ✅ Token 使用统计
- ✅ 错误和异常
- ✅ 用户反馈

## 7. 常用装饰器参数

```python
@observe(
    name="my_function",      # 运行名称
    as_type="chain",         # chain, tool, retriever, llm
    capture_input=True,      # 捕获输入
    capture_output=True,     # 捕获输出
    metadata={"version": "1.0"}  # 元数据
)
```

## 8. Langfuse vs LangSmith

| 特性 | Langfuse | LangSmith |
|------|----------|-----------|
| 开源 | ✅ MIT | ❌ 闭源 |
| 自托管 | ✅ | ❌ |
| 免费 | ✅ 完全免费 | ⚠️ 有限免费 |
| 数据自主 | ✅ | ❌ |
| LangChain 集成 | ✅ | ✅ 原生 |
| 社区活跃度 | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ |

## 9. 最佳实践

1. **本地开发使用 Docker**：快速部署 Langfuse
2. **生产环境配置**：使用云服务或自建集群
3. **合理命名**：使用清晰的 `name` 参数
4. **添加元数据**：记录版本、环境等信息
5. **定期清理数据**：避免数据库过大

## 10. 故障排除

### 问题：无法连接到 Langfuse

```bash
# 检查 Docker 容器是否运行
docker ps | grep langfuse

# 查看日志
docker logs langfuse

# 重启容器
docker restart langfuse
```

### 问题：API Key 无效

- 确保在 Langfuse 界面创建了 API Key
- 检查 `.env` 文件中的 Key 是否正确
- 重启 Python 进程重新加载环境变量
