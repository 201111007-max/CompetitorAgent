# 设计文档 55 — 部署/LLMOps：Dockerfile（multi-stage 双 target）+ docker-compose + benchmark 门禁化 + CI 补强

> 触发：2026-08-20 岗位差距分析（BOSS/猎聘 Agent 应用开发岗 JD 提炼）标出「无 Dockerfile、
> 无 CI 产物、单机运行——补 Dockerfile + docker-compose + GitHub Actions，是原型→生产叙事的分水岭」。
> 经代码核实该判断**说错一半**：CI 已存在（`.github/workflows/ci.yml`：ruff + mypy + pytest
> py3.10/3.11/3.12 矩阵 + benchmark 报告 artifact），真正缺口是 ① 无任何 Docker 化与部署文档、
> ② **benchmark 门禁不执法**——`benchmark.main()` 恒 `return 0`（benchmark.py:1489），
> 门禁指标只打印，质量退化 CI 不会变红。
> 用户拍板四决策（2026-08-20）：**Q1 范围** = Dockerfile + docker-compose + 部署文档 +
> CI 补强（CI 主体不动）；**Q2 multi-stage 双 target**（`full` 含 rag / `slim` 仅 web，一个
> Dockerfile 出两镜像）；**Q3 compose** = 基础 web_app 服务 + 可选 `observability` profile
> （Langfuse + Postgres，与 doc 54 exporter 联动一键全栈，默认不起）；**Q4 CI 补强** =
> benchmark `--gate` 门禁化 + docker build 验证 job，**不推镜像**（仓库是叙事载体）。
> 前置：问题 8（auth token/CORS 配置化）、32（rag extra）、52（rag-warmup 预热）、
> 54（LANGFUSE_* exporter）、29/36/49（benchmark 门禁阈值与 harness）。

## 1. 问题现状

### 1.1 核实后的真实状态

| 维度 | JD 判断 | 核实结论 |
|---|---|---|
| CI | 无 CI 产物 | ❌ 不准确——ci.yml 已有 lint/类型/三版本测试矩阵 + benchmark 报告 artifact |
| CI 质量门禁 | （未提及） | ❌ 真缺口——benchmark 步骤恒 exit 0，门禁指标不执法 |
| Docker/部署 | 无 Dockerfile、单机运行 | ✅ 属实——无 Dockerfile/compose/部署文档 |
| 容器化基础 | （未提及） | ✅ 意外得好（见 1.3）——缺口只是「没人写 Dockerfile」 |

### 1.2 三个具体问题

1. **无 Docker 化**：clone 后部署要手工装 Python 环境 + extras + 配环境变量，
   「一键起 web_app」不存在，原型→生产叙事断在最后一环。
2. **benchmark 门禁形同虚设（CI 侧）**：阈值常量存在且报告里判定，但退出码恒 0——
   退化只能人眼盯报告，CI 红绿与质量脱钩。
3. **LLMOps 闭环缺展示面**：doc 54 的 Langfuse exporter 需要用户自己起 server，
   没有 compose 一键全栈，「链路追踪」叙事落不了地。

### 1.3 现有可复用资产（容器化基础）

