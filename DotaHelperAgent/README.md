# DotaHelperAgent - Dota 2 智能助手

基于 **ReAct Agent** 架构的 Dota 2 英雄推荐助手，支持英雄克制分析、出装推荐、技能加点等智能查询。

## 架构概述

```
┌─────────────────────────────────────────────┐
│              前端 (Vue 3 + TypeScript + Vite) │
│  frontend/                                   │
│  - 聊天界面、日志侧边栏、英雄选择器             │
└──────────────────────┬──────────────────────┘
                       │ /api/*
                       ▼
┌─────────────────────────────────────────────┐
│              后端 API (Flask)                │
│  web/app.py                                  │
│  - SSE 流式输出 /api/chat/stream              │
│  - 日志/Trace 接口                            │
└──────────────────────┬──────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────┐
│          AgentController (ReAct Loop)        │
│  core/agent_controller.py                    │
│  Think → Plan → Execute → Observe → Reflect  │
│  ┌─────────────────────────────────────┐    │
│  │   Parallel Executor (并行执行器)      │    │
│  │   - 依赖分析 → 拓扑排序              │    │
│  │   - 并发控制 → 超时管理              │    │
│  │   - 性能提升 50-80%                 │    │
│  └─────────────────────────────────────┘    │
└──────────────────────┬──────────────────────┘
                       │
        ┌──────────────┼──────────────┐
        ▼              ▼              ▼
┌──────────────┐ ┌──────────┐ ┌──────────────┐
│ Tool Registry │ │  Memory   │ │  Reflection  │
│ (10+ Tools)  │ │ (3 Types) │ │  Evaluator   │
└──────────────┘ └──────────┘ └──────────────┘
```

## 核心功能

| 功能 | 说明 |
|------|------|
| 英雄克制分析 | 根据敌方阵容推荐克制英雄 |
| 出装推荐 | 核心装备、针对出装、局势出装 |
| 技能加点 | 技能升级顺序、天赋树推荐 |
| 阵容分析 | 敌我双方阵容综合评估 |
| 版本强势 | 当前版本热门英雄查询 |
| 多轮对话 | 上下文理解、指代消解 |

## 技术栈

### 前端 (`frontend/`)
- **Vue 3** + **TypeScript** + **Vite**
- **Pinia** - 状态管理
- **Naive UI** - UI 组件库
- **Axios** - HTTP 客户端
- **SSE** - 流式输出

### 后端 (`web/`)
- **Flask** - API 服务
- **ReAct Agent** - 推理循环 (Think→Plan→Execute→Observe→Reflect)
- **LLM** - 智能工具选择与参数提取
- **OpenDota API** - 游戏数据来源
- **SQLite** - 三层记忆系统 (短期/长期/情景)
- **SSE** - 流式输出
- **Asyncio** - 异步并行执行（工具并发、依赖分析、拓扑排序）

## 项目结构

```
DotaHelperAgent/
├── frontend/                 # Vue 3 前端
│   ├── src/
│   │   ├── components/      # 组件 (chat/, sidebar/, common/)
│   │   ├── composables/     # 组合式函数 (useSSE, useChat)
│   │   ├── services/        # API 服务
│   │   ├── stores/          # Pinia 状态管理
│   │   ├── views/           # 页面视图
│   │   └── types/           # TypeScript 类型
│   └── vite.config.ts       # Vite 配置
├── web/                      # Flask API 后端
│   └── app.py               # API 入口
├── core/                     # Agent 核心
│   ├── agent_controller.py  # ReAct 循环控制器
│   ├── tool_registry.py     # 工具注册表
│   ├── reflection_evaluator.py  # 反思评估器
│   ├── goal_planner.py      # 目标分解
│   ├── conversation_manager.py  # 会话管理
│   ├── context_augmenter.py # 上下文增强
│   ├── dependency_analyzer.py   # 依赖分析器
│   ├── parallel_executor.py     # 并行执行器
│   └── parallel_execution_config.py  # 并行执行配置
├── analyzers/                # 分析器
│   ├── hero_analyzer.py     # 英雄分析
│   ├── item_recommender.py  # 物品推荐
│   └── skill_builder.py     # 技能加点
├── tools/                    # Agent 工具
│   └── agent_tools.py       # 工具工厂 (10+ Tools)
├── memory/                   # 记忆系统
│   └── memory.py            # SQLite 持久化
├── strategies/               # 评分策略
├── utils/                    # 工具函数
│   ├── api_client.py        # OpenDota API 客户端
│   ├── llm_client.py        # LLM 客户端
│   └── localization.py      # 本地化 (中英)
├── config/                   # 配置文件
│   └── llm_config.yaml      # LLM 配置
├── data/                     # 数据文件
├── tests/                    # 测试
└── docs/                     # 文档
```

## 快速开始

### 1. 环境要求

- Python 3.10+
- Node.js 18+
- LLM API Key (OpenAI 兼容接口)

### 2. 配置 LLM

```bash
cp config/llm_config.yaml.example config/llm_config.yaml
# 编辑 llm_config.yaml，填入你的 API Key 和 Base URL
```

### 3. 启动后端

```bash
pip install flask flask-cors schedule pyyaml requests
python web/app.py
# API 服务运行在 http://localhost:5000
```

### 4. 启动前端

```bash
cd frontend
npm install
npm run dev
# 前端运行在 http://localhost:3000，自动代理 API 到 :5000
```

### 5. 访问

打开浏览器访问 **http://localhost:3000**

## API 接口

| 端点 | 方法 | 说明 |
|------|------|------|
| `/` | GET | 服务信息 |
| `/api/health` | GET | 健康检查 |
| `/api/chat` | POST | 聊天接口 |
| `/api/chat/stream` | POST | 流式聊天 (SSE) |
| `/api/tools` | GET | 工具列表 |
| `/api/parse/preview` | POST | 英雄解析预览 |
| `/api/logs` | GET | 日志查询 |
| `/api/logs/stream` | GET | 实时日志流 |
| `/api/trace/<id>` | GET | Trace 追踪 |
| `/api/memory/stats` | GET | 记忆系统统计 |

## ReAct Agent 能力

| 能力 | 状态 |
|------|------|
| Think → Plan → Execute → Observe → Reflect | ✅ |
| LLM 智能工具选择 (10+ Tools) | ✅ |
| 三层记忆系统 (SQLite) | ✅ |
| 多维度反思评估 | ✅ |
| 目标分解与追踪 | ✅ |
| 元认知能力 | ✅ |
| 多轮对话上下文理解 | ✅ |
| SSE 流式输出 | ✅ |
| 混合模式 (LLM优先 + 数据兜底) | ✅ |
| **工具并行执行** | ✅ |
| - 依赖分析与拓扑排序 | ✅ |
| - 并发控制与超时管理 | ✅ |
| - 性能提升 50-80% | ✅ |
| - 宽松模式（部分失败不影响整体） | ✅ |

## 文档

- [架构分析报告](docs/ARCHITECTURE_ANALYSIS.md)
- [前端迁移总结](frontend/MIGRATION_SUMMARY.md)
- [前端部署指南](frontend/DEPLOYMENT.md)
