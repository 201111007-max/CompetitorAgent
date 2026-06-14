# DotaHelperAgent - Dota 2 智能助手

## ⚡ Quick Start

**3 分钟快速体验 DotaHelperAgent：**

### 1️⃣ 配置 LLM（必需）

```bash
# 复制配置模板
cp config/llm_config.yaml.example config/llm_config.yaml

# 编辑配置文件，填入你的 API Key
# 支持 DeepSeek、OpenAI 兼容接口或本地部署
```

配置示例（DeepSeek）：
```yaml
llm:
  enabled: true
  base_url: "https://api.deepseek.com"
  model: "deepseek-v4-pro"
  # API Key 从环境变量读取：export DEEPSEEK_API_KEY=your_key
```

**环境变量配置（推荐）：**
```bash
# 复制环境变量模板
cp .env.example .env

# 编辑 .env 文件，填入你的 API Key
# DEEPSEEK_API_KEY=your_key_here
```

### 2️⃣ 启动服务

```bash
# 安装后端依赖（完整版）
pip install -r requirements.txt

# 安装可选依赖（推荐）
pip install duckduckgo-search python-dotenv  # 搜索功能、环境变量管理
pip install -r requirements-optional.txt     # Langfuse 监控

# 启动后端（端口 5000）
python web/app.py
```

```bash
# 安装前端依赖
cd frontend
npm install

# 启动前端（端口 3000）
npm run dev
```

### 3️⃣ 开始使用

打开浏览器访问 **http://localhost:3000**，即可体验：

- 🎯 **英雄克制推荐** - "对面有 PA、火枪，我该选什么？"
- 🛡️ **出装建议** - "打幻影刺客怎么出装？"
- 📊 **阵容分析** - "分析一下双方阵容优劣势"
- 🔥 **版本强势** - "当前版本哪些英雄强势？"

---

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
│  ┌─────────────────────────────────────┐    │
│  │   Metacognition (元认知能力)         │    │
│  │   - 知识边界评估                    │    │
│  │   - 置信度计算                      │    │
│  │   - 澄清请求生成                    │    │
│  └─────────────────────────────────────┘    │
└──────────────────────┬──────────────────────┘
                       │
        ┌──────────────┼──────────────┬──────────────┐
        ▼              ▼              ▼              ▼
┌──────────────┐ ┌──────────┐ ┌──────────────┐ ┌──────────────┐
│ Tool Registry │ │  Memory   │ │  Reflection  │ │  Knowledge   │
│ (15+ Tools)  │ │ (3 Types) │ │  Evaluator   │ │   System     │
└──────────────┘ └──────────┘ └──────────────┘ └──────────────┘
        │                                                      │
        └──────────────────────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────┐
│          Cache System (SQLite)               │
│  cache/cache_manager.py                      │
│  - 两级缓存（内存 + SQLite）                  │
│  - LRU 淘汰机制                              │
│  - 自动过期管理                              │
└─────────────────────────────────────────────┘
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
| 知识查询 | 向量检索、知识融合、多源知识整合 |
| 智能搜索 | DuckDuckGo 搜索最新 Dota 2 信息（可选） |

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

### 知识管理 (`knowledge/`)
- **ChromaDB** - 向量数据库
- **Sentence Transformers** - 向量嵌入
- **OpenAI API** - 向量嵌入（可选）
- **知识融合引擎** - 多源知识整合

### 搜索与缓存
- **DuckDuckGo Search** - 免费搜索（可选）
- **SQLite Cache** - 两级缓存系统（内存 + 持久化）

## 依赖说明

### 核心依赖（必需）

| 依赖 | 版本 | 说明 |
|------|------|------|
| flask | ≥2.0.0 | Web 框架 |
| flask-cors | ≥3.0.0 | 跨域支持 |
| requests | ≥2.28.0 | HTTP 客户端 |
| pyyaml | ≥6.0 | 配置文件解析 |
| python-dateutil | ≥2.8.0 | 日期处理 |
| chromadb | ≥0.5.0 | 向量数据库 |
| openai | ≥1.12.0 | OpenAI API 客户端 |
| sentence-transformers | ≥2.2.2 | 向量嵌入模型 |

**安装命令：**
```bash
pip install -r requirements.txt
```

### 可选依赖（推荐）