| 资产 | 位置 | 复用方式 |
|---|---|---|
| Web 入口参数化 | `web_app.py::main`（--host/--port，默认 127.0.0.1:8000） | 容器 CMD 显式 `--host 0.0.0.0`，本地默认不变 |
| 数据目录环境变量 | `COMPETITOR_AGENT_DATA_DIR` > `~/.competitor_agent`（secret_vault.py:171） | 卷挂载 `/data` 约定现成 |
| 密钥全环境变量 | OPENAI_API_KEY / COMPETITOR_AUTH_TOKEN / LANGFUSE_*（问题 8、doc 54） | 镜像零密钥，运行时注入 |
| extras 分层 | pyproject `[project.optional-dependencies]`（web/rag/mcp/eval/spa） | 双 target 各取所需 |
| 静态资源打包 | `package-data`（static/*.html/js/css/vendor） | pip install 后 Web 资源随包走，镜像无需额外拷贝 |
| CI 骨架 | `.github/workflows/ci.yml`（矩阵 + artifact） | 增量加 --gate 与 docker job，主体不动 |

## 2. 目标设计

### 2.1 Dockerfile（multi-stage 双 target，Q2）

```dockerfile
FROM python:3.12-slim AS base
# 共享层：工作目录、非 root 用户、pip 缓存挂载

FROM base AS slim          # 仅 .[web]（~300MB）：Web + 词袋 RAG 降级
FROM base AS full          # .[web,rag,mcp,eval]（~2GB+，torch 来自 sentence-transformers）
                           # 默认 target；compose build 指 full
```

- 运行约定：非 root 用户；`EXPOSE 8000`；`ENV COMPETITOR_AGENT_DATA_DIR=/data`；
  `VOLUME /data`；`CMD ["python","-m","competitor_agent.web_app","--host","0.0.0.0","--port","8000"]`。
- **镜像零密钥**：OPENAI_API_KEY 等全运行时 `-e`/env_file 注入；`.dockerignore`
  排除 tests/doc/reports/.git/.cache。
- **spa/playwright 不进镜像**（浏览器二进制过重）；部署文档标注为可选外挂能力。
- **bge-small 模型不在构建期预下载**：运行时首次启用缓存到 `/data` 卷（与 doc 52
  `_semantic_embedder_cached` 只探测缓存的纪律一致）；文档给 `rag-warmup`（doc 52 M2）
  容器内预热命令。

### 2.2 docker-compose（Q3）

- 基础服务 `web`：build target=full、ports `8000:8000`、volumes（data/reports）、
  `env_file: .env`（`.env` 已被 gitignore，提供 `.env.example` 模板列全部可用变量）。
- **`observability` profile**：`langfuse` + `postgres`（官方镜像锁 tag），`web` 服务
  经环境变量指向 `http://langfuse:3000`——doc 54 exporter 开箱联动；不加
  `--profile observability` 时完全不起，单机默认零额外负载。

### 2.3 benchmark 门禁化（Q4-a）

- `evaluation/benchmark.py` 加 `--gate` 开关：mock 模式跑完按现有门禁阈值
  （field_accuracy ≥ 0.90 / hallucination ≤ 0.05 / tool_selection ≥ 0.85 / trace = 1.0
  + doc 42 行为门禁）判定——**低于门禁 `return 1` 并逐项打印「指标/阈值/实测」差距**；
  不加 `--gate` 行为逐位不变（恒 0）。阈值复用现有门禁常量单一来源，不新造数值，
  HARNESS_VERSION 不变。
- CI benchmark 步骤加 `--gate`：质量退化 → CI 变红；报告 artifact 保留。

### 2.4 CI 补强（Q4-b）

- 新增 `docker` job：`docker build` 两 target（slim/full）+ 容器内 smoke
  （`python -c "import competitor_agent"` + `web_app --help` 跑通）；**不推镜像**。
- 触发条件沿用 paths 过滤 + Dockerfile/docker-compose.yml 变更纳入。

### 2.5 部署文档

- 新增 `competitor_agent/docs/deployment.md`：本地开发 / docker 单容器（两 target 取舍 +
  体积表）/ compose 全栈（含 observability profile）/ 环境变量清单 / 卷与数据持久化 /
  安全节（auth token、CORS、密钥纪律、rag-warmup 预热）。

### 2.6 明确不做

- **不推镜像**到 ghcr.io/Docker Hub（Q4：仓库是叙事载体，发布超范围）。
- **不做 k8s/helm**：单机 compose 足够支撑「原型→生产」叙事。
- **不改 CI 测试矩阵/ruff/mypy 现状**（已绿，不在本文档范围）。
- **不在镜像内置模型权重/真实密钥**（体积与安全双重纪律）。
- **不动 web_app 代码**：容器适配只靠现有 `--host`/环境变量参数，零代码改动。

## 3. 模块/接口设计

### 3.1 新增/修改点

- `Dockerfile`（仓库根，~40 行）+ `.dockerignore`。
- `docker-compose.yml`（~40 行）+ `.env.example`。
- `competitor_agent/evaluation/benchmark.py`（~30 行增量）：`--gate` 参数 + 门禁判定 +
  差距打印。
- `.github/workflows/ci.yml`（~25 行增量）：benchmark 步骤加 `--gate`；新增 docker job。
- `competitor_agent/docs/deployment.md`（新增）。

### 3.2 测试

- `tests/evaluation/test_benchmark_gate.py`：达标 `return 0` / 不达标 `return 1` 且输出含
  指标差距 / 默认不加 `--gate` 恒 0 回归 / real 无 Key 仍 return 2 不变。
- Docker/compose 不进 pytest（守护进程依赖）——CI docker job 即验证；本地手动
  `docker build` 两 target。
- 全量 `pytest -q` 不回归（`--gate` 默认关，现有评测测试零影响）。

## 4. 接入方式

- 配置：无新 yaml 字段；`.env.example` 仅模板注释；密钥纪律不变（gitignore 已覆盖 `.env`）。
- 依赖：零新 Python 依赖；Docker/compose 为主机侧工具。
- 兼容：不加 `--gate`、不 build 镜像 = 现状逐位不变；CI 默认路径只是 benchmark 步骤
  多了执法（mock 确定性门禁已绿，无突变风险）。
- 回退：删 4 个新增文件 + ci.yml 增量 + `--gate` 参数即完全回退。

## 5. 验证方式

- `pytest tests/evaluation/test_benchmark_gate.py -q` 全绿；全量不回归；ruff/mypy 改动文件通过。
- 手动：`docker build --target slim|full` 两 target 成功；`docker compose up` 起 web_app
  跑一次分析（mock 或真实 Key）；`--profile observability` 起 Langfuse，
  doc 54 M3 落地后验证 exporter 上报闭环。
- CI：push 后 docker job 绿；临时调高阈值验证 `--gate` 变红（验证后还原），确认门禁执法。

## 6. 实现优先级与工作量

| # | 里程碑 | 产出 | 工作量 |
|---|--------|------|--------|
| 0 | 设计文档 + 索引登记 | 本文档 + README/implementation_plan 登记 | 0.2d ✅ 2026-08-20 |
| 1 | 门禁执法 | benchmark `--gate` + 单测 + CI 接线 | 0.3d |
| 2 | Docker 化 | Dockerfile 双 target + .dockerignore + CI docker job | 0.5d |
| 3 | compose + 文档 | docker-compose + observability profile + .env.example + deployment.md | 0.5d |

## 7. 风险与缓解

1. **full 镜像体积 ~2GB+（torch）**：slim target 兜底 + 部署文档给体积/能力取舍表；
   构建用 pip 缓存挂载与分层减少重复下载。
2. **`--gate` 误红/争议**：阈值复用现有门禁常量单一来源，不新造数值；输出逐项差距
   可定位；HARNESS_VERSION 不变不重定。
3. **compose Langfuse 镜像版本漂移**：锁 tag（如 `langfuse/langfuse:2`、`postgres:16`），
   部署文档记录已验证版本组合。
4. **密钥泄漏**：镜像/compose/.env.example 全无真实密钥；CI 不需要 LLM Key
   （mock 门禁零成本零触网）。
5. **web_app 监听地址**：容器 CMD 显式 `--host 0.0.0.0`，本地默认 127.0.0.1 不变——
   文档说明差异原因（容器端口映射语义）。
