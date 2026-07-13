# DotaHelperAgent 精简清理报告

> 生成时间：2026-07-13 22:30:25
> 项目路径：`D:\trae_projects\first-agent\DotaHelperAgent`

## 一、精简目标

将 DotaHelperAgent 精简为仅保留以下核心功能：

1. **英雄分析、出装推荐、问答** - 现有功能保留
2. **比赛录像分析及总结** - 待新建
3. **前端页面展示** - 保留并调整
4. **分析结果保存为 MD 文件** - 待新建

## 二、删除统计概览

| 指标 | 数值 |
|------|------|
| 待删除目录数 | 16 |
| 待删除文件数 | 32 |
| 涉及文件总数 | 183 |
| 释放空间 | 2.7 MB |

## 三、按模块分类的删除清单

### 配置文件 (`config/`)

| 类型 | 路径 | 删除原因 |
|------|------|---------|
| FILE | `config/feedback_config.yaml` | 反馈学习配置 |
| FILE | `config/gsi_config.yaml` | GSI 配置 |
| FILE | `config/knowledge_config.yaml` | 知识管理配置 |
| FILE | `config/parallel_execution_config.yaml` | 并行执行配置（暂不需要） |
| FILE | `config/prompts/decision.yaml` | 决策 Prompt，为 GSI 决策引擎服务 |
| FILE | `config/prompts/recommendation.yaml` | 推荐 Prompt，为 GSI 推荐服务 |
| FILE | `config/recommendation_config.yaml` | 推荐系统配置 |

### Agent 核心模块（决策引擎/事件触发） (`core/`)

| 类型 | 路径 | 删除原因 |
|------|------|---------|
| DIR | `core/decision` | 决策融合器（规则/数据/LLM引擎），为 GSI 主动推荐服务 |
| FILE | `core/event_trigger.py` | 事件触发器，为 GSI 主动推荐服务 |

### 部署配置 (`deploy/`)

| 类型 | 路径 | 删除原因 |
|------|------|---------|
| DIR | `deploy` | Langfuse Docker 部署配置，非核心 |

### 评估系统 (`evaluation/`)

| 类型 | 路径 | 删除原因 |
|------|------|---------|
| DIR | `evaluation` | Agent 质量评估系统，非核心需求 |

### 反馈学习系统 (`feedback/`)

| 类型 | 路径 | 删除原因 |
|------|------|---------|
| DIR | `feedback` | 用户反馈学习系统，为 GSI 推荐优化服务 |

### 前端文件 (`frontend/`)

| 类型 | 路径 | 删除原因 |
|------|------|---------|
| FILE | `frontend/src/components/GsiStatusPanel.vue` | GSI 状态面板组件 |
| FILE | `frontend/src/composables/useGsiStream.ts` | GSI 流式处理 Hook |
| FILE | `frontend/src/composables/useRecommendationStream.ts` | 推荐流式处理 Hook |
| FILE | `frontend/src/types/gsi.ts` | GSI 类型定义 |

### GSI 实时游戏状态模块 (`gsi/`)

| 类型 | 路径 | 删除原因 |
|------|------|---------|
| DIR | `gsi` | GSI 实时游戏状态监控模块，与目标功能无关 |

### 知识管理系统 (`knowledge/`)

| 类型 | 路径 | 删除原因 |
|------|------|---------|
| DIR | `knowledge` | ChromaDB 向量检索系统，非核心需求，复杂度高 |

### 资源文件（语音） (`resources/`)

| 类型 | 路径 | 删除原因 |
|------|------|---------|
| DIR | `resources/voice` | 13 个语音提醒 .wav 文件，GSI 事件提醒专用 |

### 脚本文件 (`scripts/`)

| 类型 | 路径 | 删除原因 |
|------|------|---------|
| DIR | `scripts/evaluation` | 评估脚本 |
| FILE | `scripts/import_knowledge.py` | 知识导入脚本，依赖已删除的 knowledge 模块 |