| 依赖 | 说明 | 安装命令 |
|------|------|---------|
| duckduckgo-search | DuckDuckGo 搜索功能 | `pip install duckduckgo-search` |
| python-dotenv | 环境变量管理 | `pip install python-dotenv` |
| langfuse | Agent 监控和追踪 | `pip install -r requirements-optional.txt` |

**一键安装所有可选依赖：**
```bash
pip install duckduckgo-search python-dotenv
pip install -r requirements-optional.txt
```

### 前端依赖

前端依赖位于 `frontend/package.json`，使用 npm 自动安装：

```bash
cd frontend
npm install
```

主要依赖包括：
- vue@3.5.34
- naive-ui@2.44.1
- pinia@3.0.4
- axios@1.16.1

## 项目结构

```
DotaHelperAgent/
├── frontend/                 # Vue 3 前端
│   ├── src/
│   │   ├── components/      # 组件 (ChatBox, HeroPanel, LogPanel)
│   │   ├── composables/     # 组合式函数 (useChatStream, useHeroQuery, useLogStream)
│   │   ├── stores/          # Pinia 状态管理 (chat, hero, log)
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
│   ├── llm_tool_selector.py     # LLM 工具选择器
│   └── metacognition/       # 元认知能力模块
│       ├── factory.py       # 工厂
│       ├── interfaces.py    # 接口定义
│       ├── llm_based.py     # LLM 驱动实现
│       └── rule_based.py    # 规则驱动实现
├── knowledge/                # 知识管理系统
│   ├── vector_store.py      # 向量数据库
│   ├── fusion_engine.py     # 知识融合引擎
│   ├── entity_alignment.py  # 实体对齐
│   ├── conflict_detector.py # 冲突检测
│   └── confidence_evaluator.py  # 置信度评估
├── tools/                    # Agent 工具
│   ├── base.py              # 工具基类
│   ├── agent_tools.py       # 工具工厂 (英雄、物品、技能工具)
│   ├── hero_tools.py        # 英雄分析工具
│   ├── build_tools.py       # 出装构建工具
│   ├── knowledge_tools.py   # 知识查询工具
│   └── search_tools.py      # 搜索工具 (DuckDuckGo)
├── analyzers/                # 分析器
│   ├── hero_analyzer.py     # 英雄分析
│   ├── hybrid_hero_analyzer.py  # 混合分析器
│   ├── item_recommender.py  # 物品推荐
│   └── skill_builder.py     # 技能加点
├── memory/                   # 记忆系统
│   └── memory.py            # SQLite 持久化
├── cache/                    # 缓存系统
│   └── cache_manager.py     # SQLite 缓存管理器
├── managers/                 # 数据管理器
│   └── matchup_data_manager.py  # 对局数据管理
├── strategies/               # 评分策略
├── utils/                    # 工具函数
│   ├── api_client.py        # OpenDota API 客户端
│   ├── llm_client.py        # LLM 客户端
│   └── localization.py      # 本地化 (中英)
├── config/                   # 配置文件
│   ├── llm_config.yaml      # LLM 配置
│   ├── knowledge_config.yaml # 知识管理配置
│   └── parallel_execution_config.yaml  # 并行执行配置
├── data/                     # 数据文件
│   ├── heroes_cn.json       # 英雄中文名映射
│   ├── items_cn.json        # 物品中文名映射
│   ├── matchups/            # 英雄对局数据
│   └── knowledge_base/      # 知识库数据
├── tests/                    # 测试
└── docs/                     # 文档
```

## 快速开始

### 1. 环境要求

- **操作系统**：Windows / macOS / Linux
- **Python**：3.10+ （推荐 3.11+）
- **Node.js**：18+ （推荐 20+）
- **内存**：至少 4GB RAM（向量数据库需要）
- **磁盘**：至少 2GB 可用空间
- **API Key**：LLM API Key (DeepSeek、OpenAI 或兼容接口)

### 2. 配置 LLM

```bash
# 复制配置模板
cp config/llm_config.yaml.example config/llm_config.yaml

# 编辑 llm_config.yaml，填入你的 API Key 和 Base URL
```

**环境变量配置（推荐）：**
```bash
# 复制环境变量模板
cp .env.example .env

# 编辑 .env 文件，配置 API Keys
# - DEEPSEEK_API_KEY: DeepSeek API Key（推荐）
# - OPENDOTA_API_KEY: OpenDota API Key（可选）
# - LANGFUSE_PUBLIC_KEY/SECRET_KEY: 监控配置（可选）
```

