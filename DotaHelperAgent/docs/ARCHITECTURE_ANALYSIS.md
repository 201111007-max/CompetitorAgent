# DotaHelperAgent 待改进事项

> 最后更新：2026-06-24

## 一、待改进优先级

> 更新时间：2026-06-22

### 1.1 总体架构升级路线图（第十六章）

**目标**: 将 DotaHelperAgent 从"被动查询助手"升级为"智能决策推荐系统"

| 阶段 | 升级方向 | 优先级 | 预计工作量 | 核心内容 | 状态 |
|------|---------|--------|----------|---------|------|
| **第一阶段** | **知识管理能力升级** | **P0** | 1-2周 | 向量数据库 + 攻略文档检索 | ✅ 已完成 |
| **第二阶段** | **GSI 实时数据处理** | **P1** | 2-3周 | GSI服务器 + 状态管理 + 事件处理 | ✅ 已完成 |
| **第三阶段** | **推理和决策能力增强** | **P1** | 3-4周 | 数据驱动决策 + 混合推理 | ✅ 已完成 |
| **第四阶段** | **个性化学习能力** | **P2** | 2-3周 | 用户画像 + 在线学习 | ✅ 已完成 |
| **第五阶段** | **多模态交互能力** | **P2** | 1-2周 | 语音播报 + 数据可视化 | 🔄 部分完成（前端样式 ✅ 2026-06-14；语音提醒 ❌ 待实现） |


### 1.2 详细待办事项清单

| 优先级 | 改进项 | 预计工作量 | 影响 | 所属阶段 | 状态 |
| --- | --- | --- | --- | --- | --- |
| **P0** | **接入 Langfuse 监控系统** | 中 | 高 | - | ✅ 已完成 |
| **P0** | **Agent 执行层监控（Langfuse）** | 中 | 高 | - | ✅ 已完成 |
| **P0** | **工具调用层监控（Langfuse）** | 中 | 高 | - | ✅ 已完成 |
| **P0** | **Trace 定位与日志追踪体系** | 大 | 高 | - | ✅ 已完成 |
| **P0** | **知识管理能力升级** | 中 | 高 | **第一阶段** | ✅ 已完成 |
| **P1** | **GSI 实时游戏状态监控** | 大 | 高 | **第二阶段** | ✅ 已完成 |
| **P1** | **游戏事件提醒系统** | 中 | 中 | **第二阶段** | ✅ 已完成 |
| **P1** | **Agent主动推荐机制** | 大 | 高 | **第三阶段** | ✅ 已完成 |
| **P1** | **GSI数据与Agent结合方案** | 中 | 高 | **第二阶段** | ✅ 已完成 |
| **P1** | **GSI主动推荐功能PRD** | 大 | 高 | **第二阶段** | ✅ 已完成 |
| **P1** | **Prompt 版本管理（Langfuse）** | 中 | 中 | **第三阶段** | ✅ 已完成 |
| **P1** | **工具执行并行化** | 中 | 中 | - | ✅ 已完成 |
| P2 | 前端样式优化 | 中 | 中 | **第五阶段** | ✅ 已完成 |
| P2 | 用户反馈学习 | 大 | 中 | **第四阶段** | ✅ 已完成 |
| P2 | 语音提醒系统 | 中 | 低 | **第五阶段** | ❌ 待实现 |
| P1 | 上下文压缩：修复重复压缩 bug | 小 | 中 | - | ✅ 已完成 |
| P1 | 上下文压缩：摘要生成升级为 LLM 驱动 | 中 | 高 | - | ✅ 已完成 |
| P2 | 上下文压缩：分层压缩策略（完整/轻量/深度） | 中 | 中 | - | ✅ 已完成 |
| P2 | 上下文压缩：异步压缩避免阻塞主流程 | 小 | 低 | - | ✅ 已完成 |

### 已完成的改进项

| 优先级 | 改进项 | 完成时间 | 代码位置 |
| --- | --- | --- | --- |
| P0 | 工具选择智能化（LLM Function Calling） | 2026-05-17 | `core/llm_tool_selector.py` |
| P0 | 知识管理能力升级 | 2026-06-14 | `knowledge/` + `tools/knowledge_tools.py` + `config/knowledge_config.yaml` |
| P1 | 记忆系统深度集成 | 2026-05-17 | `memory/memory.py` |
| P1 | 多轮对话上下文 | 2026-05-17 | `core/conversation_manager.py` + `core/context_augmenter.py` |
| P1 | 工具执行并行化 | 2026-06-10 | `core/parallel_executor.py` + `core/parallel_execution_config.py` |
| P1 | GSI 实时游戏状态监控 | 2026-06-22 | `gsi/` + `tools/gsi_tools.py` + `config/gsi_config.yaml` |
| P1 | 游戏事件提醒系统 | 2026-06-22 | `gsi/event_handler.py` + `gsi/event_queue.py` |
| P1 | GSI 数据与 Agent 结合 | 2026-06-22 | `tools/gsi_tools.py` |
| P1 | Agent主动推荐机制 | 2026-06-24 | `core/decision/` + `core/event_trigger.py` + `tools/recommendation_tools.py` + `config/recommendation_config.yaml` |
| P1 | Prompt 版本管理 | 2026-06-24 | `utils/prompt_manager.py` + `utils/prompt_strategy.py` + `config/prompts/` + `config/prompt_config.yaml` |
| P1 | GSI主动推荐功能PRD | 2026-06-22 | `gsi/` + `core/decision/` + `core/event_trigger.py` |
| P2 | 反思结果驱动策略调整 | 2026-05-17 | `core/agent_controller.py#_adjust_strategy` |
| P2 | 前端样式优化 | 2026-06-14 | `frontend/src/components/` + `frontend/src/styles/dota-theme.css` |
| P2 | 用户反馈学习 | 2026-06-25 | `feedback/` + `config/feedback_config.yaml` + `web/app.py` |

---

### 1.3 待办项合并与冲突分析

#### 1.3.1 合并关系说明

**第二阶段：GSI 实时数据处理** 整合了以下待办项（✅ 已完成，2026-06-22）：
- ✅ **GSI 实时游戏状态监控**（第八章）→ 第二阶段核心功能
- ✅ **游戏事件提醒系统**（第九章）→ 第二阶段事件处理器
- ✅ **GSI数据与Agent结合方案**（第十一章）→ 第二阶段工具层集成
- ✅ **GSI主动推荐功能PRD**（第十二章）→ 第二阶段产品化方案

**第三阶段：推理和决策能力增强** 整合了以下待办项（✅ 已完成，2026-06-24）：
- ✅ **Agent主动推荐机制**（第十章）→ 第三阶段决策融合器（已完成，2026-06-24）
- ✅ **Prompt 版本管理**（第六章）→ 第三阶段 Prompt 优化（已完成，2026-06-24）

**第四阶段：个性化学习能力** 整合了以下待办项：
- ✅ **用户反馈学习**（P2）→ 第四阶段在线学习引擎