### Skill 模块 (`skills/`)

| 类型 | 路径 | 删除原因 |
|------|------|---------|
| DIR | `skills/knowledge_query` | 知识查询 Skill，依赖已删除的 knowledge 模块 |
| DIR | `skills/lineup_analyzer` | 阵容分析 Skill，非核心功能 |
| DIR | `skills/meta_analyzer` | 元分析 Skill，非核心功能 |

### 评分策略 (`strategies/`)

| 类型 | 路径 | 删除原因 |
|------|------|---------|
| DIR | `strategies` | 评分策略模块，仅服务于旧分析流程 |

### 测试文件 (`tests/`)

| 类型 | 路径 | 删除原因 |
|------|------|---------|
| DIR | `tests/evaluation` | 评估系统测试 |
| DIR | `tests/feedback` | 反馈系统测试 |
| DIR | `tests/gsi` | GSI 模块测试 |
| FILE | `tests/integration/test_feedback_integration.py` | 反馈集成测试 |
| FILE | `tests/integration/test_parallel_execution_integration.py` | 并行执行集成测试 |
| FILE | `tests/integration/test_voice_integration.py` | 语音集成测试 |
| DIR | `tests/knowledge` | 知识系统测试 |
| FILE | `tests/skills/test_knowledge_query.py` | 知识查询 Skill 测试 |
| FILE | `tests/skills/test_lineup_analyzer.py` | 阵容分析 Skill 测试 |
| FILE | `tests/skills/test_meta_analyzer.py` | 元分析 Skill 测试 |
| FILE | `tests/test_data_engine.py` | 数据引擎测试（decision 模块） |
| FILE | `tests/test_decision_fusion.py` | 决策融合测试（decision 模块） |
| FILE | `tests/test_llm_engine.py` | LLM 引擎测试（decision 模块） |
| FILE | `tests/test_rule_engine.py` | 规则引擎测试（decision 模块） |
| FILE | `tests/unit/test_background_loader.py` | 后台加载器测试 |
| FILE | `tests/unit/test_event_trigger.py` | 事件触发器测试 |
| FILE | `tests/unit/test_recommendation_tools.py` | 推荐工具测试 |
| FILE | `tests/utils/test_voice_player.py` | 语音播放器测试 |

### 工具层（GSI/推荐/知识工具） (`tools/`)

| 类型 | 路径 | 删除原因 |
|------|------|---------|
| FILE | `tools/gsi_tools.py` | GSI 数据工具 |
| FILE | `tools/knowledge_tools.py` | 知识管理工具，依赖已删除的 knowledge 模块 |
| FILE | `tools/recommendation_tools.py` | 推荐系统工具，为 GSI 主动推荐服务 |

### 工具函数 (`utils/`)

| 类型 | 路径 | 删除原因 |
|------|------|---------|
| FILE | `utils/background_loader.py` | 知识数据后台加载器，依赖已删除的 knowledge 模块 |
| FILE | `utils/voice_player.py` | 语音播放器，GSI 事件提醒专用 |

## 四、保留模块清单

### 4.1 后端保留

