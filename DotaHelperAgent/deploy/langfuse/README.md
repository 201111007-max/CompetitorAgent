# Langfuse Self-hosted 部署指南

## 快速启动

### 1. 启动服务

```powershell
cd d:\trae_projects\first-agent\DotaHelperAgent\deploy\langfuse
docker-compose up -d
```

### 2. 访问 Web 界面

打开浏览器访问: http://localhost:3000

### 3. 创建账号和项目

1. 首次访问会引导你创建管理员账号
2. 登录后创建一个新项目
3. 进入项目设置 → API Keys
4. 复制 Public Key 和 Secret Key

### 4. 配置环境变量

在 PowerShell 中设置:

```powershell
$env:LANGFUSE_PUBLIC_KEY = "你的公钥"
$env:LANGFUSE_SECRET_KEY = "你的密钥"
$env:LANGFUSE_HOST = "http://localhost:3000"
```

或在 `.env` 文件中配置:

```
LANGFUSE_PUBLIC_KEY=你的公钥
LANGFUSE_SECRET_KEY=你的密钥
LANGFUSE_HOST=http://localhost:3000
```

## 常用命令

```powershell
# 查看服务状态
docker-compose ps

# 查看日志
docker-compose logs -f langfuse-server

# 停止服务
docker-compose down

# 完全清理（包括数据）
docker-compose down -v
```

## 端口说明

- **3000**: Langfuse Web 界面
- **5432**: PostgreSQL 数据库

## 注意事项

- 生产环境请修改 `NEXTAUTH_SECRET`、`SALT` 和 `ENCRYPTION_KEY`
- 数据持久化在 Docker volume `langfuse-db-data` 中