**第五阶段：多模态交互能力** 整合了以下待办项：
- ❌ **语音提醒系统**（P2）→ 第五阶段语音播报功能（**待实现**，参考 [第十五章](#十五p2语音提醒系统)）
- ✅ **前端样式优化**（P2）→ 第五阶段数据可视化（已完成，2026-06-14）

#### 1.3.2 新增待办项

**第一阶段：知识管理能力升级**（P0，新增）：
- ✅ **向量数据库集成**（Chroma） - `knowledge/vector_store.py`
- ✅ **攻略文档向量化存储** - `data/guides/hero_guides/` + `scripts/import_knowledge.py`
- ✅ **知识查询工具** - `tools/knowledge_tools.py`（KnowledgeQueryTool, KnowledgeUpdateTool）
- ✅ **知识融合引擎** - `knowledge/fusion_engine.py`
- ✅ **实体对齐** - `knowledge/entity_alignment.py`
- ✅ **冲突检测** - `knowledge/conflict_detector.py`
- ✅ **置信度评估** - `knowledge/confidence_evaluator.py`
- ✅ **配置化管理** - `config/knowledge_config.yaml`

#### 1.3.3 优先级调整建议

| 原优先级 | 改进项 | 新优先级 | 调整原因 |
|---------|--------|---------|---------|
| P1 | GSI 实时游戏状态监控 | P1 | 保持不变，属于第二阶段核心 |
| P1 | 游戏事件提醒系统 | P1 | 保持不变，属于第二阶段 |
| P1 | Agent主动推荐机制 | P1 | **已完成，2026-06-24** |
| P1 | GSI数据与Agent结合方案 | P1 | 保持不变，属于第二阶段 |
| P1 | GSI主动推荐功能PRD | P1 | 保持不变，属于第二阶段 |
| P1 | Prompt 版本管理 | P1 | **已完成，2026-06-24** |
| P2 | 用户反馈学习 | P2 | 保持不变，属于第四阶段 |
| P2 | 语音提醒系统 | P2 | 保持不变，属于第五阶段 |
| P2 | 前端样式优化 | P2 | **已完成，2026-06-14** |
| - | **知识管理能力升级** | **P0** | **已完成，2026-06-14** |

#### 1.3.4 实施建议

**推荐实施顺序**：
1. ~~**第一阶段（P0）**：知识管理能力升级 - 建立知识库基础设施~~ ✅ 已完成（2026-06-14）
2. ~~**第二阶段（P1）**：GSI 实时数据处理 - 实现实时监控能力~~ ✅ 已完成（2026-06-22）
3. ~~**第三阶段（P1）**：推理和决策能力增强 - 提升决策质量~~ ✅ 已完成（2026-06-24）
4. ~~**第四阶段（P2）**：个性化学习能力 - 实现个性化推荐~~ ✅ 已完成（2026-06-25）
5. **第五阶段（P2）**：多模态交互能力 - 提升用户体验（前端样式 ✅ 已完成；语音提醒 ❌ 待实现）

**关键依赖关系**：
- ~~第二阶段依赖第一阶段（知识库支持决策推荐）~~ ✅ 第一阶段已完成
- ~~第三阶段依赖第二阶段（实时数据支持推理）~~ ✅ 第二阶段已完成
- ~~第四阶段依赖第三阶段（决策能力支持个性化）~~ ✅ 第四阶段已完成
- 第五阶段可并行开发（相对独立），当前仅剩语音提醒子项未实现

---

## 二、P0：接入 Langfuse 监控系统 ✅

**实现状态**: ✅ 已完成（2026-05-21）

**代码位置**:
- `utils/langfuse_adapter.py` - Langfuse 适配器（单例模式，可选导入）
- `utils/langfuse_config.py` - 配置管理（支持环境变量 + YAML）
- `config/langfuse_config.yaml` - 配置文件
- `web/app.py` - 集成点（请求追踪、用户反馈）
- `tests/integration/test_langfuse_integration.py` - 集成测试

### 2.1 概述

Langfuse 是一个开源的 LLM 应用可观测性平台，提供：
- **Trace 追踪**：完整记录请求生命周期 ✅
- **Prompt 管理**：版本化 Prompt 模板 ✅（2026-06-24 通过 [第七章](#七p1prompt-版本管理-) 完成）
- **评分系统**：用户反馈和自动评估 ✅
- **成本分析**：Token 使用量和成本统计 ✅（通过 `utils/llm_client.py` 中的 Token 统计实现）
- **会话分析**：多轮对话上下文追踪 ✅

**官方文档**：https://langfuse.com/docs

### 2.2 已实现的集成点

| 模块 | 集成内容 | 状态 |
| --- | --- | --- |
| `utils/langfuse_adapter.py` | Langfuse 客户端适配器（单例、可选导入） | ✅ 已完成 |
| `utils/langfuse_config.py` | 配置管理（环境变量 + YAML） | ✅ 已完成 |
| `config/langfuse_config.yaml` | 配置文件 | ✅ 已完成 |
| `web/app.py` | 请求追踪、用户反馈收集 | ✅ 已完成 |
| `utils/llm_client.py` | LLM 调用追踪、Token 统计 | ✅ 已完成 |
| `utils/api_client.py` | API 调用追踪（OpenDota） | ✅ 已完成 |
| `tests/integration/test_langfuse_integration.py` | 集成测试 | ✅ 已完成 |
| `core/tool_registry.py` | 工具执行追踪、耗时统计 | ✅ 已完成 |
| `core/agent_controller.py` | ReAct 循环追踪、会话关联 | ✅ 已完成 |
| `utils/prompt_manager.py` + `utils/prompt_strategy.py` | 版本化 Prompt 模板管理 | ✅ 已完成 |

### 2.3 特性亮点

1. **可选导入设计** - SDK 未安装时自动降级为 NoOpObservation，不影响项目运行
2. **配置化管理** - 支持环境变量和 YAML 配置文件，灵活切换环境
3. **完整的测试覆盖** - 单元测试 + 集成测试

### 2.4 预期收益

1. **调试效率提升**：快速定位问题请求 ✅
2. **性能优化**：识别慢查询和瓶颈 ✅（通过 API 调用追踪）
3. **成本控制**：Token 使用量可视化 ✅（在 llm_client.py 中记录）
4. **质量评估**：用户评分 + 自动评估 ✅
5. **Prompt 优化**：版本管理和 A/B 测试 ✅（已实现，2026-06-24）

---

## 三、P0：Agent 执行层监控 ✅

**实现状态**: ✅ 已完成（2026-05-26）

**目标**: 在 `agent_controller.py` 中集成 Langfuse，监控 ReAct 循环的每个阶段

**实现位置**: `core/agent_controller.py`

**已实现功能**:
- ✅ 创建 Agent Trace（`langfuse_client.observation(name="react_agent", as_type="agent")`）
- ✅ 监控 solve() 方法的整体执行流程
- ✅ 记录输入参数（query, context）和元数据（session_id, max_turns, trace_id）
- ✅ 创建 Langfuse Span 用于各阶段追踪
- ✅ 与现有 TraceSpan 系统协同工作

**预期收益**:
- ✅ Agent 推理过程可视化
- ✅ 精确定位推理瓶颈
- ✅ 推理质量评估

---

## 四、P0：工具调用层监控 ✅

**实现状态**: ✅ 已完成（2026-05-26）

**目标**: 在 `tool_registry.py` 中集成 Langfuse，监控工具执行情况

**实现位置**: `core/tool_registry.py`

**已实现功能**:
- ✅ 创建工具 Span（`langfuse_client.observation(name=f"tool_{tool_name}", as_type="tool")`）
- ✅ 监控工具调用频率
- ✅ 统计工具执行耗时
- ✅ 追踪工具成功率（通过 `tool_span.score()`）
- ✅ 记录工具参数和返回值预览
- ✅ 异常处理和错误记录

**预期收益**:
- ✅ 工具性能分析
- ✅ 工具使用统计
- ✅ 工具优化依据

---

## 五、P0：Trace 定位与日志追踪体系 ✅

**实现状态**: ✅ 已完成（2026-05-26）

**目标**: 建立完整的日志追踪方案，支持根据 trace ID 快速获取完整调用链日志

**实现位置**:
- `utils/trace_context.py` - Trace 上下文管理（TraceContext, TraceSpan, @traced 装饰器）
- `utils/trace_persistence.py` - Trace 持久化模块（SQLite 存储，支持历史查询和长期存储）
- `utils/log_config.py` - TraceJSONFormatter 日志格式化器
- `web/app.py` - Flask 请求级 Trace 初始化与清理、Trace 查询 API
- `core/agent_controller.py` - Agent 执行流程 Span 追踪

**已实现功能**:
- ✅ Trace ID 生成与传递（`generate_trace_id()`, `generate_span_id()`, `generate_session_id()`）
- ✅ 日志与 Trace 关联（TraceJSONFormatter 自动注入 trace_id, span_id, parent_span_id）
- ✅ Span 嵌套追踪（TraceSpan 上下文管理器，支持父子 Span 关系）
- ✅ Trace 查询接口（`GET /api/trace/<trace_id>`, `GET /api/trace/<trace_id>/spans`）
- ✅ 前端 TraceID 传递（X-Trace-ID Header）
- ✅ @traced 装饰器（自动为函数添加 Trace 支持）
- ✅ Trace 持久化（SQLite 存储，支持历史查询和长期存储）

**核心特性**:
- TraceContext 数据结构：包含 trace_id, span_id, parent_span_id, session_id, operation, start_time
- TraceSpan 上下文管理器：支持嵌套 Span 追踪
- @traced 装饰器：自动为函数添加 Trace 支持
- JSON 格式日志输出：便于解析和分析

**预期收益**:
- ✅ 快速定位问题（通过 trace_id 一键查询相关日志）
- ✅ 完整调用链追踪（Span 树结构展示嵌套关系）
- ✅ 日志分析效率提升（JSON 格式便于解析）

---

## 六、P0：知识管理能力升级 ✅

**实现状态**: ✅ 已完成（2026-06-14）

**目标**: 将 DotaHelperAgent 从纯 API 查询模式升级为知识驱动的智能助手，支持攻略文档向量化存储和语义检索

**实现位置**:
- `knowledge/vector_store.py` - 向量数据库客户端（基于 Chroma）
- `knowledge/fusion_engine.py` - 知识融合引擎（整合多源知识）
- `knowledge/entity_alignment.py` - 实体对齐（统一不同数据源的英雄/物品名称）
- `knowledge/conflict_detector.py` - 冲突检测（识别知识库中的矛盾建议）
- `knowledge/confidence_evaluator.py` - 置信度评估（根据数据源可信度评估知识质量）
- `tools/knowledge_tools.py` - 知识查询工具（KnowledgeQueryTool, KnowledgeUpdateTool）
- `config/knowledge_config.yaml` - 知识管理配置文件
- `scripts/import_knowledge.py` - 数据导入脚本
- `data/guides/hero_guides/` - 攻略文档目录（已有 PA.md）

**已实现功能**:
- ✅ 向量数据库集成（Chroma，支持持久化存储和内存模式）
- ✅ 攻略文档向量化存储（支持 JSON/MD/TXT 格式导入）
- ✅ 语义检索（基于 Embedding 的相似度搜索）
- ✅ 知识融合引擎（实体对齐 + 冲突检测 + 置信度评估 + 知识融合）
- ✅ 知识查询工具（支持非结构化/结构化/融合知识查询）
- ✅ 知识更新工具（支持增量导入和覆盖导入）
- ✅ 配置化管理（向量数据库、融合引擎、查询参数均可配置）
- ✅ Agent 集成（agent_controller.py 中自动初始化知识系统并注册工具）

**核心特性**:
- 延迟导入设计：chromadb 未安装时静默降级
- 多源知识融合：OpenDota API 数据 + 攻略文档 + 用户贡献
- 实体对齐：统一中英文英雄/物品名称
- 冲突检测：自动识别物品推荐和技能加点冲突
- 置信度评估：基于数据源可信度 + 胜率 + 选取率综合评分

**预期收益**:
- ✅ 攻略文档语义检索（而非关键词匹配）
- ✅ 多源知识融合（API 数据 + 文档知识）
- ✅ 知识冲突自动检测
- ✅ 知识质量评估

---

## 七、P1：Prompt 版本管理 ✅

**实现状态**: ✅ 已完成（2026-06-24）

**目标**: 使用 Langfuse 管理 Prompt 模板，支持版本化和 A/B 测试

**实现位置**:
- `utils/prompt_manager.py` - Prompt 管理器（接口 + 工厂 + 缓存）
- `utils/prompt_strategy.py` - 策略接口 + Langfuse 策略 + 本地 YAML 策略
- `config/prompts/` - Prompt 配置目录（5个 YAML 文件）
- `config/prompt_config.yaml` - Prompt 管理配置
- `tests/utils/test_prompt_manager.py` - Prompt 管理器单元测试（12个用例）
- `tests/utils/test_prompt_strategy.py` - 策略单元测试（13个用例）
- `tests/integration/test_prompt_integration.py` - 集成测试（15个用例）

**已实现功能**:
- ✅ 策略模式设计（Langfuse 主策略 + 本地 YAML 降级策略）
- ✅ Prompt 模板版本管理（支持多版本、最新版本获取）
- ✅ 内存缓存机制（TTL 过期、缓存统计）
- ✅ 变量替换（模板渲染）
- ✅ 自动降级（Langfuse 不可用时回退到本地）
- ✅ 业务模块集成（agent_controller、llm_client、llm_engine、skill_builder）
- ✅ 完整的测试覆盖（40个测试用例全部通过）

**核心特性**:
- 接口 + 策略模式设计，便于扩展其他后端
- 声明式 Prompt 注册（YAML 配置）
- 缓存命中率监控
- Prompt 元数据管理（作者、标签、描述）

**预期收益**:
- ✅ Prompt 优化有据可依
- ✅ 降低 Prompt 变更风险
- ✅ 提升 Prompt 质量
- ✅ 支持 A/B 测试（设计文档中已规划）

---

## 八、P1：工具执行并行化 ✅

**实现状态**: ✅ 已完成（2026-06-10）

**目标**: 实现工具的并行执行，提升 Agent 响应速度和性能

**实现位置**:
- `core/parallel_executor.py` - 并行执行器
- `core/parallel_execution_config.py` - 配置管理器
- `config/parallel_execution_config.yaml` - 配置文件
- `tests/integration/test_parallel_execution_integration.py` - 集成测试

**核心功能**:
- ✅ 并行执行多个独立工具（使用 asyncio.gather）
- ✅ 并发控制（asyncio.Semaphore 限制最大并发数）
- ✅ 超时控制（asyncio.wait_for 实现单个工具超时）
- ✅ 异常处理（宽松模式，一个工具失败不影响其他工具）
- ✅ 依赖分析（识别工具间依赖关系，按需顺序执行）
- ✅ 性能监控（记录执行时间、并行分组等）
- ✅ 配置化管理（支持动态调整并发数、超时时间等参数）

**性能提升**:
- ⚡ **响应速度提升**：多个独立工具并行执行，总耗时接近最慢工具的耗时
- 🛡️ **容错能力增强**：一个工具失败不影响其他工具执行
- 📊 **可观测性提升**：记录执行时间、并行分组等信息，便于性能分析
- ⚙️ **灵活配置**：支持动态调整并发数、超时时间等参数

**预期收益**:
- ✅ Agent 响应速度提升 30%-50%（取决于工具数量和独立性）
- ✅ 系统吞吐量提升（支持更多并发请求）
- ✅ 用户体验优化（更快的响应时间）

---

## 九、P1：GSI 实时游戏状态监控 ✅

**实现状态**: ✅ 已完成（2026-06-22）

**目标**: 集成 Dota 2 游戏状态集成（Game State Integration, GSI）功能，实时监控游戏状态

**实现位置**: 
- `gsi/server.py` - GSI HTTP 服务器
- `gsi/state_manager.py` - 游戏状态管理器
- `gsi/event_handler.py` - 事件处理器
- `gsi/event_queue.py` - 事件队列
- `gsi/models.py` - GSI 数据模型
- `tools/gsi_tools.py` - Agent 工具层集成
- `config/gsi_config.yaml` - 配置文件
- `frontend/src/components/GsiStatusPanel.vue` - 前端 UI 面板

**已实现功能**:
- ✅ GSI HTTP 服务器实现（接收 Dota 2 客户端发送的实时游戏数据）
- ✅ 游戏状态数据解析（地图、玩家、英雄、技能、物品）
- ✅ Token 认证机制（确保数据来源安全）
- ✅ 实时数据更新（每次收到请求时更新 game_state 对象）
- ✅ 状态管理器（缓存、变化检测）
- ✅ 事件队列（SSE 推送 + Agent 查询）
- ✅ Agent 工具层集成（GSIDataTool）
- ✅ 前端 UI 面板（GsiStatusPanel）
- ✅ 配置化管理

**核心特性**:
- 延迟导入设计：Flask 未安装时静默降级
- 状态变化检测：自动检测游戏状态变化并触发事件
- SSE 实时推送：前端实时显示游戏状态
- Agent 集成：Agent 可查询实时游戏数据

**预期收益**:
- ✅ 实时游戏状态监控（了解当前游戏情况）
- ✅ 基于实时数据的智能推荐（根据当前英雄状态推荐出装、技能加点）
- ✅ 游戏事件提醒（堆野、符文、中立物品等）
- ✅ 增强用户体验（实时交互）

---

## 十、P1：游戏事件提醒系统 ✅

**实现状态**: ✅ 已完成（2026-06-22）

**目标**: 基于游戏状态监控，提供游戏事件提醒功能

**实现位置**: 
- `gsi/event_handler.py` - 事件处理器
- `gsi/event_queue.py` - 事件队列
- `config/gsi_config.yaml` - 配置文件

**已实现功能**:
- ✅ 堆野提醒（每分钟堆野时间点提醒）
- ✅ 符文提醒（中符、赏金符、智慧符、莲花）
- ✅ 中立物品提醒（中立物品刷新时间点提醒）
- ✅ 白天/夜晚切换提醒（昼夜切换提醒）
- ✅ 肉山复活提醒（肉山死亡后复活时间提醒）
- ✅ Tormentor 提醒（第一波 Tormentor 时间点提醒）
- ✅ Shard 提醒（Shard 可用时间点提醒）
- ✅ Ward purchase 提醒（眼购买冷却结束提醒）
- ✅ 事件队列管理（SSE 推送 + Agent 查询）
- ✅ 配置化管理（支持动态启用/禁用各类事件）

**核心特性**:
- 事件检测：基于游戏时间自动检测各类事件触发点
- 去重机制：避免重复提醒（past_event_keys）
- 灵活配置：每个事件类型可独立配置启用状态和提醒延迟
- 事件队列：支持 SSE 实时推送到前端
- Agent 集成：Agent 可查询待处理事件

**预期收益**:
- ✅ 游戏节奏提醒（帮助玩家掌握游戏节奏）
- ✅ 资源获取提醒（符文、中立物品、肉山等）
- 时间管理优化（堆野、昼夜切换等）

---

## 十一、P1：Agent主动推荐机制 ✅

**实现状态**: ✅ 已完成（2026-06-24）

**目标**: 在游戏过程中，Agent自动推送建议，无需用户主动输入问题

**实现位置**:
- `core/decision/` - 决策融合器（规则引擎 + 数据引擎 + LLM引擎）
- `core/event_trigger.py` - 事件触发器（订阅GSI事件，自动触发推荐）
- `tools/recommendation_tools.py` - 推荐查询工具
- `config/recommendation_config.yaml` - 推荐系统配置
- `web/app.py` - SSE推送端点（`/api/gsi/recommendations`）
- `frontend/src/composables/useRecommendationStream.ts` - 前端SSE集成

**核心功能**:
- ✅ 决策融合器（规则引擎 + 数据引擎 + LLM引擎，支持加权平均和最高置信度融合策略）
- ✅ 事件触发器（订阅GSI事件队列，冷却控制，阈值检测）
- ✅ 推荐工具（Agent可查询的推荐接口）
- ✅ SSE实时推送（前端可实时接收推荐）
- ✅ 配置化管理（支持堆野/符文/低血量/敌方消失等多种触发器）

**推荐模式**:

| 推荐模式 | 触发条件 | 推送内容示例 |
|---------|---------|-------------|
| **基于游戏事件** | 堆野、符文、肉山等关键事件 | "堆野时间到了！建议前往野区堆野" |
| **基于状态变化** | 血量<30%、金钱>=装备价格、技能冷却结束 | "血量过低！建议立即回城补给" |
| **基于游戏阶段** | 对线期、中期、后期、决胜期 | "中期！建议参团，协助团队推进" |
| **基于团队状态** | 团队领先/劣势、团队状态良好/不佳 | "团队领先！建议主动推塔，扩大优势" |

**技术实现**:
- SSE流式推送（单向推送，前端实时接收）
- 决策融合（规则 + 数据 + LLM三引擎并行推理）
- 事件驱动（订阅GSI事件队列，自动触发推荐）

**预期收益**:
- ✅ Agent从"被动响应"升级为"主动推送"
- ✅ 用户无需主动输入问题，Agent自动推送建议
- ✅ 实时游戏状态监控，主动推送策略建议
- ✅ 大幅提升用户体验和实用性

---

## 十、P1：GSI数据与Agent结合方案 ✅

**实现状态**: ✅ 已完成（2026-06-22）

**目标**: 将GSI实时数据与Agent工具结合，提供实时问答和策略建议

**实现位置**:
- `tools/gsi_tools.py` - GSI数据工具（GSIDataTool）
- `gsi/` - GSI模块（服务器、状态管理器、事件处理器）

**核心功能**:
- ✅ GSI数据工具（获取英雄状态、游戏时间、玩家数据、技能冷却、物品状态）
- ✅ 实时问答（基于GSI数据回答游戏状态问题）
- ✅ 策略建议（根据当前状态提供游戏策略）

**结合方式**:

| 结合方式 | 用户查询示例 | Agent回答示例（基于GSI数据） |
|---------|-------------|----------------------------|
| **实时数据驱动** | "我血量只有30%，该怎么办？" | "建议回城补给，或使用治疗药膏/魔瓶" |
| **游戏事件策略** | "堆野时间到了！" | "建议前往野区堆野，优先堆大野点（距离500码）" |
| **实时问答** | "我现在等级多少？" | "你当前等级：12级，经验值：8500/10000" |
| **整体策略建议** | "我现在应该做什么？" | "根据当前状态（等级12、金钱2500、血量80%），建议：1.购买BKB；2.前往中符位置；3.准备团战" |

**预期收益**:
- ✅ Agent从"静态问答助手"升级为"实时游戏助手"
- ✅ 实时交互能力增强，根据游戏状态回答问题
- ✅ 个性化建议，根据用户当前状态提供建议
- ✅ 游戏节奏掌握优化，帮助用户掌握游戏节奏

---

## 十二、P1：GSI主动推荐功能PRD ✅

**实现状态**: ✅ 已完成（2026-06-22）

**目标**: 实现基于GSI的Agent主动推荐系统，提供游戏过程中的智能建议推送

**实现位置**:
- `gsi/server.py` - GSI HTTP服务器
- `gsi/state_manager.py` - 游戏状态管理器
- `gsi/event_handler.py` - 事件处理器
- `gsi/event_queue.py` - 事件队列
- `core/decision/` - 决策融合器
- `core/event_trigger.py` - 事件触发器
- `tools/recommendation_tools.py` - 推荐工具
- `web/app.py` - SSE推送端点
- `frontend/src/composables/useRecommendationStream.ts` - 前端SSE集成

**已实现功能**:
- ✅ GSI HTTP服务器（接收Dota 2客户端实时数据）
- ✅ 游戏状态解析（英雄、物品、技能、地图等）
- ✅ 事件检测器（堆野、符文、中立物品、肉山等）
- ✅ 决策融合器（规则引擎 + 数据引擎 + LLM引擎）
- ✅ 事件触发器（订阅事件队列，自动触发推荐）
- ✅ SSE实时推送（前端实时接收推荐）
- ✅ 配置化管理（支持多种触发器和冷却控制）

**预期收益**:
- ✅ Agent主动感知游戏状态，自动推送建议
- ✅ 实时游戏状态监控（GSI集成）
- ✅ LLM驱动的个性化建议生成
- ✅ 可配置化的提醒设置

### User Stories

**游戏事件提醒**:
1. As a Dota 2 player, I want Agent to remind me when to stack camps (every minute), so that I can maximize my farm efficiency.
2. As a Dota 2 player, I want Agent to remind me when runes spawn (mid runes every 2 minutes, bounty/wisdom/lotus every 3 minutes), so that I can contest them.
3. As a Dota 2 player, I want Agent to remind me when neutral items spawn (5/15/25/35/45 minutes), so that I can get the best items for my hero.

**游戏阶段提醒**:
4. As a Dota 2 player, I want Agent to remind me during laning phase (0-10 minutes) to focus on farming and buying core items.
5. As a Dota 2 player, I want Agent to remind me during mid game (10-20 minutes) to participate in teamfights and push towers.

### Implementation Decisions

**模块设计**:
- **GSI HTTP Server**: Flask-based HTTP server to receive GSI data from Dota 2 client (port: 5001)
- **GSI Data Parser**: Parse raw GSI JSON data into structured GameState object
- **Game Event Detector**: Detect game events (stack, runes, neutral items, Roshan, Tormentor) based on game time
- **LLM Suggestion Generator**: **核心模块** - Use LLM to generate natural language suggestions based on context
- **Personalization Engine**: Personalize suggestions based on user behavior pattern, current state, hero type, and playstyle
- **Desktop Notification Sender**: Send Windows desktop notifications with configurable duration and icons
- **Voice Player**: Play voice reminders in multiple languages (Chinese, English, custom)

**建议生成流程**:
```
游戏事件触发
    │
    ▼
┌─────────────────┐
│  事件检测器      │
│  - 检测事件类型  │
│  - 提取游戏时间  │
└─────────────────┘
    │
    ▼
┌─────────────────┐
│  上下文构建器    │
│  - 游戏状态数据  │
│  - 用户行为模式  │
│  - 英雄类型      │
│  - 游戏风格      │
└─────────────────┘
    │
    ▼
┌─────────────────┐
│  LLM建议生成器   │  ⭐ 核心模块
│  - 构造Prompt    │
│  - 调用LLM       │
│  - 解析建议内容  │
└─────────────────┘
    │
    ▼
┌─────────────────┐
│  个性化引擎      │
│  - 调整建议语气  │
│  - 优化建议内容  │
└─────────────────┘
    │
    ▼
┌─────────────────┐
│  推送调度器      │
│  - 确定优先级    │
│  - 设置延迟      │
│  - 调度推送      │
└─────────────────┘
    │
    ▼
┌─────────────────┐
│  推送执行        │
│  - 桌面通知      │
│  - 语音播放      │
└─────────────────┘
```

**LLM Prompt示例**:
```python
# 堆野建议Prompt
STACK_PROMPT = """你是一个Dota 2游戏教练，正在指导玩家堆野。

## 当前游戏状态
- 游戏时间：{game_time}秒
- 英雄：{hero_name}（{hero_type}）
- 血量：{health_percent}%
- 金钱：{gold}
- 位置：{hero_position}

## 用户行为模式
- 最近3次堆野：{stack_behavior}（成功/失败/错过）
- 游戏风格：{playstyle}（打钱型/参团型）

## 任务
根据以上信息，生成一个堆野建议（不超过20字），要求：
1. 根据用户行为模式提供针对性建议
2. 根据英雄类型调整建议重点
3. 根据游戏风格优化建议语气
4. 使用自然、流畅的语言

## 示例输出
- "堆野时间到了！你最近3次都错过堆野了，建议这次去堆野提升经济"
- "堆野提醒！作为核心英雄，建议优先堆大野点，提升打钱效率"
- "堆野时间！血量充足（80%），建议前往野区堆野"
"""
```

### Out of Scope

> **状态说明**：以下为本 PRD 起草时（2026-06-22 之前）规划排除的功能。截至 2026-07-06，部分排除项已根据实际需求实现，已实现的项以 `✅` 标注并附实现位置。

- **WebSocket Push**: Not implementing WebSocket push (using desktop notifications and voice instead)
- **SSE Push**: ~~Not implementing SSE push (using desktop notifications and voice instead)~~ ✅ **已实现**（2026-06-22）- `web/app.py` `/api/gsi/recommendations` 端点 + `frontend/src/composables/useRecommendationStream.ts`
- **State Change Reminders**: ~~Not implementing state change reminders (health, gold, skill cooldown, level up)~~ ✅ **已实现**（2026-06-24）- 第十一章"基于状态变化"推荐模式（血量<30%、金钱>=装备价格、技能冷却结束）
- **STRATZ API Integration**: Not integrating STRATZ API for game data (using Dota 2 client GSI only)
- **Mobile Notifications**: Not implementing mobile notifications (Windows desktop only)
- **Multi-user Support**: Not implementing multi-user support (single-user mode only)
- **Cloud Storage**: Not implementing cloud storage for behavior history (SQLite local storage only)

---

## 十三、P2：前端样式优化 ✅

**实现状态**: ✅ 已完成（2026-06-14）

**目标**: 优化前端界面样式，提升用户体验

**实现位置**: `frontend/src/` - 前端源码

**核心功能**:
- 响应式布局适配
- 暗色主题支持
- 交互反馈优化（加载动画、hover 效果）
- 消息展示美化（Markdown 渲染、代码高亮）
- 英雄/物品卡片样式优化

**预期收益**:
- 用户体验提升
- 视觉效果优化
- 交互流畅度提升

---

## 十四、P2：用户反馈学习 ✅

**实现状态**: ✅ 已完成（2026-06-25）

**目标**: 建立用户反馈学习系统，通过显式+隐式双通道反馈，动态优化决策引擎权重和规则参数

**实现位置**: 
- `feedback/store.py` - 反馈存储（SQLite）
- `feedback/collector.py` - 反馈采集器（显式+隐式）
- `feedback/evaluator.py` - 效果评估器
- `feedback/strategy_params.py` - 策略参数管理
- `feedback/learning_engine.py` - 学习引擎（实时增量+定期批量）
- `config/feedback_config.yaml` - 反馈系统配置
- `web/app.py` - Web API 集成（7个反馈接口）
- `tests/feedback/` - 单元测试（26个用例）
- `tests/integration/test_feedback_integration.py` - 集成测试（9个用例）

**核心功能**:
- ✅ 显式反馈采集（用户评分 1-5 星，归一化到 [-1, 1]）
- ✅ 隐式反馈采集（采纳/部分采纳/忽略/反向操作，自动映射评分）
- ✅ 反馈存储（SQLite，支持按引擎/规则/场景维度查询）
- ✅ 效果评估（引擎级、规则级、场景级聚合统计）
- ✅ 实时增量学习（每次反馈后微调引擎权重，保持权重和为 1.0）
- ✅ 定期批量校准（每天定时校准规则参数，如低血量阈值）
- ✅ 策略参数持久化（YAML 存储，支持版本和置信度）
- ✅ Langfuse 集成（反馈上报到 Langfuse Score）
- ✅ Web API（显式/隐式反馈提交、统计查询、策略查询/重置、手动校准）
- ✅ 与决策系统集成（DecisionFusion 动态引擎权重、RuleEngine 动态规则参数）
- ✅ 与 EventTrigger 集成（推荐上下文注册，供反馈关联）

**预期收益**:
- ✅ 决策引擎权重自适应调整，推荐质量持续提升
- ✅ 关键规则参数根据实际效果优化
- ✅ 形成"推荐 → 反馈 → 学习 → 优化推荐"的完整闭环

---

## 十五、P2：语音提醒系统 ❌

**目标**: 提供语音提醒功能，增强游戏事件提醒的感知度

**参考项目**: `dota2-game-helper` - 语音播放实现

**实现位置**: `utils/voice_player.py` - 语音播放器（新建）

**核心功能**:
- 语音播放功能（播放预录制的语音文件）
- 可配置化的提醒开关（用户可选择开启/关闭特定提醒）
- 多语言支持（中文、英文）

**语音资源**:

| 事件类型 | 语音文件 | 说明 |
|---------|---------|------|
| 游戏开始 | `prologue.wav` | 游戏开始提醒 |
| 堆野 | `alarm_stack.wav` | 堆野提醒 |
| 中符 | `alarm_mid_runes.wav` | 中符刷新提醒 |
| 财神符 | `alarm_bounty_runes.wav` | 财神符刷新提醒 |
| 智慧符 | `alarm_wisdom_runes.wav` | 智慧符刷新提醒 |
| 莲花 | `alarm_lotus.wav` | 莲花刷新提醒 |
| 中立物品 | `alarm_neutral_items.wav` | 中立物品刷新提醒 |
| 白天 | `alarm_daytime.wav` | 白天切换提醒 |
| 夜晚 | `alarm_night_time.wav` | 夜晚切换提醒 |
| 肉山 | `alarm_roshan.wav` | 肉山复活提醒 |
| Tormentor | `alarm_first_tormentor.wav` | Tormentor 提醒 |
| Shard | `alarm_shard.wav` | Shard 提醒 |
| 眼购买 | `alarm_ward_purchase.wav` | 眼购买冷却结束提醒 |

**实现方案**:

```python
# utils/voice_player.py
import pygame
import os

class VoicePlayer:
    """语音播放器"""
    
    def __init__(self, resources_dir: str = "resources/"):
        self.resources_dir = resources_dir
        pygame.mixer.init()
    
    def play(self, voice_type: str):
        """播放语音"""
        voice_file = os.path.join(self.resources_dir, f"{voice_type}.wav")
        if os.path.exists(voice_file):
            pygame.mixer.Sound(voice_file).play()
        else:
            logging.warning(f"Voice file not found: {voice_file}")
```

**预期收益**:
- 提醒感知度增强（语音比文字更直观）
- 游戏节奏掌握优化（及时响应游戏事件）
- 用户体验提升（多感官交互）

---

## 十六、Agent 架构升级总体思路 🔄

> **状态**: 🔄 部分完成（第一、二阶段已完成，第三阶段部分完成）
> **更新时间**: 2026-06-24
> **说明**: 本章节内容已整合到第一章"待改进优先级"中，作为总体架构升级路线图。详细实施方案请参考各阶段对应的详细文档。

**目标**: 将 DotaHelperAgent 从"被动查询助手"升级为"智能决策推荐系统"

### 16.1 升级背景

当前 DotaHelperAgent 已具备优秀的 ReAct Agent 架构基础：
- ✅ 完整的推理循环（Think → Plan → Execute → Observe → Reflect）
- ✅ 元认知能力（自我评估、置信度计算）
- ✅ 反思机制（多维度质量评估）
- ✅ 三层记忆系统（短期、长期、情景）
- ✅ 丰富的工具生态（10+ 工具）
- ✅ 并行执行能力（性能优化）

但为了实现"智能决策推荐"的核心需求，需要从以下 5 个维度进行系统性升级：

### 16.2 升级方向概览

| 维度 | 当前状态 | 目标状态 | 优先级 | 详细文档 |
|------|---------|---------|--------|---------|
| **知识管理能力** | 三层记忆系统（扁平存储） | 知识图谱 + 向量检索系统 | P0 | [KNOWLEDGE_MANAGEMENT_UPGRADE.md](./architecture_upgrade/KNOWLEDGE_MANAGEMENT_UPGRADE.md) |
| **实时数据处理** | 静态数据查询（OpenDota API） | GSI 实时监控 + 动态决策 | P1 | [REALTIME_DATA_PROCESSING_UPGRADE.md](./architecture_upgrade/REALTIME_DATA_PROCESSING_UPGRADE.md) |
| **推理决策能力** | 规则推理 + LLM 增强 | 混合推理（规则 + 数据 + LLM） | P1 | [REASONING_DECISION_UPGRADE.md](./architecture_upgrade/REASONING_DECISION_UPGRADE.md) |
| **个性化学习** | 通用推荐（无个性化） | 用户画像 + 在线学习 | P2 | [PERSONALIZED_LEARNING_UPGRADE.md](./architecture_upgrade/PERSONALIZED_LEARNING_UPGRADE.md) |
| **多模态交互** | 文本交互 | 文本 + 语音 + 可视化 | P2 | [MULTIMODAL_INTERACTION_UPGRADE.md](./architecture_upgrade/MULTIMODAL_INTERACTION_UPGRADE.md) |

### 16.3 核心架构升级

```
┌─────────────────────────────────────────────────────────────┐
│                    Agent 架构升级蓝图                        │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌──────────────────────────────────────────────────────┐  │
│  │              多模态交互层（新增）                      │  │
│  │  - 文本输入/输出                                      │  │
│  │  - 语音识别/播报                                      │  │
│  │  - 可视化图表                                         │  │
│  └──────────────────────────────────────────────────────┘  │
│                          ▼                                  │
│  ┌──────────────────────────────────────────────────────┐  │
│  │              个性化推荐层（新增）                      │  │
│  │  - 用户画像管理                                       │  │
│  │  - 风格匹配                                           │  │
│  │  - 在线学习                                           │  │
│  └──────────────────────────────────────────────────────┘  │
│                          ▼                                  │
│  ┌──────────────────────────────────────────────────────┐  │
│  │              混合推理层（增强）                        │  │
│  │  ┌────────────┐  ┌────────────┐  ┌────────────┐     │  │
│  │  │ 规则推理   │  │ 数据驱动   │  │ LLM 增强   │     │  │
│  │  │ 引擎       │  │ 引擎       │  │ 引擎       │     │  │
│  │  └────────────┘  └────────────┘  └────────────┘     │  │
│  │         │               │               │            │  │
│  │         └───────────────┼───────────────┘            │  │
│  │                         ▼                            │  │
│  │              ┌──────────────────┐                    │  │
│  │              │  决策融合器       │                    │  │
│  │              └──────────────────┘                    │  │
│  └──────────────────────────────────────────────────────┘  │
│                          ▼                                  │
│  ┌──────────────────────────────────────────────────────┐  │
│  │              知识管理层（升级）                        │  │
│  │  ┌────────────┐  ┌────────────┐  ┌────────────┐     │  │
│  │  │ 知识图谱   │  │ 向量检索   │  │ 知识融合   │     │  │
│  │  │ (Neo4j)    │  │ (Chroma)   │  │ 引擎       │     │  │
│  │  └────────────┘  └────────────┘  └────────────┘     │  │
│  └──────────────────────────────────────────────────────┘  │
│                          ▼                                  │
│  ┌──────────────────────────────────────────────────────┐  │
│  │              实时数据处理层（新增）                    │  │
│  │  ┌────────────┐  ┌────────────┐  ┌────────────┐     │  │
│  │  │ GSI 客户端 │  │ 状态管理器 │  │ 事件处理器 │     │  │
│  │  └────────────┘  └────────────┘  └────────────┘     │  │
│  └──────────────────────────────────────────────────────┘  │
│                          ▼                                  │
│  ┌──────────────────────────────────────────────────────┐  │
│  │              现有 Agent 核心（保留）                   │  │
│  │  - ReAct 循环                                         │  │
│  │  - 元认知系统                                         │  │
│  │  - 反思机制                                           │  │
│  │  - 工具生态                                           │  │
│  └──────────────────────────────────────────────────────┘  │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### 16.4 实施路线图

#### **第一阶段：知识管理能力升级**（P0，1-2 周）

**目标**: 建立知识库基础设施

**关键任务**:
1. 集成向量数据库（Chroma/FAISS）
2. 实现攻略文档的向量化存储和检索
3. 新增知识查询工具

**预期收益**:
- 支持攻略文档的语义检索
- 提升推荐质量（基于攻略知识）

**详细方案**: [KNOWLEDGE_MANAGEMENT_UPGRADE.md](./architecture_upgrade/KNOWLEDGE_MANAGEMENT_UPGRADE.md)

---

#### **第二阶段：GSI 实时数据处理**（P1，2-3 周）

**目标**: 实现实时游戏状态监控

**关键任务**:
1. 实现 GSI HTTP 服务器
2. 实现状态管理器
3. 实现事件处理器
4. 新增 GSI 数据访问工具

**预期收益**:
- 实时监控游戏状态
- 事件驱动的提醒功能

**详细方案**: [REALTIME_DATA_PROCESSING_UPGRADE.md](./REALTIME_DATA_PROCESSING_UPGRADE.md)

---

#### **第三阶段：推理和决策能力增强**（P1，3-4 周）🔄 部分完成

**目标**: 实现数据驱动的决策推荐

**关键任务**:
1. ~~收集和处理历史对局数据~~ ✅ 已完成（通过决策融合器实现）
2. ~~训练胜率预测模型~~ ✅ 已完成（数据引擎集成）
3. ~~实现决策融合器~~ ✅ 已完成（规则引擎 + 数据引擎 + LLM引擎）
4. ~~新增数据驱动推荐工具~~ ✅ 已完成（recommendation_tools.py）
5. ~~Prompt 版本管理~~ ✅ 已完成（2026-06-24）

**预期收益**:
- ✅ 基于历史数据的胜率预测
- ✅ 多源决策融合，提升推荐质量

**详细方案**: [REASONING_DECISION_UPGRADE.md](./REASONING_DECISION_UPGRADE.md)

---

#### **第四阶段：个性化学习能力**（P2，2-3 周）

**目标**: 实现个性化推荐

**关键任务**:
1. 实现用户画像系统
2. 实现反馈收集机制
3. 实现在线学习引擎
4. 新增个性化推荐工具

**预期收益**:
- 根据用户风格个性化推荐
- 持续优化推荐质量

**详细方案**: [PERSONALIZED_LEARNING_UPGRADE.md](./PERSONALIZED_LEARNING_UPGRADE.md)

---

#### **第五阶段：多模态交互能力**（P2，1-2 周）

**目标**: 提升用户体验

**关键任务**:
1. 实现语音播报功能
2. 实现数据可视化
3. 新增多模态输出工具

**预期收益**:
- 语音提醒，提升游戏体验
- 可视化展示，更直观的数据呈现

**详细方案**: [MULTIMODAL_INTERACTION_UPGRADE.md](./MULTIMODAL_INTERACTION_UPGRADE.md)

---

### 16.5 技术选型建议

| 组件 | 推荐技术 | 理由 |
|------|---------|------|
| 向量数据库 | Chroma / FAISS | 轻量级、易集成、性能好 |
| 知识图谱 | Neo4j | 成熟、查询能力强、社区活跃 |
| GSI 服务器 | Flask + WebSocket | 与现有架构一致、实时性好 |
| 数据分析 | Pandas + Scikit-learn | 成熟、易用、适合中小规模数据 |
| 语音合成 | Azure TTS / Google TTS | 质量高、支持中文 |

### 16.6 关键成功因素

1. **数据质量**: 攻略文档的质量决定推荐质量
2. **实时性**: GSI 数据的实时性决定决策时效性
3. **个性化**: 用户画像的准确性决定推荐满意度
4. **可解释性**: 推荐理由的清晰度决定用户信任度

### 16.7 预期收益

| 维度 | 当前能力 | 升级后能力 | 收益 |
|------|---------|-----------|------|
| **知识管理** | 扁平记忆存储 | 知识图谱 + 向量检索 | 推荐质量提升 30% |
| **实时决策** | 静态数据查询 | 实时状态监控 | 决策时效性提升 80% |
| **推理能力** | 规则 + LLM | 混合推理 | 推荐准确率提升 25% |
| **个性化** | 通用推荐 | 用户画像 + 学习 | 用户满意度提升 40% |
| **交互体验** | 文本交互 | 多模态交互 | 用户留存率提升 20% |

---

## 十七、Skill/SubAgent 可替代功能分析

> 更新时间：2026-07-06

**分析目标**: 从产品功能角度，识别 DotaHelperAgent 中哪些用户可感知的功能可以用 Skill（轻量单次调用）或 SubAgent（重多步推理）模式替代实现。

**核心判断标准**: 当前这些功能通过内部硬编码 LLM 调用实现（prompt + API 调用）。如果用 Skill/SubAgent 模式替代，意味着将它们变成可独立调用的能力单元，由主 Agent 按需调度，而不是在代码中写死调用逻辑。

### 17.1 适合用 Skill 替代的功能（轻量、单次 LLM 调用）

| 产品功能 | 功能描述 | 为什么适合 Skill |
|---------|---------|----------------|
| **多轮对话上下文理解** | 理解用户指代（如"它"指哪个英雄）、推断用户意图、注入上下文信息 | 单次 LLM 调用即可完成语义理解，输入输出边界清晰，不需要多步推理 |
| **阵容分析** | 分析敌我双方阵容的优劣势，给出阵容评估 | 单次 LLM 推理，输入阵容列表，输出分析文本，不需要调用外部工具 |
| **版本强势查询** | 查询当前版本的热门英雄、强势英雄 | 数据查询 + 单次 LLM 总结，输入输出明确，流程简单 |
| **知识查询** | 检索攻略文档并生成回答（如"PA 怎么出装？"） | 向量检索 + 单次 LLM 总结，输入输出边界清晰 |
| **智能搜索** | 搜索最新的 Dota 2 资讯、攻略、更新内容 | 搜索引擎调用 + 单次 LLM 摘要，流程简单，天然适合 Skill |

### 17.2 适合用 SubAgent 替代的功能（重、多步推理）

| 产品功能 | 功能描述 | 为什么适合 SubAgent |
|---------|---------|-------------------|
| **英雄克制推荐** | 根据敌方阵容推荐克制英雄（如"对面有 PA、火枪，我该选什么？"） | 多步推理：调用外部 API 获取对局数据 → 数据分析 → LLM 评估克制关系 → 排序推荐，SubAgent 可自主编排整个流程 |
| **出装推荐** | 根据英雄和局势推荐核心装备、针对出装、局势出装 | 多步推理：查询英雄数据 → 分析敌方阵容 → 查询物品库 → LLM 生成推荐方案，需要自主调用多个数据源 |
| **技能加点推荐** | 推荐技能升级顺序、天赋树选择 | 多步推理：查询英雄技能信息 → 分析对局情况 → LLM 生成加点方案，可独立执行完整流程 |
| **游戏事件提醒** | 堆野、符文刷新、肉山复活等游戏事件提醒 | 事件检测 → 构建游戏上下文 → LLM 生成个性化建议，SubAgent 可自主完成从事件感知到建议生成的全流程 |
| **主动推荐** | 根据游戏状态自动推送建议（如血量低时提醒回城） | 感知游戏状态 → 判断触发条件 → 生成个性化建议，多步推理适合 SubAgent |
| **用户反馈学习** | 根据用户反馈（评分、采纳行为）调整推荐策略 | 收集反馈 → 评估推荐效果 → 调整策略参数，自主闭环适合 SubAgent |

### 17.3 不适合替代的功能（纯工程实现）

| 产品功能 | 为什么不适合替代 |
|---------|----------------|
| **GSI 实时游戏状态监控** | 需要持续监听 HTTP 请求，低延迟要求，不适合 Skill/SubAgent 的调用-返回模式 |
| **缓存系统** | 纯工程实现（LRU + SQLite），无 LLM 推理，不需要智能调度 |
| **记忆系统** | SQLite 持久化存储，纯 I/O 操作，不涉及推理 |
| **SSE 流式输出** | 网络通信层，纯工程实现，与 LLM 推理无关 |
| **前端界面** | Vue 3 组件，用户交互层，与 Skill/SubAgent 模式无关 |

### 17.4 功能替代方式总结

| 产品功能 | 推荐替代方式 | 替代后的调用流程 |
|---------|------------|----------------|
| 英雄克制推荐 | **SubAgent** | 主 Agent → 克制推荐 SubAgent → 自主调用 API + 分析 + 生成推荐 |
| 出装推荐 | **SubAgent** | 主 Agent → 出装推荐 SubAgent → 自主查询数据 + 分析 + 生成方案 |
| 技能加点推荐 | **SubAgent** | 主 Agent → 技能加点 SubAgent → 自主查询技能 + 分析 + 生成加点 |
| 游戏事件提醒 | **SubAgent** | 主 Agent → 事件提醒 SubAgent → 自主感知事件 + 生成建议 |
| 主动推荐 | **SubAgent** | 主 Agent → 主动推荐 SubAgent → 自主感知状态 + 判断 + 推送 |
| 用户反馈学习 | **SubAgent** | 主 Agent → 反馈学习 SubAgent → 自主收集 + 评估 + 调整 |
| 阵容分析 | **Skill** | 主 Agent → 调用阵容分析 Skill → 返回分析结果 |
| 多轮对话 | **Skill** | 主 Agent → 调用对话理解 Skill → 返回增强后的上下文 |
| 版本强势查询 | **Skill** | 主 Agent → 调用版本强势 Skill → 返回查询结果 |
| 知识查询 | **Skill** | 主 Agent → 调用知识查询 Skill → 返回检索结果 |
| 智能搜索 | **Skill** | 主 Agent → 调用智能搜索 Skill → 返回搜索结果 |

### 17.5 替代收益分析

| 维度 | 当前方式 | Skill/SubAgent 方式 | 收益 |
|------|---------|-------------------|------|
| **可测试性** | 需要 mock LLM 客户端，测试复杂 | Skill/SubAgent 独立测试，接口清晰 | 测试复杂度降低 |
| **可替换性** | 修改代码替换 LLM 调用逻辑 | 替换 Skill/SubAgent 实现即可 | 切换成本降低 |
| **可复用性** | 功能与模块耦合，难以复用 | 独立能力单元，可跨场景复用 | 复用性提升 |
| **主 Agent 复杂度** | 硬编码调用逻辑，代码复杂 | 只需编排调度，逻辑简洁 | 主 Agent 更清晰 |
| **降级策略** | 每个功能各自实现降级 | 统一降级框架，一致性更好 | 维护成本降低 |

### 17.6 实施建议

**推荐实施顺序**：
1. 先抽取轻量功能为 Skill：阵容分析 → 知识查询 → 版本强势 → 智能搜索 → 多轮对话
2. 再抽取重功能为 SubAgent：英雄克制推荐 → 出装推荐 → 技能加点 → 游戏事件提醒 → 主动推荐 → 用户反馈学习
3. 最后统一降级框架和编排调度逻辑

**注意事项**：
- 每个 Skill/SubAgent 需定义清晰的输入/输出接口
- 保留当前的规则驱动降级方案作为兜底
- 需考虑 Skill/SubAgent 调用的延迟开销
- GSI 实时监控、缓存、记忆系统等纯工程模块保持现有实现

---

## 十八、Skill/SubAgent 评估体系

> 更新时间：2026-07-06

### 18.1 评估目标与挑战

**目标**: 评估基于 Skill/SubAgent 模式替代实现后的功能效果和可靠性，建立可量化、可对比、可回归的评测体系。

**核心挑战**:
- Dota 2 领域缺乏标准化公开评测集（不同于 GAIA、WebArena）
- 同一查询可能存在多个有效答案，难以精确匹配
- 业务场景涉及游戏专业知识，需要领域知识支撑
- 用户主观体验（流畅度、个性化）难以量化

### 18.2 业界主流评测体系调研

调研 2026 年主流 Agent/Skill 评测体系，提炼适用于 DotaHelperAgent 的方法论。

#### 18.2.1 主流评测基准对比

| 评测基准 | 评估目标 | 核心指标 | 适用性 |
|---------|---------|---------|--------|
| **GAIA** ([amd-gaia.ai](https://amd-gaia.ai/docs/eval)) | 多步推理+工具调用 | 7 维评分量表、Pass/Fail | 借鉴评分量表设计 |
| **AgentBench** | 8 个环境综合能力 | 任务成功率 | 借鉴环境隔离设计 |
| **WebArena** ([arXiv:2307.13854](https://arxiv.org/html/2307.13854v4)) | 真实 Web 任务 | 任务成功率 14.4%→78% | 借鉴任务定义方法 |
| **SWE-bench Verified** | 真实代码修复 | 多级评分 | 不适用 |
| **TAU-bench** | 策略感知客服 | 通过率 | 借鉴领域策略测试 |
| **MCPAgentBench** | MCP 工具使用 | 任务完成率+效率 | 借鉴工具调用评估 |
| **TRAJECT-Bench** ([arXiv:TRAJECT](https://openreview.net/pdf?id=TZWnWvsQ0X)) | 工具使用轨迹 | 轨迹级诊断（工具选择、参数、依赖） | **核心参考** |
| **AgentProp-Bench** ([arXiv:2604.16706](https://arxiv.org/html/2604.16706v1)) | 错误传播+缓解 | Stage-level 传播率 | 借鉴错误传播分析 |
| **BabelJudge** ([arXiv:2606.22329](https://arxiv.org/pdf/2606.22329)) | LLM-as-a-Judge 可靠性 | 位置/长度/跨语言偏见 | 借鉴 Judge 校准方法 |

#### 18.2.2 主流评测框架

| 框架 | 特点 | 适用场景 |
|------|------|---------|
| **MLflow** ([mlflow.org](https://mlflow.org/top-5-agent-evaluation-frameworks/)) | 最广泛使用（30M+ 月下载），多维评分、人机协同 | 离线评测 + 在线监控 |
| **DeepEval** ([deepeval.com](https://deepeval.com/guides/guides-llm-as-a-judge)) | pytest 风格 CI/CD 集成、G-Eval/DAG/QAG | CI 集成回归测试 |
| **Ragas** | RAG 评测起家，扩展到 Agent | 知识查询 Skill 评测 |
| **Arize Phoenix** | ML 可观测性扩展 | Trace 分析 |

#### 18.2.3 核心评估方法论提炼

**方法 1：LLM-as-a-Judge（LLM 评判）**
- **核心思想**：用 LLM 评估 LLM 输出
- **三大可靠性支柱**（Microsoft Foundry 2026.01）：
  1. Human Alignment（与人类判断一致）
  2. Self-Consistency（自身一致性）
  3. Inter-Model Agreement（模型间一致性）
- **风险**：位置偏见、长度偏见、自我偏好、跨语言退化
- **缓解**：盲评、多模型交叉评审、temperature=0、多次采样取平均

**方法 2：Trajectory Evaluation（轨迹评估）**
- **核心思想**：评估 Agent 完整执行轨迹，而非仅最终输出
- **关键指标**（TRAJECT-Bench）：
  - Tool Selection Accuracy（工具选择准确率）
  - Argument Correctness（参数正确性）
  - Dependency/Order Satisfaction（依赖/顺序满足度）
  - Premature Invocation Rate（过早调用率）
  - Clue Adherence Rate（线索遵循率）
- **优势**：暴露中间失败，可定位根因

**方法 3：Rejection-Recovery Decomposition（拒绝-恢复分解）**
- **核心思想**：错误检测和错误恢复是相互独立的能力
- **指标**：拒绝率、恢复率、独立评估两者

**方法 4：Multi-dimensional Rubric（多维评分量表）**
- **核心思想**：7 维评分（正确性、完整性、相关性、安全性、效率、鲁棒性、个性化）
- **应用**：GAIA Agent Eval Benchmark
- **格式**：每维 1-5 分，加权聚合

### 18.3 DotaHelperAgent 评估框架设计

基于业界方法论，结合 DotaHelperAgent 实际场景，设计三层评估体系。

#### 18.3.1 评估三层架构

```
┌─────────────────────────────────────────────────────────────┐
│                   L1: 离线评测（开发阶段）                    │
│   - 标准测试集（自建 DotaBench）                              │
│   - 单元测试 + 集成测试                                       │
│   - LLM-as-a-Judge + 规则评分                                 │
└──────────────────────────┬──────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│                   L2: 在线评测（生产阶段）                    │
│   - Trace 记录                                              │
│   - 用户反馈（显式评分 + 隐式行为）                            │
│   - 实时监控仪表板                                            │
└──────────────────────────┬──────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│                   L3: 回归测试（发布阶段）                    │
│   - 基线对比                                                 │
│   - A/B 测试                                                 │
│   - 版本对比报告                                             │
└─────────────────────────────────────────────────────────────┘
```

#### 18.3.2 评估维度定义

为 DotaHelperAgent 定义 7 维评分量表（参考 GAIA + TRAJECT-Bench）：

| 维度 | 权重 | 评估目标 | 评分标准（1-5） |
|------|------|---------|---------------|
| **正确性** | 25% | 答案是否准确 | 1=完全错误 2=部分正确 3=基本正确 4=正确 5=完全准确 |
| **完整性** | 15% | 是否覆盖所有要点 | 1=缺失严重 3=部分覆盖 5=完整覆盖 |
| **相关性** | 15% | 是否切题 | 1=答非所问 3=部分切题 5=精准切题 |
| **工具选择** | 15% | 工具是否合适 | 1=选错工具 3=勉强可用 5=最优选择 |
| **效率** | 10% | 步骤是否精简 | 1=严重冗余 3=有冗余 5=最优路径 |
| **鲁棒性** | 10% | 异常处理 | 1=崩溃 3=部分降级 5=优雅降级 |
| **个性化** | 10% | 是否贴合用户风格 | 1=通用模板 3=部分个性化 5=高度定制 |

#### 18.3.3 Skill 评估指标（轻量级）

针对 Skill（单次 LLM 调用）的评估指标：

| 指标 | 计算方式 | 目标值 |
|------|---------|--------|
| **任务成功率** | 成功调用数 / 总调用数 | ≥ 95% |
| **响应时间 P50** | 中位数耗时 | < 2s |
| **响应时间 P99** | 99 分位耗时 | < 5s |
| **降级触发率** | 降级调用数 / 总调用数 | < 10% |
| **LLM Judge 评分** | 7 维加权平均 | ≥ 4.0/5.0 |
| **用户满意度** | 显式评分平均 | ≥ 4.0/5.0 |
| **置信度校准** | 预测置信度与实际准确率相关性 | ≥ 0.7 |

#### 18.3.4 SubAgent 评估指标（多步推理）

针对 SubAgent（多步推理循环）的评估指标（参考 TRAJECT-Bench + AgentProp-Bench）：

| 指标 | 计算方式 | 目标值 | 来源 |
|------|---------|--------|------|
| **任务成功率** | 成功完成任务 / 总任务 | ≥ 90% | AgentBench |
| **工具选择准确率** | 正确工具选择 / 总工具调用 | ≥ 85% | TRAJECT-Bench |
| **参数正确率** | 正确参数 / 总参数 | ≥ 80% | TRAJECT-Bench |
| **依赖满足度** | 正确顺序执行 / 总任务 | ≥ 90% | TRAJECT-Bench |
| **过早调用率** | 过早调用次数 / 总调用 | < 10% | AgentEscapeBench |
| **线索遵循率** | 遵循关键线索 / 总线索 | ≥ 80% | AgentEscapeBench |
| **平均步数** | 总步数 / 任务数 | ≤ 5 步 | 业务基准 |
| **最大步数** | 单任务最大步数 | ≤ max_steps | 配置限制 |
| **错误传播率** | 错误步骤数 / 总步骤 | < 15% | AgentProp-Bench |
| **拒绝率** | 主动拒绝错误 / 应拒绝总数 | ≥ 70% | AgentProp-Bench |
| **恢复率** | 错误后恢复 / 错误总数 | ≥ 60% | AgentProp-Bench |
| **执行时间 P99** | 99 分位耗时 | < 15s | 业务基准 |
| **降级触发率** | 降级调用数 / 总调用 | < 15% | 业务基准 |
| **LLM Judge 轨迹分** | 7 维加权平均 | ≥ 3.8/5.0 | 自定义 |

#### 18.3.5 评估方法选择

| 评估场景 | 推荐方法 | 原因 |
|---------|---------|------|
| **单元测试** | 规则匹配 + 字符串匹配 | 精确、可重复 |
| **功能测试** | LLM-as-a-Judge (G-Eval) | 处理开放性答案 |
| **轨迹测试** | LLM-as-a-Judge + 规则混合 | 同时评估过程和结果 |
| **回归测试** | 基线对比 + 多模型投票 | 稳定性、可对比 |
| **用户反馈** | 显式评分 + 隐式行为 | 真实场景信号 |
| **A/B 测试** | 统计显著性检验 | 决策依据 |

### 18.4 自建评测集 DotaBench

由于 Dota 2 领域无公开评测集，需要构建自有的评测集。

#### 18.4.1 评测集结构

```
DotaBench/
├── skill_bench/
│   ├── lineup_analyzer/
│   │   ├── cases.jsonl          # 测试用例
│   │   ├── expected.jsonl        # 期望输出
│   │   └── judge_prompts.yaml   # Judge prompt
│   ├── dialogue_understander/
│   ├── meta_analyzer/
│   ├── knowledge_query/
│   └── web_search/
├── subagent_bench/
│   ├── counter_pick/
│   ├── item_recommender/
│   ├── skill_builder/
│   ├── event_advisor/
│   ├── proactive_recommender/
│   └── feedback_learner/
├── e2e_bench/
│   ├── user_scenarios.jsonl     # 端到端场景
│   └── eval_scenarios.yaml      # 场景定义
└── human_eval/
    ├── sample_pool.jsonl        # 人工评估样本池
    └── rubrics.yaml             # 评分量表
```

#### 18.4.2 测试用例设计原则

1. **覆盖度**：覆盖各 Skill/SubAgent 的典型场景
2. **难度分层**：简单（30%）、中等（50%）、困难（20%）
3. **多样性**：包含正常输入、边界输入、异常输入
4. **可对比**：每条用例都有期望输出（参考答案）
5. **可扩展**：支持增量添加新用例

#### 18.4.3 测试用例示例

**Skill 用例：阵容分析**

```json
{
  "case_id": "lineup_001",
  "input": {
    "radiant_heroes": ["幻影刺客", "水晶室女", "潮汐猎人", "剧毒术士", "发条技师"],
    "dire_heroes": ["敌法师", "莉娜", "莱恩", "沙王", "巫医"]
  },
  "expected": {
    "key_points": [
      "己方有 PA + 水晶室女的高爆发组合",
      "己方控制能力强（潮汐、剧毒、发条）",
      "敌方有敌法师克制 PA",
      "敌方控制偏弱（莱恩、沙王单体控制）"
    ],
    "verdict": "己方阵容控制强、爆发高，敌方单体控制多"
  },
  "difficulty": "medium",
  "tags": ["control", "burst", "anti-carry"]
}
```

**SubAgent 用例：英雄克制**

```json
{
  "case_id": "counter_pick_001",
  "input": {
    "enemy_heroes": ["幻影刺客", "火枪手"]
  },
  "expected": {
    "top_recommendations": [
      {"hero": "敌法师", "reason": "法术免疫克制 PA 标记"},
      {"hero": "潮汐猎人", "reason": "技能增强降低 PA 暴击伤害"},
      {"hero": "末日使者", "reason": "大招无视 BKB"}
    ],
    "must_include_heroes": ["敌法师", "潮汐猎人"]
  },
  "difficulty": "easy",
  "tags": ["counter", "pa", "sniper"]
}
```

### 18.5 LLM-as-a-Judge 设计

参考 [Microsoft Foundry 2026.01 报告](https://techcommunity.microsoft.com/blog/azure-ai-foundry-blog/evaluating-ai-agents-can-llm%E2%80%91as%E2%80%91a%E2%80%91judge-evaluators-be-trusted/4480110) 的三大可靠性支柱，设计可靠的 Judge。

#### 18.5.1 Judge 评分 Prompt 模板

```yaml
lineup_analyzer_judge:
  system: |
    你是一名 Dota 2 阵容分析质量评估专家。
    请基于以下 7 个维度评估输出质量（1-5 分）：
    1. 正确性（25%）
    2. 完整性（15%）
    3. 相关性（15%）
    4. 工具选择（15%）
    5. 效率（10%）
    6. 鲁棒性（10%）
    7. 个性化（10%）
  
  template: |
    ## 输入
    己方阵容：{radiant_heroes}
    敌方阵容：{dire_heroes}
    
    ## 期望关键点
    {expected_points}
    
    ## 实际输出
    {actual_output}
    
    ## 评估
    请按 7 维度评分，并给出总分（加权平均）和简要理由。
    
    输出 JSON 格式：
    {{
      "correctness": 1-5,
      "completeness": 1-5,
      "relevance": 1-5,
      "tool_selection": 1-5,
      "efficiency": 1-5,
      "robustness": 1-5,
      "personalization": 1-5,
      "total_score": 加权平均,
      "reasoning": "评分理由"
    }}
```

#### 18.5.2 Judge 可靠性保障

| 风险 | 缓解措施 |
|------|---------|
| 位置偏见 | 盲评（打乱 A/B 顺序） |
| 长度偏见 | 限制输入长度，明确相关性 > 长度 |
| 自我偏好 | 使用不同家族的 LLM 作为 Judge |
| 采样噪声 | temperature=0，多次采样取平均（≥3 次） |
| 模型间分歧 | 多模型投票（GPT-4o + Claude + Gemini） |
| 跨语言退化 | 始终使用中文，避免混入英文术语 |

#### 18.5.3 Judge 校准方法

借鉴 [BabelJudge](https://arxiv.org/pdf/2606.22329) 的"Gold-labelling by degradation"思想：

1. **准备参考答案**：人工标注的高质量答案
2. **构造扰动样本**：对参考答案进行可控扰动（删除、错误、冗余）
3. **测试 Judge 一致性**：扰动样本应被 Judge 识别为低分
4. **持续校准**：每月重新校准一次

### 18.6 评估工具选型

#### 18.6.1 推荐方案

| 评估场景 | 推荐工具 | 理由 |
|---------|---------|------|
| 单元测试 | **pytest** + 自定义评估器 | 项目已有基础 |
| LLM-as-a-Judge | **DeepEval** | pytest 风格，CI 集成好，**G-Eval/DAG/QAG** 三种方法 |
| 轨迹评估 | **MLflow Tracing** + 自定义评分 | 业内最广泛使用 |
| 知识查询 RAG 指标 | **Ragas** | RAG 评测起家，faithfulness/context_precision 等指标完善 |
| 可视化 | **MLflow UI** / **Arize Phoenix** | Trace 时间线可视化 |
| 在线监控 | **Langfuse**（已有） | 项目已集成 |
| 自建场景 | **自研 DotaBench** | 领域特定 |

#### 18.6.2 与现有系统集成

DotaHelperAgent 已有 Langfuse Trace 系统，可直接复用：

- Trace 记录每步执行（已有）
- 评估结果记录到 Trace（新增）
- 用户反馈关联 Trace（已有）
- 评分上报 Langfuse Score（已有）

### 18.7 评估实施计划

#### 18.7.1 分阶段实施

| 阶段 | 时间 | 任务 | 验收标准 |
|------|------|------|---------|
| **阶段 1** | 第 1-2 周 | 构建 DotaBench 评测集（各 Skill/SubAgent 至少 30 条用例） | 评测集覆盖度 > 80% |
| **阶段 2** | 第 2-3 周 | 实现 LLM-as-a-Judge（7 维评分）+ DeepEval 集成 | Judge 评分与人工评分一致性 > 80% |
| **阶段 3** | 第 3-4 周 | 实现 Trajectory 评估（针对 SubAgent） | 轨迹评分与专家分析一致 |
| **阶段 4** | 第 4-5 周 | 实现回归测试 + A/B 测试框架 | 自动化回归报告 |
| **阶段 5** | 第 5-6 周 | 在线监控仪表板 + 告警 | 实时监控上线 |
| **阶段 6** | 第 6 周+ | 持续优化 + Judge 校准 | 持续改进 |

#### 18.7.2 验收标准

1. **评测集覆盖度**：DotaBench 至少 200 条用例，覆盖所有 Skill/SubAgent
2. **Judge 可靠性**：Judge 评分与人工评分一致性 ≥ 80%
3. **自动化程度**：CI 集成回归测试，每次 PR 触发
4. **可视化**：评估仪表板支持多维筛选、趋势分析
5. **响应时间**：单次评估 < 30s（LLM Judge）
6. **成本控制**：月度评估成本 < $100

### 18.8 风险与缓解

| 风险 | 缓解措施 |
|------|---------|
| LLM Judge 偏见 | 多模型投票、盲评、temperature=0 |
| 评测集偏差 | 持续扩充用例，覆盖边缘情况 |
| 评估成本高 | 关键场景用 GPT-4o，大规模用开源 LLaMA 3 70B |
| 评估延迟 | 异步执行，CI 缓存结果 |
| 主观维度难量化 | 多评估员平均，明确评分标准 |
| 游戏版本变化 | 评测集随版本更新，建立版本映射 |

### 18.9 持续改进机制

1. **每周**：CI 回归测试，输出评分趋势
2. **每月**：Judge 校准，更新评测集
3. **每版本**：A/B 测试新方案，统计显著性检验
4. **每季度**：评估体系复盘，引入新方法（如新 LLM Judge 技术）

### 18.10 参考资料

- [TRAJECT-Bench (ICLR 2026)](https://openreview.net/pdf?id=TZWnWvsQ0X) - 轨迹感知评测
- [AgentProp-Bench](https://arxiv.org/html/2604.16706v1) - 错误传播分析
- [BabelJudge](https://arxiv.org/pdf/2606.22329) - LLM Judge 可靠性
- [Microsoft Foundry: LLM-as-a-Judge Reliability](https://techcommunity.microsoft.com/blog/azure-ai-foundry-blog/evaluating-ai-agents-can-llm%E2%80%91as%E2%80%91a%E2%80%91judge-evaluators-be-trusted/4480110) - 三大可靠性支柱
- [WebArena](https://arxiv.org/html/2307.13854v4) - 任务成功率评估
- [MLflow Top 5 Agent Evaluation Tools](https://mlflow.org/top-5-agent-evaluation-frameworks/) - 工具对比
- [DeepEval LLM-as-a-Judge Guide](https://deepeval.com/guides/guides-llm-as-a-judge) - G-Eval/DAG/QAG
- [GAIA Agent Eval Benchmark](https://amd-gaia.ai/docs/eval) - 7 维评分量表
- [Agent 评测不能只看答案：从 Output Eval 到 Trajectory Eval](https://blog.csdn.net/Huang_ZX_259/article/details/162561227) - Output vs Trajectory
- [Evaluating AI Agents: Metrics and Best Practices (Maxim AI)](https://www.getmaxim.ai/articles/evaluating-ai-agents-metrics-and-best-practices/) - 评估最佳实践

---

> **文档版本**: v1.3  
> **最后更新**: 2026-07-06
