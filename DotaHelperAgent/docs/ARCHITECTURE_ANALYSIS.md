# DotaHelperAgent 待改进事项

> 最后更新：2026-06-22

## 一、待改进优先级

> 更新时间：2026-06-22

### 1.1 总体架构升级路线图（第十六章）

**目标**: 将 DotaHelperAgent 从"被动查询助手"升级为"智能决策推荐系统"

| 阶段 | 升级方向 | 优先级 | 预计工作量 | 核心内容 | 状态 |
|------|---------|--------|----------|---------|------|
| **第一阶段** | **知识管理能力升级** | **P0** | 1-2周 | 向量数据库 + 攻略文档检索 | ✅ 已完成 |
| **第二阶段** | **GSI 实时数据处理** | **P1** | 2-3周 | GSI服务器 + 状态管理 + 事件处理 | ✅ 已完成 |
| **第三阶段** | **推理和决策能力增强** | **P1** | 3-4周 | 数据驱动决策 + 混合推理 | ❌ 待实现 |
| **第四阶段** | **个性化学习能力** | **P2** | 2-3周 | 用户画像 + 在线学习 | ❌ 待实现 |
| **第五阶段** | **多模态交互能力** | **P2** | 1-2周 | 语音播报 + 数据可视化 | ❌ 待实现 |

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
| **P1** | **Agent主动推荐机制** | 大 | 高 | **第三阶段** | ❌ 待实现 |
| **P1** | **GSI数据与Agent结合方案** | 中 | 高 | **第二阶段** | ✅ 已完成 |
| **P1** | **GSI主动推荐功能PRD** | 大 | 高 | **第二阶段** | ✅ 已完成 |
| P1 | Prompt 版本管理（Langfuse） | 中 | 中 | **第三阶段** | ❌ 待实现 |
| **P1** | **工具执行并行化** | 中 | 中 | - | ✅ 已完成 |
| P2 | 前端样式优化 | 中 | 中 | **第五阶段** | ✅ 已完成 |
| P2 | 用户反馈学习 | 大 | 中 | **第四阶段** | ❌ 待实现 |
| P2 | 语音提醒系统 | 中 | 低 | **第五阶段** | ❌ 待实现 |

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
| P2 | 反思结果驱动策略调整 | 2026-05-17 | `core/agent_controller.py#_adjust_strategy` |
| P2 | 前端样式优化 | 2026-06-14 | `frontend/src/components/` + `frontend/src/styles/dota-theme.css` |

---

### 1.3 待办项合并与冲突分析

#### 1.3.1 合并关系说明

**第二阶段：GSI 实时数据处理** 整合了以下待办项（✅ 已完成，2026-06-22）：
- ✅ **GSI 实时游戏状态监控**（第八章）→ 第二阶段核心功能
- ✅ **游戏事件提醒系统**（第九章）→ 第二阶段事件处理器
- ✅ **GSI数据与Agent结合方案**（第十一章）→ 第二阶段工具层集成
- ✅ **GSI主动推荐功能PRD**（第十二章）→ 第二阶段产品化方案

**第三阶段：推理和决策能力增强** 整合了以下待办项：
- ✅ **Agent主动推荐机制**（第十章）→ 第三阶段决策融合器
- ✅ **Prompt 版本管理**（第六章）→ 第三阶段 Prompt 优化

**第四阶段：个性化学习能力** 整合了以下待办项：
- ✅ **用户反馈学习**（P2）→ 第四阶段在线学习引擎

**第五阶段：多模态交互能力** 整合了以下待办项：
- ✅ **语音提醒系统**（P2）→ 第五阶段语音播报功能
- ✅ **前端样式优化**（P2）→ 第五阶段数据可视化

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
| P1 | Agent主动推荐机制 | P1 | 保持不变，属于第三阶段核心 |
| P1 | GSI数据与Agent结合方案 | P1 | 保持不变，属于第二阶段 |
| P1 | GSI主动推荐功能PRD | P1 | 保持不变，属于第二阶段 |
| P1 | Prompt 版本管理 | P1 | 保持不变，属于第三阶段 |
| P2 | 用户反馈学习 | P2 | 保持不变，属于第四阶段 |
| P2 | 语音提醒系统 | P2 | 保持不变，属于第五阶段 |
| P2 | 前端样式优化 | P2 | **已完成，2026-06-14** |
| - | **知识管理能力升级** | **P0** | **已完成，2026-06-14** |

#### 1.3.4 实施建议

