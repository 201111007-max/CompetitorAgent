# 迁移对照表（dota_helper → competitor_agent）

> 本文档是架构设计文档第 8 节的展开实现指南。
> 迁移原则：**复制通用能力 → 重写领域逻辑**；保持双向零 import 耦合。

---

## 1. 迁移策略总览

| 处置 | 数量 | 说明 |
|------|------|------|
| 复制 + 保留 | 若干 | 纯通用能力，无领域依赖，可整体拷贝 |
| 复制 + 通用化 | 若干 | 有轻微 Dota 痕迹，去领域字段后迁移到 core/ |
| 复制 + 领域化 | 若干 | 骨架通用，但键/模式需按竞品调整 |
| 重写领域逻辑 | 若干 | 与 Dota 无关，全新实现 |
| 不迁移 | 若干 | Dota 专属，无需保留 |

---

## 2. 模块级映射表

### 2.1 框架内核（core/ 与 agent/）

| dota_helper 模块 | 处置 | competitor_agent 目标 | 迁移要点 |
|------------------|------|-----------------------|---------|
| `secret_vault.py` | 复制 + 保留 | `secret_vault.py` | 无领域依赖；数据目录改 `~/.competitor_agent/`，日志前缀改名 |
| `orchestrator/strategic_loop.py` | 复制 + 领域化 | `core/strategic_loop.py` | 双循环骨架保留；match_type 分类 → InfoGap 清单生成 |
| `orchestrator/tactical_loop.py` | 复制 + 领域化 | `core/tactical_loop.py` | 骨架保留；analyzer 接口替换为竞品维度分析器 |
| `engines/budget.py` | 复制 + 保留 | `core/budget.py` | 纯通用（IterationBudget） |
| `engines/stop_verifier.py` | 复制 + 保留 | `core/stop_verifier.py` | 纯通用（Hook 验证终止） |
| `engines/compressor.py` | 复制 + 保留 | （可选并入 core/compressor.py） | 上下文压缩，通用 |
| `engines/prompt_builder.py` | 复制 + 通用化 | `agent/prompts/` | 动态注入点保留 |
| `agent/react_agent.py` | 复制 + 通用化 | `agent/react_agent.py` | 去掉 match_id 自动补全，改 gap 上下文补全 |
| `agent/react_loop.py` | 复制 + 通用化 | `agent/react_loop.py` | SSE 9 事件契约保留 |
| `agent/response_parser.py` | 复制 + 保留 | `agent/response_parser.py` | 纯通用 |
| `agent/tool_registry.py` + `tool_dispatcher.py` | 复制 + 保留 | `agent/tool_dispatcher.py` | 纯通用 |
| `agent/tool_guard.py` | 复制 + 保留 | `agent/tool_guard.py` | 护栏纯通用 |
| `agent/circuit_breaker.py` | 复制 + 保留 | `agent/circuit_breaker.py` | 纯通用 |
| `agent/error_classifier.py` | 复制 + 保留 | `agent/error_classifier.py` | 四类错误纯通用 |
| `agent/injection_guard.py` | 复制 + 保留 | `agent/injection_guard.py` | 三层注入防御纯通用 |
| `agent/session_manager.py` | 复制 + 保留 | `agent/session_manager.py` | 通用 |
| `parallel/parallel_runner.py` + `subagent.py` | 复制 + 保留 | `core/parallel_runner.py` + `core/subagent.py` | 通用；budget_quota 保留 |

### 2.2 领域层（全为重写）

| dota_helper 模块 | 处置 | competitor_agent 目标 | 替换内容 |
|------------------|------|-----------------------|---------|
| `domain_types/`（match_data/analysis/report） | 重写 | `domain_types/` | match → Competitor/InfoGap/Observation/Report |
| `data_source/`（opendota_client/match_fetcher/cache） | 重写 | `collector/` | OpenDota → Web/GitHub/Pricing/Benchmark/Review 采集器 |
| `analyzers/`（teamfight/economy/laning/vision） | 重写 | `analyzers/` | 对线/团战 → 功能/定价/性能/生态/口碑 |
| `mcp_server/`（match_tools/hero_tools/...） | 重写 | `mcp_server/` | 英雄/装备 → web/github/pricing/benchmark/review |
| `report/`（report_builder/markdown_renderer） | 复制 + 通用化 | `core/report_builder.py` + `markdown_renderer.py` | 渲染骨架通用，字段替换 |
| `interfaces/`（13 个 Protocol） | 复制 + 领域化 | `interfaces/`（7 个） | 契约骨架保留，签名换领域类型 |

### 2.3 记忆 / 知识库 / 可观测

| dota_helper 模块 | 处置 | competitor_agent 目标 | 迁移要点 |
|------------------|------|-----------------------|---------|
| `memory/four_layer_memory.py` | 复制 + 领域化 | `memory/four_layer_memory.py` | 键从 match_id → competitor_name |
| `memory/session_archive.py` | 复制 + 领域化 | `memory/session_archive.py` | 归档键换竞品 |
| `memory/persistent_notes.py` | 复制 + 保留 | `memory/persistent_notes.py` | 通用 |
| `memory/skill_store.py` | 复制 + 通用化 | `memory/skill_store.py` | 提炼规则领域化（"该竞品用哪个源"） |
| `memory/dream_recap.py` | 复制 + 领域化 | `memory/evolution_memory.py` | 梦境回顾 → 数据源成功率统计 |
| `agent/rag_engine.py` + `rag_plugin.py` | 复制 + 领域化 | `knowledge_base/` | 英雄/装备索引 → 竞品文档/Changelog |
| `observability/`（logger/tracer/metrics） | 复制 + 保留 | `observability/` | 纯通用 |
| `facade/api.py` + `entrypoint.py` | 重写门面 | `facade/api.py` | review() → analyze() |
| `web_app.py` | 复制 + 通用化 | `web_app.py` | SSE 前端骨架保留 |

### 2.4 Dota 专属（不迁移）

| dota_helper 模块 | 处置 |
|------------------|------|
| `data_source/opendota_client.py` | 不迁移 |
| `analyzers/teamfight_analyzer.py` 等 5 个 | 不迁移 |
| `mcp_server/tools/hero_tools.py`/`ward_tools.py` | 不迁移 |
| `engines/data_formatter.py`（Dota 字段） | 不迁移 |

---

## 3. 迁移顺序

```
第 1 批（无依赖，直接拷）：secret_vault / observability / budget / stop_verifier
第 2 批（纯通用 agent 层）：react_agent / react_loop / response_parser / tool_dispatcher
                          / tool_guard / circuit_breaker / error_classifier / injection_guard
                          / session_manager
第 3 批（并行）：parallel_runner / subagent
第 4 批（领域化改造）：four_layer_memory / rag_engine
第 5 批（重写）：domain_types → collector → analyzers → mcp_server
第 6 批（组装）：strategic_loop / tactical_loop / report / facade
```

> 每批完成后跑 `pytest`，确保迁移不引入回归。

---

## 4. 迁移自检清单

- [ ] 不存在任何 `import dota_helper` 引用
- [ ] 所有硬编码 Dota 术语（hero/match/ward/teamfight）已从代码与注释移除
- [ ] SecretVault 数据目录已指向 `~/.competitor_agent/`
- [ ] core/ 模块可独立运行（不依赖 collector/analyzers）
- [ ] 测试文件与模块一一对应（无"孤儿"代码）
