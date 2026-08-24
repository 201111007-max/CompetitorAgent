# 设计文档 35 — 记忆摘要压缩与相关度召回（深度补充）

> 对应 `implementation_plan.md` §16.1 记忆行（"四层=JSON 计数，无摘要压缩/向量召回"）。
> 触发：2026-08-14 深度复查——"四层记忆"为四个 JSON 文件：`skill_store` 是成功 +1.0/失败 -0.5 计数（skill_store.py:47/83）、封顶 50（:20），
> `evolution_memory.py` 仅 62 行，`session_archive` 原样存档；无摘要压缩、无相关度召回、无跨会话凝练。
> 依赖：`memory/session_archive.py`、`memory/skill_store.py`、`memory/evolution_memory.py`、`knowledge_base/competitor_store.py`（复用 chunk/向量基建）。

## 1. 问题现状

- **会话原样存档**：`session_archive.py` 每次分析全文存档，跨会话复用靠"取最近"而非"凝练/召回"，长会话上下文膨胀、噪音累积。
- **技能=计数**：`skill_store.py` 的"技能"只是 (gap, source) 权重累加，不含"怎么抽更准"的方法论——"记忆怎么沉淀经验"只能答计数。
- **L4 进化记忆**：`evolution_memory.py`（62 行）仅记录成功率维度，无跨任务模式归纳。
- 影响：记忆系统的"自进化"叙事停留在计数层面，无法支撑"长会话/多任务持续变好"的说法。

## 2. 目标设计

1. **会话摘要压缩**：每次分析后对 `session_archive` 做结构化摘要（结论/证据/遗留缺口），长存档滚动压缩（超出上限时把旧会话折叠为摘要条目），上下文注入用"摘要 + 最近相关会话"而非全量。
2. **相关度召回**：会话摘要与技能条目可检索（复用设计文档 32 的向量/词袋基建），`enrich_prompt` 按任务相关度召回最近记忆，而非"最近 N 条"。
3. **经验凝练（技能语义化）**：`skill_store` 条目增加"成功做法"文本字段（如"该源抓不到 → 降级到榜单源"），由分析后链路沉淀，注入 prompt 时同时给"选源结论 + 做法"。
4. **进化记忆归纳**：`evolution_memory` 从"成功率表"升级为"可检索的经验/反例清单"（跨竞品归纳），低置信模式可回溯。

## 3. 模块/接口设计

### 3.1 `memory/session_summary.py`（新增）

```python
@dataclass
class SessionSummary:
    competitor: str
    dimensions: list[str]          # 已覆盖维度
    key_conclusions: list[str]     # 结构化结论（取 confidence>=0.6 的 DimensionResult.summary）
    pending_gaps: list[str]        # 遗留缺口
    created_at: str
    session_id: str

def summarize_session(session: dict, max_conclusions: int = 5) -> SessionSummary: ...
def compress_archive(entries: list[dict], keep_full: int, summarize_rest: bool = True) -> list[dict]:
    """长存档滚动压缩：最近 keep_full 条保全文，更旧折叠为 SessionSummary。"""
```

- 结论抽取**不做 LLM**（规则取高置信 summary），保证无 Key 可复现；可选 LLM 凝练留待后续。

### 3.2 `session_archive.py` 扩展

- `compress(max_entries=20, keep_full=5)`：超限压缩；`recent_context(competitor, top_k, query="")` 返回"摘要 + 最近全文"，`query` 非空时经可检索索引按相关度召回（复用 `CompetitorStore.search` 的 lexical 层，向量层接入后自动升级）。

### 3.3 `skill_store.py` 语义化

- `Skill` 增 `method: str = ""`（`interfaces/context.py`），`record_success(..., method="")` 沉淀做法；`retrieve_skills` 返回含 method；`enrich_prompt`（`agent/prompts/react_system.py`）注入时带做法文本。

### 3.4 `evolution_memory.py` 归纳

- `record_outcome` 保留成功率；新增 `note_pattern(competitor, dimension, pattern, outcome)` 记录可检索反例/经验，`retrieve_patterns(competitor, dimension)` 供规划与失败归因（设计文档 31）联动。

## 4. 接入方式

```
api.analyze/analyze_team 归档后 → summarize_session → 写/更新 SessionSummary
  → session_archive.compress（超限滚动压缩）
enrich_prompt / FourLayerMemory.recent_context → 按任务 query 召回"摘要+相关会话+带 method 技能"
evolution_memory.note_pattern 由分析后链路（成功/降级分支）调用
```

- 记忆写入仍由 `enable_memory`（设计文档 30）门控，开关语义不变；压缩不改变既有 `list_sessions`/`get_history` 契约（原样返回全文，压缩仅影响内部注入路径）。

## 5. 验证方式

- **单测（summarize/compress）**：高置信结论被提取；超限后旧会话折叠为摘要、最近 keep_full 条保全文；可逆无损于 `get_history`。
- **单测（skill 语义化）**：record 带 method → retrieve 带回 → prompt 注入含做法；兼容旧字段（method 默认空）。
- **单测（evolution 归纳）**：note_pattern/retrieve 往返；与失败归因（设计文档 31）联动读取。
- **集成（上下文注入）**：多次分析后 `recent_context(query=...)` 命中相关旧结论（相关度召回而非"最近 N 条"）；注入内容较压缩前更精简。
- **回归**：记忆层既有测试（`test_memory.py`/`test_m2_integration.py`/`test_timeline_memory.py`）全绿；消融 `enable_memory=False` 零写入语义不变。

## 6. 实现优先级与工作量

- 优先级：**中低**（深度加分项，不改变功能交付）。
- 工作量：约 1 天。
  - `session_summary` + 压缩：0.3 天；
  - `recent_context` 相关度召回（复用词袋/向量）：0.3 天；
  - skill method + evolution 归纳 + 测试：0.4 天。
- 前置：设计文档 02/32（召回基建复用）；记忆接口（`interfaces/memory.py`）已有 `IFourLayerMemory` 契约可扩展。