**推荐实施顺序**：
1. ~~**第一阶段（P0）**：知识管理能力升级 - 建立知识库基础设施~~ ✅ 已完成
2. ~~**第二阶段（P1）**：GSI 实时数据处理 - 实现实时监控能力~~ ✅ 已完成（2026-06-22）
3. **第三阶段（P1）**：推理和决策能力增强 - 提升决策质量（当前优先）
4. **第四阶段（P2）**：个性化学习能力 - 实现个性化推荐
5. **第五阶段（P2）**：多模态交互能力 - 提升用户体验

**关键依赖关系**：
- ~~第二阶段依赖第一阶段（知识库支持决策推荐）~~ ✅ 第一阶段已完成
- ~~第三阶段依赖第二阶段（实时数据支持推理）~~ ✅ 第二阶段已完成
- 第四阶段依赖第三阶段（决策能力支持个性化）
- 第五阶段可并行开发（相对独立）

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
- **Prompt 管理**：版本化 Prompt 模板（待集成）
- **评分系统**：用户反馈和自动评估 ✅
- **成本分析**：Token 使用量和成本统计（待集成）
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
| Prompt 管理 | 版本化 Prompt 模板 | ❌ 未集成 |

### 2.3 特性亮点

1. **可选导入设计** - SDK 未安装时自动降级为 NoOpObservation，不影响项目运行
2. **配置化管理** - 支持环境变量和 YAML 配置文件，灵活切换环境
3. **完整的测试覆盖** - 单元测试 + 集成测试

### 2.4 预期收益

1. **调试效率提升**：快速定位问题请求 ✅
2. **性能优化**：识别慢查询和瓶颈 ✅（通过 API 调用追踪）
3. **成本控制**：Token 使用量可视化 ✅（在 llm_client.py 中记录）
4. **质量评估**：用户评分 + 自动评估 ✅
5. **Prompt 优化**：版本管理和 A/B 测试 ❌（未集成，属于第三阶段）

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

## 七、P1：Prompt 版本管理 ❌

**目标**: 使用 Langfuse 管理 Prompt 模板，支持版本化和 A/B 测试

**实现位置**: 
- `utils/prompt_manager.py` - Prompt 管理器（新建）
- `config/prompts/` - Prompt 配置目录

**核心功能**:
- Prompt 模板版本管理
- A/B 测试支持
- Prompt 性能追踪
- 自动回滚机制

**示例代码**:
```python
# utils/prompt_manager.py
from langfuse import Langfuse

class PromptManager:
    """Prompt 管理器 - 基于 Langfuse"""
    
    def __init__(self):
        self.client = Langfuse()
    
    def get_prompt(self, name: str, version: str = None) -> str:
        """获取 Prompt 模板"""
        prompt = self.client.get_prompt(name, version=version)
        return prompt.prompt
    
    def create_prompt(self, name: str, prompt: str, config: Dict = None):
        """创建新 Prompt"""
        self.client.create_prompt(
            name=name,
            prompt=prompt,
            config=config
        )
    
    def compare_prompts(self, name: str, versions: List[str], test_cases: List[Dict]):
        """A/B 测试 Prompt"""
        results = []
        for version in versions:
            prompt = self.get_prompt(name, version)
            # 执行测试...
            results.append({"version": version, "score": score})
        return results
```

**预期收益**:
- Prompt 优化有据可依
- 降低 Prompt 变更风险
- 提升 Prompt 质量

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

## 十一、P1：Agent主动推荐机制 ❌

**目标**: 在游戏过程中，Agent自动推送建议，无需用户主动输入问题

**核心思路**:

| 推荐模式 | 触发条件 | 推送内容示例 |
|---------|---------|-------------|
| **基于游戏事件** | 堆野、符文、肉山等关键事件 | "堆野时间到了！建议前往野区堆野" |
| **基于状态变化** | 血量<30%、金钱>=装备价格、技能冷却结束 | "血量过低！建议立即回城补给" |
| **基于游戏阶段** | 对线期、中期、后期、决胜期 | "中期！建议参团，协助团队推进" |
| **基于团队状态** | 团队领先/劣势、团队状态良好/不佳 | "团队领先！建议主动推塔，扩大优势" |
| **基于用户行为** | 用户连续3次错过堆野/符文 | "你最近3次都忘记堆野了，建议这次去堆野" |

**技术实现**:
- WebSocket实时推送（双向通信）
- SSE流式推送（单向推送）
- 桌面通知推送（Windows通知）

