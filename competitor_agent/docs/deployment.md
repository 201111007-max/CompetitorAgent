# 部署指南（设计文档 55）

覆盖三条路径：本地开发 → Docker 单容器（slim/full 取舍）→ docker-compose 全栈（含可选 Langfuse 可观测性）。

## 1. 本地开发

```bash
cd competitor_agent
pip install -e ".[dev]"          # 或按需 extras：web / rag / mcp / eval
export OPENAI_API_KEY=...        # 别名链：OPENAI_API_KEY > DEEPSEEK_API_KEY > LLM_API_KEY
python -m competitor_agent.web_app          # 默认 127.0.0.1:8000
```

数据落 `~/.competitor_agent`（`COMPETITOR_AGENT_DATA_DIR` 可改）。

## 2. Docker 单容器

仓库根一个 Dockerfile 出两个 target（multi-stage）：

| target | extras | 体积 | 能力 |
|---|---|---|---|
| `slim` | `.[web]` | ~300MB | Web + LLM 分析 + 词袋 RAG 降级 |
| `full` | `.[web,rag,mcp,eval]` | ~2GB+（torch 来自 sentence-transformers） | 全量：向量 RAG / MCP / 评测 |

```bash
docker build --target slim -t competitor-agent:slim .
docker build --target full -t competitor-agent:full .   # 默认/compose 用 full

docker run -d --name competitor-agent \
  -p 8000:8000 \
  -e OPENAI_API_KEY=<你的key> \
  -v competitor-data:/data \
  competitor-agent:full
# 打开 http://localhost:8000
```

运行约定：容器内**非 root**（uid 10001）；`EXPOSE 8000`；`COMPETITOR_AGENT_DATA_DIR=/data`。
CMD 显式 `--host 0.0.0.0`——容器端口映射语义要求监听全部接口；本地开发默认
`127.0.0.1` 不变，二者差异是有意的。

**模型预热（full 特有）**：bge 嵌入模型不在构建期预下载，首次启用向量检索时缓存到
`/data` 卷。可显式预热（唯一触网路径）：

```bash
docker exec competitor-agent python -m competitor_agent.cli rag-warmup
```

**spa/playwright 不进镜像**（浏览器二进制过重）；需要 SPA 采集时在容器外部署并自行外挂。

## 3. docker-compose 全栈

```bash
cp .env.example .env      # 填入 OPENAI_API_KEY 等
docker compose up -d      # 仅 web（build target=full + /data 卷 + env_file）

# 可选：可观测性全栈（doc 54 Langfuse exporter 开箱联动）
docker compose --profile observability up -d
# Langfuse UI: http://localhost:3000 （首启自建管理员账号，创建项目拿 public/secret key，
# 回填 .env 的 LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY 后 docker compose up -d 重建 web）
```

`observability` profile 不起时 Langfuse/Postgres 完全零负载；web 的 `LANGFUSE_HOST`
缺省指向 compose 内 `http://langfuse:3000`，在 `.env` 显式设置可改指外部 Langfuse Cloud。

## 4. 环境变量清单

| 变量 | 必填 | 说明 |
|---|---|---|
| `OPENAI_API_KEY` | 是（或别名） | LLM Key；别名 `DEEPSEEK_API_KEY` / `LLM_API_KEY` |
| `OPENAI_BASE_URL` | 否 | OpenAI 兼容端点（DeepSeek 等） |
| `COMPETITOR_AUTH_TOKEN` | 否 | 设置后 `/api/*` 需 `Authorization: Bearer`；空=不鉴权（仅本机） |
| `LANGFUSE_HOST` / `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` | 否 | 三者齐全才启用 doc 54 exporter；缺一即静默关闭 |
| `COMPETITOR_AGENT_DATA_DIR` | 否 | 数据目录；镜像内固定 `/data` |
| `POSTGRES_PASSWORD` / `NEXTAUTH_SECRET` / `SALT` | 否 | observability profile 的本地占位密钥，见安全节 |

CORS 来源白名单在 `competitor_agent/config/review_config.yaml` 的 `security.cors_origins`
（默认仅 `http://localhost:8000`），不走环境变量。

## 5. 卷与数据持久化

| 卷 | 容器路径 | 内容 |
|---|---|---|
| `competitor-data` | `/data` | 四层记忆、知识库（含 chromadb 向量）、`<data_dir>/reports` 报告归档、bge 模型缓存 |
| `langfuse-db` | `/var/lib/postgresql/data` | Langfuse 的 Postgres 数据（仅 observability profile） |

删卷即清空全部记忆与报告：`docker compose down -v`（谨慎）。

## 6. 安全

- **镜像零密钥**：所有密钥运行时 `-e` / `env_file` 注入；`.dockerignore` 排除 `.env*`，
  `.env` 已被 gitignore，`.env.example` 只有占位。
- **鉴权**：共享部署必须设 `COMPETITOR_AUTH_TOKEN`；空 token = 无鉴权，仅适合本机。
- **CORS**：默认仅放行 `http://localhost:8000`；跨域前端部署后改 yaml 白名单。
- **Langfuse 占位密钥**：compose 的 `NEXTAUTH_SECRET`/`SALT`/`POSTGRES_PASSWORD`
  缺省值仅供本机开发；暴露到共享网络前在 `.env` 覆盖为强随机值。
- **不推镜像**：本仓库 CI 只做 build 验证，不向任何 registry 发布（设计文档 55 Q4）。
