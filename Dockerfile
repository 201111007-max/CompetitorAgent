# syntax=docker/dockerfile:1
# 设计文档 55 M2：multi-stage 双 target（一个 Dockerfile 出两镜像）
#   slim —— 仅 .[web]（~300MB）：Web + 词袋 RAG 降级
#   full —— .[web,rag,mcp,eval]（~2GB+，torch 来自 sentence-transformers），默认/compose target
# 运行约定：非 root；EXPOSE 8000；COMPETITOR_AGENT_DATA_DIR=/data（卷挂载持久化）。
# 镜像零密钥：OPENAI_API_KEY / COMPETITOR_AUTH_TOKEN / LANGFUSE_* 全部运行时 -e/env_file 注入。
# spa/playwright 不进镜像（浏览器二进制过重）；bge 模型不构建期预下载，
# 运行时首次启用缓存到 /data 卷（doc 52 `_semantic_embedder_cached` 只探测缓存的纪律一致）。
FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    COMPETITOR_AGENT_DATA_DIR=/data

WORKDIR /app

# pyproject packages.find where=[".."]：包目录须位于项目目录上一级（/app）下
COPY competitor_agent/ /app/competitor_agent/

RUN useradd --create-home --uid 10001 agent \
    && mkdir -p /data \
    && chown -R agent:agent /data

EXPOSE 8000
VOLUME ["/data"]
# 容器端口映射语义要求监听 0.0.0.0；本地默认 127.0.0.1 不变（见 docs/deployment.md）
CMD ["python", "-m", "competitor_agent.web_app", "--host", "0.0.0.0", "--port", "8000"]

FROM base AS slim
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install "/app/competitor_agent[web]"
USER agent

FROM base AS full
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install "/app/competitor_agent[web,rag,mcp,eval]"
USER agent

# 可选：启用 crawl4ai 浏览器渲染抓取（设计文档 71 §3.4/§10 P3）
# 体积 +~200MB，仅需渲染级抓取时用 `--target crawler4ai` 构建；slim/full 默认不含。
# crawl4ai 运行时默认关（collector.crawler.browser_pool=0），浏览器写入 /data 卷可持久化复用。
FROM base AS crawler4ai
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install "/app/competitor_agent[crawl4ai]" \
    && python -m crawl4ai.setup --quick
USER agent