| 路径 | 说明 |
|------|------|
| `core/agent.py` | Agent 主类 |
| `core/agent_controller.py` | ReAct 循环控制器 |
| `core/tool_registry.py` | 工具注册表 |
| `core/llm_tool_selector.py` | LLM 智能工具选择器 |
| `core/conversation_manager.py` | 会话管理器 |
| `core/context_augmenter.py` | 上下文增强器 |
| `core/goal_planner.py` | 目标分解与追踪 |
| `core/reflection_evaluator.py` | 多维度反思评估 |
| `core/dependency_analyzer.py` | 依赖分析器 |
| `core/parallel_executor.py` | 并行执行器 |
| `core/parallel_execution_config.py` | 并行执行配置 |
| `core/hybrid_base.py` | 混合模式基类 |
| `core/config.py` | 配置类定义 |
| `core/metacognition/` | 元认知模块（LLM 驱动评估） |
| `analyzers/` | 分析器（英雄/物品/技能） |
| `tools/base.py` | 工具基类 |
| `tools/agent_tools.py` | 工具工厂 |
| `tools/hero_tools.py` | 英雄分析工具 |
| `tools/build_tools.py` | 出装/技能推荐工具 |
| `tools/search_tools.py` | 搜索工具（问答用） |
| `managers/` | 数据管理器 |
| `cache/` | 缓存系统 |
| `memory/` | 记忆系统 |
| `utils/api_client.py` | OpenDota API 客户端 |
| `utils/llm_client.py` | LLM 客户端 |
| `utils/localization.py` | 本地化工具 |
| `utils/log_config.py` | 日志配置 |
| `utils/memory_log_handler.py` | 内存日志处理器 |
| `utils/prompt_manager.py` | Prompt 管理器 |
| `utils/prompt_strategy.py` | Prompt 策略 |
| `utils/trace_context.py` | Trace 上下文 |
| `utils/trace_persistence.py` | Trace 持久化 |
| `utils/langfuse_adapter.py` | Langfuse 适配器（可选） |
| `utils/langfuse_config.py` | Langfuse 配置 |
| `web/app.py` | Flask API 后端（需精简 API 端点） |
| `skills/base.py` | Skill 基类 |
| `skills/registry.py` | Skill 注册表 |
| `skills/fallback.py` | 降级处理 |
| `skills/exceptions.py` | 异常定义 |
| `skills/dialogue_understander/` | 对话理解 Skill |
| `skills/web_search/` | 网络搜索 Skill |
| `data/` | 数据文件（英雄/物品/对局数据） |
| `config/llm_config.yaml*` | LLM 配置 |
| `config/langfuse_config.yaml` | Langfuse 配置 |
| `config/prompt_config.yaml` | Prompt 配置 |
| `config/skills_config.yaml` | Skill 配置 |
| `config/prompts/system_prompts.yaml` | 系统 Prompt |
| `config/prompts/hero_analysis.yaml` | 英雄分析 Prompt |
| `config/prompts/skill_build.yaml` | 技能加点 Prompt |
| `config/prompts/skills.yaml` | Skill Prompt |

### 4.2 前端保留

| 路径 | 说明 |
|------|------|
| `frontend/src/components/ChatBox.vue` | 聊天主界面 |
| `frontend/src/components/HeroPanel.vue` | 英雄选择面板 |
| `frontend/src/components/LogPanel.vue` | 日志侧边栏 |
| `frontend/src/components/MarkdownRenderer.vue` | Markdown 渲染 |
| `frontend/src/components/MessageActions.vue` | 消息操作 |
| `frontend/src/components/RightDrawer.vue` | 右侧抽屉 |
| `frontend/src/components/SidePanel.vue` | 侧边面板 |
| `frontend/src/components/ThinkingSteps.vue` | 思考步骤展示 |
| `frontend/src/components/TopStatusBar.vue` | 顶部状态栏 |
| `frontend/src/composables/useChatStream.ts` | 聊天流式处理 |
| `frontend/src/composables/useHeroQuery.ts` | 英雄查询 Hook |
| `frontend/src/composables/useLogStream.ts` | 日志流式处理 |
| `frontend/src/stores/chat.ts` | 聊天状态 |
| `frontend/src/stores/hero.ts` | 英雄状态 |
| `frontend/src/stores/log.ts` | 日志状态 |
| `frontend/src/types/chat.ts` | 聊天类型 |
| `frontend/src/types/hero.ts` | 英雄类型 |
| `frontend/src/types/log.ts` | 日志类型 |
| `frontend/src/styles/` | 样式文件 |
| `frontend/src/App.vue` | 根组件 |
| `frontend/src/main.ts` | 入口文件 |
| `frontend/src/router/` | 路由配置 |
| `frontend/src/views/` | 视图组件 |

## 五、待新建模块

