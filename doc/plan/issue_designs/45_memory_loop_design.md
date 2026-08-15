# 设计文档 45 — 记忆回路只写不读 / 读写不对称

> 触发：2026-08-15 第三轮评审——① **L4 反例/经验只写不读**：`note_pattern` 有写入（core/orchestrator.py:243、
> facade/api.py:690），但 `retrieve_patterns` 全仓库**无任何调用**——沉淀的成功/失败模式从不被规划或失败归因消费；
> ② **记忆注入两条路径不对称**：single 路径经 `GapExecutor` 注入 `memory_context`（core/orchestrator.py:189
> `memory_context_fn=self._memory_context_fn()`），team 路径 `AnalyzerAgent.analyze_observation`（team/analyzer_agent.py:71-79）
> 构造 `AnalysisContext(competitor_name, dimension, rag_context=...)` **不传 memory_context**——默认多 Agent 入口反而
> 丢了记忆增强。
> 依赖：设计文档 35（`memory/session_archive.py` `recent_context` 相关度召回已有；`IFourLayerMemory.note_pattern/
> retrieve_patterns` 契约已有，`memory/four_layer_memory.py` 已实现）。
>
> **实现状态（2026-08-15）**：已落地 ✅。L4 消费接线（`retrieve_patterns_with_outcome` 规划提权/降权 +
> `failure_patterns_for` 源选择降级 `set_failure_penalties`）；team 路径 `AnalyzerAgent._retrieve_memory` 注入
> `memory_context`（与 single 的 GapExecutor 同口径 recent_context）；`TeamOrchestrator` 复用外层 selector。
> 详见 `doc/plan/issue_designs/README.md` 设计文档 45 修复说明。

## 1. 问题现状

- **L4 patterns 是"数据僵尸"**：写入侧 `note_pattern`（orchestrator.py:243 记"缺口 X 由源 Y 有效"；api.py:690
  同），读取侧 `retrieve_patterns`（interfaces/memory.py:69-71 定义"供规划与失败归因联动"）**零调用方**
  （grep 仅 interfaces/memory.py 与 memory/ 实现，生产代码无消费）。
- **记忆注入路径分裂**：single（GapExecutor `_retrieve_memory`，gap_executor.py:217-225）与 team
  （AnalyzerAgent `analyze_observation`，analyzer_agent.py:66-79）对同一任务产出**不同**的记忆增强——
  同任务在两条模式（`mode="single"` vs `mode="team"`，facade/api.py:174-179）下 prompt 不同、结论可能漂移。
- 影响：四层记忆的 L3/L4 被写成"计数/记录"，对质量提升贡献弱；两条路径行为不一致是"宣称能力与实际接线不符"的又一实例。

## 2. 目标设计

1. **让 L4 被消费**：失败归因/源选择时检索反例 → 调整降级链或重试策略；规划时检索成功模式 → 缺口提权
   （对齐现有 `_apply_memory_boost` 的 L3 用法）。
2. **记忆注入收敛到单点**：team 路径补 `memory_context` 注入，与 single 对齐；读取逻辑收敛到同一函数
   （复用 `recent_context`，35 已有）。
3. **回归安全**：无记忆（`memory=None`/`enable_memory=False`）时行为与现状一致；注入内容不影响 mock 抽取
   （与 34 的"排后于 RAG、不影响 mock LLM 对观测文本的抽取"约定一致）。

## 3. 模块/接口设计

### 3.1 L4 消费（`core/strategic_loop.py` / `collector/source_selector.py`）

```python
# 规划：成功模式 → 提权（与 L3 的 _apply_memory_boost 并列）
patterns = memory.retrieve_patterns(competitor.name, gap.field)   # 成功反例
for p in patterns:
    if "success" in p: gap.confidence = min(gap.confidence + 0.1, 0.9)
    if "failure" in p and gap.confidence == 0: gap.priority = max(gap.priority - 1, 1)  # 反例降权

# 源选择：反例命中 → 该源降级（记录 failures 的源排后）
selector.set_failure_penalties(memory.failure_patterns_for(competitor))   # 契约新增可选
```

- 只读不改写：消费侧不新增写入，避免放大僵尸数据；读取失败静默降级（try/except，既有风格）。

### 3.2 team 路径补记忆注入（`team/analyzer_agent.py`）

```python
def analyze_observation(self, competitor_name, obs) -> DimensionResult:
    analyzer = self._registry.get(obs.gap_field)
    return analyzer.analyze(
        obs,
        InfoGap(field=obs.gap_field),
        AnalysisContext(
            competitor_name=competitor_name,
            dimension=analyzer.dimension,
            rag_context=self._retrieve_rag(competitor_name, obs.gap_field),
            memory_context=self._retrieve_memory(competitor_name, obs.gap_field),   # 新增，与 single 对齐
        ),
    )
```

- `AnalyzerAgent` 增加 `memory` 依赖（`__init__` 已有 `memory` 参数，BaseAgent 已持有），新增 `_retrieve_memory`
  复用 `recent_context`（与 GapExecutor._retrieve_memory 同口径）。
- `AnalysisContext.memory_context`（interfaces/context.py）已存在，只需接线。

### 3.3 消费点收敛

- 读取统一走 `recent_context`（35）与 `retrieve_patterns`，不新增第三套召回；`core/orchestrator.py` 与
  `team/analyzer_agent.py` 各持一份轻量包装，内部同源。

## 4. 接入方式

```
规划：retrieve_patterns（成功→提权 / 失败→降权）＋ _apply_memory_boost（L3）——在 StrategicPlanner.plan
分析：single（GapExecutor._retrieve_memory）与 team（AnalyzerAgent._retrieve_memory）都注入 memory_context
源选择：反例命中源 → set_failure_penalties 降级
记忆层：只读消费，不新增写入；memory=None 时全部跳过（现状不变）
```

## 5. 验证方式

- **单测（L4 消费）**：`note_pattern` 写"失败: 源 X 无数据" → `retrieve_patterns` 取回 → 规划器对同缺口降权/
  源选择把 X 排后；成功模式提权。
- **单测（team 注入）**：team 路径 mock 下 prompt 含 `[历史经验参考]` 块（与 single 路径一致）；`memory=None`
  时两块均无。
- **集成（路径一致性）**：同任务 `mode="single"` 与 `mode="team"` 下注入的记忆块相同（消除漂移）。
- **回归**：mock LLM 抽取不受新增注入块影响（对齐 34 基准的 `_user_text` 约定）；`enable_memory=False` 全绿。

## 6. 实现优先级与工作量

- 优先级：**中**（记忆"写了要能用"是四层记忆叙事的关键一环；路径漂移已在 43 的架构问题下）
- 工作量：约 0.5-1 天。
  - L4 消费（规划提权/降权 + 源选择降级）：0.3 天；
  - team 路径 memory_context 注入：0.2 天；
  - 测试：0.3 天。
- 前置：35（`recent_context` 已有）；独立于 43/44/46，可先落地。
