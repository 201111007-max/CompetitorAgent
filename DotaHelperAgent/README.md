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

### 2️⃣ 启动服务

```bash
# 安装后端依赖
pip install -r requirements.txt

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