| 模块 | 路径 | 说明 |
|------|------|------|
| 比赛录像分析器 | `analyzers/match_analyzer.py` | 通过 OpenDota API 获取比赛数据，分析关键事件和玩家表现 |
| 比赛分析工具 | `tools/match_tools.py` | Agent 工具层：获取比赛、总结比赛 |
| MD 导出器 | `utils/markdown_export.py` | 将分析结果格式化为 Markdown 并保存为文件 |
| 比赛分析 API | `web/app.py` 新增端点 | `/api/match/analyze`, `/api/match/export` |
| 前端比赛分析页 | `frontend/src/views/MatchAnalysis.vue` | 输入比赛 ID → 展示分析 → 导出 MD |
| 比赛分析配置 | `config/prompts/match_analysis.yaml` | 比赛分析 Prompt 模板 |

## 六、web/app.py API 端点清理

### 6.1 待删除的 API 端点（约 22 个）

| 路由 | 方法 | 原功能 |
|------|------|--------|
| `/api/gsi/events` | GET | GSI 事件 SSE 推送 |
| `/api/gsi/state` | GET | GSI 状态查询 |
| `/api/gsi/recommendations` | GET | 主动推荐 SSE 推送 |
| `/api/gsi/recommendation/status` | GET | 推荐系统状态 |
| `/api/gsi/recommendation/query` | GET | 主动推荐查询 |
| `/api/gsi/data` | POST | GSI 数据推送（测试用） |
| `/api/voice/status` | GET | 语音播放器状态 |
| `/api/voice/toggle` | POST | 语音开关 |
| `/api/voice/volume` | POST | 语音音量 |
| `/api/voice/event` | POST | 事件语音开关 |
| `/api/feedback/explicit` | POST | 显式反馈提交 |
| `/api/feedback/implicit` | POST | 隐式反馈提交 |
| `/api/feedback/stats` | GET | 反馈统计查询 |
| `/api/feedback/strategy` | GET | 策略参数查询 |
| `/api/feedback/strategy/reset` | POST | 策略参数重置 |
| `/api/feedback/calibrate` | POST | 手动校准 |
| `/api/feedback` | POST | Langfuse 反馈 |
| `/api/generate_hero_query` | POST | 随机英雄查询生成 |
| `/api/test_tools` | GET | 工具测试（可保留或移除） |

### 6.2 保留的 API 端点（约 30 个）

| 路由 | 方法 | 功能 |
|------|------|------|
| `/` | GET | 服务根路径 |
| `/api/health` | GET | 健康检查 |
| `/api/chat` | POST | Agent 聊天（同步） |
| `/api/chat/stream` | POST | Agent 聊天（SSE 流式） |
| `/api/parse/preview` | POST | 解析预览 |
| `/api/tools` | GET | 工具列表 |
| `/api/skills` | GET | Skill 列表 |
| `/api/skills/<name>/invoke` | POST | Skill 调用 |
| `/api/conversation/stats` | GET | 会话统计 |
| `/api/conversation/<session_id>` | GET | 会话历史 |
| `/api/sessions` | GET | 会话列表 |
| `/api/sessions/<session_id>` | GET | 会话详情 |
| `/api/memory/stats` | GET | 记忆统计 |
| `/api/memory/clear` | POST | 清空记忆 |
| `/api/logs` | GET | 日志查询 |
| `/api/logs/stream` | GET | 日志 SSE 流 |
| `/api/logs/files` | GET | 日志文件列表 |
| `/api/logs/files/<path:filename>` | GET | 日志文件内容 |
| `/api/logs/clear` | POST | 清空日志 |
| `/api/cache/warmup` | POST | 缓存预热 |
| `/api/cache/status` | GET | 缓存状态 |
| `/api/matchup/status` | GET | 对局数据状态 |
| `/api/matchup/load-all` | POST | 对局数据加载 |
| `/api/matchup/hero/<hero_id>` | GET | 英雄对局数据 |
| `/api/matchup/stop-load` | POST | 停止加载 |
| `/api/trace/<trace_id>` | GET | Trace 查询 |
| `/api/trace/<trace_id>/persist` | POST | Trace 持久化 |
| `/api/trace/<trace_id>/history` | GET | 历史 Trace |
| `/api/traces/recent` | GET | 最近 Trace |
| `/api/traces/statistics` | GET | Trace 统计 |
| `/api/traces/errors` | GET | 错误 Trace |
| `/api/trace/search` | GET | Trace 搜索 |
| `/api/errors` | GET | 错误日志 |