### 3. 安装依赖

**后端依赖：**
```bash
# 核心依赖（必需）
pip install -r requirements.txt

# 可选依赖（推荐安装）
pip install duckduckgo-search python-dotenv  # 搜索功能、环境变量管理
pip install -r requirements-optional.txt     # Langfuse 监控
```

**前端依赖：**
```bash
cd frontend
npm install
```

### 4. 启动服务

**启动后端：**
```bash
python web/app.py
# API 服务运行在 http://localhost:5000
```

**启动前端：**
```bash
cd frontend
npm run dev
# 前端运行在 http://localhost:3000，自动代理 API 到 :5000
```

### 5. 访问应用

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
| LLM 智能工具选择 (15+ Tools) | ✅ |
| 三层记忆系统 (SQLite) | ✅ |
| 多维度反思评估 | ✅ |
| 目标分解与追踪 | ✅ |
| 元认知能力 | ✅ |
| - 知识边界评估 | ✅ |
| - 置信度计算 | ✅ |
| - 澄清请求生成 | ✅ |
| 多轮对话上下文理解 | ✅ |
| SSE 流式输出 | ✅ |
| 混合模式 (LLM优先 + 数据兜底) | ✅ |
| **工具并行执行** | ✅ |
| - 依赖分析与拓扑排序 | ✅ |
| - 并发控制与超时管理 | ✅ |
| - 性能提升 50-80% | ✅ |
| - 宽松模式（部分失败不影响整体） | ✅ |
| **知识管理系统** | ✅ |
| - 向量检索 (ChromaDB) | ✅ |
| - 知识融合引擎 | ✅ |
| - 实体对齐与冲突检测 | ✅ |
| - 置信度评估 | ✅ |
| **缓存系统** | ✅ |
| - 两级缓存（内存 + SQLite） | ✅ |
| - LRU 淘汰机制 | ✅ |
| - 自动过期管理 | ✅ |
| **智能搜索** | ✅ |
| - DuckDuckGo 搜索（免费、无限制） | ✅ |
| - 自动添加 Dota 2 前缀 | ✅ |

## 文档

- [架构分析报告](docs/ARCHITECTURE_ANALYSIS.md)
- [前端迁移总结](frontend/MIGRATION_SUMMARY.md)
- [前端部署指南](frontend/DEPLOYMENT.md)

## 常见问题

### 1. 如何获取 API Key？

**DeepSeek API Key（推荐）：**
1. 访问 https://platform.deepseek.com/
2. 注册账号并登录
3. 在 API Keys 页面创建新的 API Key
4. 将 API Key 添加到 `.env` 文件或 `llm_config.yaml`

**OpenAI API Key：**
1. 访问 https://platform.openai.com/
2. 注册账号并登录
3. 在 API Keys 页面创建新的 API Key
4. 修改 `llm_config.yaml` 中的 `base_url` 和 `model`

### 2. 安装依赖时遇到问题？

**ChromaDB 安装失败：**
```bash
# Windows 用户可能需要安装 Visual C++ Build Tools
# 下载地址：https://visualstudio.microsoft.com/visual-cpp-build-tools/

# 或使用预编译版本
pip install chromadb --prefer-binary
```

**Sentence Transformers 下载慢：**
```bash
# 设置国内镜像
export HF_ENDPOINT=https://hf-mirror.com
pip install sentence-transformers
```

### 3. 如何验证安装是否成功？

**验证后端：**
```bash
# 启动后端
python web/app.py

# 访问健康检查接口
curl http://localhost:5000/api/health
# 应返回：{"status": "healthy", ...}
```

**验证前端：**
```bash
cd frontend
npm run dev

# 访问 http://localhost:3000
# 应看到聊天界面
```

### 4. 搜索功能不可用？

如果看到 "搜索功能不可用" 提示，需要安装 DuckDuckGo 搜索：

```bash
pip install duckduckgo-search
```

### 5. 向量数据库初始化慢？

首次运行时，向量数据库需要下载模型文件（约 500MB），请耐心等待。模型会缓存到本地，后续启动会很快。

### 6. 如何更新到最新版本？

```bash
# 拉取最新代码
git pull

# 更新后端依赖
pip install -r requirements.txt --upgrade

# 更新前端依赖
cd frontend
npm update
```