**预期变化**:
- Agent从"被动响应"升级为"主动推送"
- 用户无需主动输入问题，Agent自动推送建议
- 实时游戏状态监控，主动推送策略建议
- 基于用户行为模式提供个性化建议
- 大幅提升用户体验和实用性

---

## 十一、P1：GSI数据与Agent结合方案 ❌

**目标**: 将GSI实时数据与Agent工具结合，提供实时问答和策略建议

**核心思路**:

| 结合方式 | 用户查询示例 | Agent回答示例（基于GSI数据） |
|---------|-------------|----------------------------|
| **实时数据驱动** | "我血量只有30%，该怎么办？" | "建议回城补给，或使用治疗药膏/魔瓶" |
| **游戏事件策略** | "堆野时间到了！" | "建议前往野区堆野，优先堆大野点（距离500码）" |
| **实时问答** | "我现在等级多少？" | "你当前等级：12级，经验值：8500/10000" |
| **整体策略建议** | "我现在应该做什么？" | "根据当前状态（等级12、金钱2500、血量80%），建议：1.购买BKB；2.前往中符位置；3.准备团战" |

**新增工具**:
- `GSIDataTool` - 获取英雄状态、游戏时间、玩家数据、技能冷却、物品状态
- `GameEventStrategyTool` - 堆野策略、符文策略、肉山策略建议
- `OverallStrategyTool` - 根据综合状态提供整体策略建议

**预期变化**:
- Agent从"静态问答助手"升级为"实时游戏助手"
- 实时交互能力增强，根据游戏状态回答问题
- 个性化建议，根据用户当前状态提供建议
- 游戏节奏掌握优化，帮助用户掌握游戏节奏

---

## 十二、P1：GSI主动推荐功能PRD ❌

**目标**: 实现基于GSI的Agent主动推荐系统，提供游戏过程中的智能建议推送

### Problem Statement

**问题**: 在Dota 2游戏过程中，用户很少会主动打字或语音输入问题，导致Agent无法及时提供帮助。用户需要一种机制，让Agent能够自动感知游戏状态并主动推送建议，而不是等待用户触发。

**用户视角**: "我在游戏时很忙，没时间打字问问题。我希望Agent能自动告诉我什么时候该堆野、什么时候该去抢符、什么时候该参团，而不是我每次都要主动问。"

### Solution

**核心思路**: Agent主动感知游戏状态，基于LLM生成个性化建议，通过桌面通知和语音提醒推送给用户。

**关键特性**:
- 实时游戏状态监控（GSI集成）
- LLM驱动的个性化建议生成
- 多渠道推送（桌面通知 + 语音提醒）
- 用户行为模式学习
- 可配置化的提醒设置

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

- **WebSocket Push**: Not implementing WebSocket push (using desktop notifications and voice instead)
- **SSE Push**: Not implementing SSE push (using desktop notifications and voice instead)
- **State Change Reminders**: Not implementing state change reminders (health, gold, skill cooldown, level up) - focusing on game events, game phases, and team states only
- **STRATZ API Integration**: Not integrating STRATZ API for game data (using Dota 2 client GSI only)
- **Mobile Notifications**: Not implementing mobile notifications (Windows desktop only)
- **Multi-user Support**: Not implementing multi-user support (single-user mode only)
- **Cloud Storage**: Not implementing cloud storage for behavior history (SQLite local storage only)

---

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

## 十四、P2：用户反馈学习 ❌

**目标**: 基于用户反馈优化Agent表现

**实现位置**: 
- `core/feedback_learner.py` - 反馈学习器（新建）
- `memory/feedback_store.py` - 反馈存储（新建）

**核心功能**:
- 用户反馈收集（评分、评论）
- 反馈分析（识别常见问题）
- 自动优化（调整工具权重、Prompt模板）
- A/B测试（验证优化效果）

**预期收益**:
- Agent表现持续优化
- 用户满意度提升
- 问题自动识别与修复

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

## 十六、Agent 架构升级总体思路 ❌

> **状态**: ❌ 待实现
> **更新时间**: 2026-06-12
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

#### **第三阶段：推理和决策能力增强**（P1，3-4 周）

**目标**: 实现数据驱动的决策推荐

**关键任务**:
1. 收集和处理历史对局数据
2. 训练胜率预测模型
3. 实现决策融合器
4. 新增数据驱动推荐工具

**预期收益**:
- 基于历史数据的胜率预测
- 多源决策融合，提升推荐质量

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

> **文档版本**: v1.0  
> **最后更新**: 2026-06-12