## 七、执行指令参考

确认清单无误后，可使用以下命令执行实际删除：

```bash
# 在 Windows PowerShell 中执行（项目根目录下）
# 请仔细核对后再执行！

# 删除目录
Remove-Item -Recurse -Force "gsi"
Remove-Item -Recurse -Force "core/decision"
Remove-Item -Recurse -Force "knowledge"
Remove-Item -Recurse -Force "feedback"
Remove-Item -Recurse -Force "evaluation"
Remove-Item -Recurse -Force "deploy"
Remove-Item -Recurse -Force "resources/voice"
Remove-Item -Recurse -Force "strategies"
Remove-Item -Recurse -Force "skills/lineup_analyzer"
Remove-Item -Recurse -Force "skills/meta_analyzer"
Remove-Item -Recurse -Force "skills/knowledge_query"
Remove-Item -Recurse -Force "tests/gsi"
Remove-Item -Recurse -Force "tests/feedback"
Remove-Item -Recurse -Force "tests/evaluation"
Remove-Item -Recurse -Force "tests/knowledge"
Remove-Item -Recurse -Force "scripts/evaluation"

# 删除文件
Remove-Item -Force "core/event_trigger.py"
Remove-Item -Force "tools/gsi_tools.py"
Remove-Item -Force "tools/recommendation_tools.py"
Remove-Item -Force "tools/knowledge_tools.py"
Remove-Item -Force "utils/voice_player.py"
Remove-Item -Force "utils/background_loader.py"
Remove-Item -Force "config/gsi_config.yaml"
Remove-Item -Force "config/feedback_config.yaml"
Remove-Item -Force "config/recommendation_config.yaml"
Remove-Item -Force "config/knowledge_config.yaml"
Remove-Item -Force "config/parallel_execution_config.yaml"
Remove-Item -Force "config/prompts/decision.yaml"
Remove-Item -Force "config/prompts/recommendation.yaml"
Remove-Item -Force "frontend/src/components/GsiStatusPanel.vue"
Remove-Item -Force "frontend/src/composables/useGsiStream.ts"
Remove-Item -Force "frontend/src/composables/useRecommendationStream.ts"
Remove-Item -Force "frontend/src/types/gsi.ts"
Remove-Item -Force "tests/utils/test_voice_player.py"
Remove-Item -Force "tests/unit/test_background_loader.py"
Remove-Item -Force "tests/unit/test_event_trigger.py"
Remove-Item -Force "tests/unit/test_recommendation_tools.py"
Remove-Item -Force "tests/integration/test_feedback_integration.py"
Remove-Item -Force "tests/integration/test_voice_integration.py"
Remove-Item -Force "tests/integration/test_parallel_execution_integration.py"
Remove-Item -Force "tests/test_data_engine.py"
Remove-Item -Force "tests/test_decision_fusion.py"
Remove-Item -Force "tests/test_llm_engine.py"
Remove-Item -Force "tests/test_rule_engine.py"
Remove-Item -Force "tests/skills/test_knowledge_query.py"
Remove-Item -Force "tests/skills/test_lineup_analyzer.py"
Remove-Item -Force "tests/skills/test_meta_analyzer.py"
Remove-Item -Force "scripts/import_knowledge.py"
```

---

> 本报告由 `scripts/simulate_cleanup.py` 自动生成，仅用于模拟分析，未执行任何删除操作。