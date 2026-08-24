# 设计文档 58 — L2/L3/L4 记忆读侧接线（业内分层组合：L4 喂决策 + L2 常驻 + L3 技能）

> 触发：2026-08-24 复核记忆读侧——L1 会话归档已读写闭环（`recent_context` 注入，api.py:789），
> **L2/L3/L4 全仓库零读取方**（`retrieve_notes`/`retrieve_skills`/`retrieve_patterns_with_outcome`/
> `failure_patterns_for`/`source_success_rates`/`top_sources` 仅接口声明，无消费调用）；
> L2 `save_note` 连写入方都没有（死层），L3 `record_skill`(api.py:1013)/`record_success`(:998) 与
> L4 `record_outcome`(:1016)/`note_pattern`(:1018) 只写不读。doc 45 原接线的 L4 消费被 doc 49
> （Lead Agent 编排替换固定流水线）移除。用户拍板采用**业内分层组合**：
> L4 反思喂决策 + L2 常驻注入 + L3 top-N 技能注入；**memory_recall 工具（MemGPT 式）暂不做**。
> 前置：35（四层记忆）、45（记忆循环写侧）、49（Lead Agent）、52（L1 向量化）。

## 1. 问题现状

### 1.1 四层记忆读写矩阵（核实后）

| 层 | 写入 | 读取 | 状态 |
|---|---|---|---|
| L1 SessionArchive | `archive_session`（api.py:376/1126） | `recent_context`（`_memory_ctx_for`:794 注入） | ✅ 读写闭环 |
| L2 PersistentNotes | `save_note` **无调用方** | `retrieve_notes` 无调用方 | ❌ 死层 |
| L3 SkillStore | `record_skill`(api.py:1013) / `record_success`(:998) | `retrieve_skills` 无调用方 | ⚠️ 只写不读 |
| L4 EvolutionMemory | `record_outcome`(api.py:1016) / `note_pattern`(:1018) | `retrieve_patterns_with_outcome` 等无调用方 | ⚠️ 只写不读 |

### 1.2 三个具体问题

1. **多层记忆名不副实**：系统在 `record_skill`/`record_outcome`/`note_pattern` 持续写入，但分析路径从不读取——
   "多层记忆会自我进化"是宣称能力与实际接线不符（doc 45 接线被 doc 49 移除后的残留）。
2. **L2 是彻底死代码**：`save_note` 无任何调用方，`PersistentNotes` 层建而不用。
3. **决策不进化**：L4 积累了"哪个源失败过、哪个维度上次降级"，但这些经验不进规划/源选择决策，
   记忆的价值闭环断裂。

### 1.3 现有可复用资产

| 资产 | 位置 | 复用方式 |
|---|---|---|
| 唯一记忆注入点 | `_memory_ctx_for`（api.py:789）——双引擎 Lead/子 Agent 全经它 | L2/L3/L4 段追加在此 |
| L4 数据现成 | `note_pattern`/`record_outcome` 持续写入 | `retrieve_patterns_with_outcome` / `failure_patterns_for` 直读 |
| L3 结构 | `Skill`（interfaces/context.py:62：source/success/weight/method） | 按 `weight` 取 top-N 注入 |
| 降级纪律 | `_memory_ctx_for` try/except 静默降级 | 各层同纪律，不炸流水线 |

## 2. 目标设计（业内分层范式映射）

| 层 | 性质 | 业内范式 | 接线 |
|---|---|---|---|
| L1 会话归档 | 历史摘要，体量大 | episodic / 自动注入 | 现状不动 |
| L2 持久笔记 | 人工要点，量小 | core / pinned | **常驻注入** + 补写入方 |
| L3 技能沉淀 | 程序性知识 | procedural | **top-N 按 weight 注入** |
| L4 进化记忆 | 成功率+反例，可统计 | reflection → 决策 | **自动喂决策**：源失败排后 + 维度经验注入 |

- **L4 喂决策**（核心价值闭环）：`failure_patterns_for`（失败源排后）+ `retrieve_patterns_with_outcome`
  （维度经验，subagent 级）注入 → Lead/子 Agent 规划时感知 → 结果回写 `record_outcome`/`note_pattern`，
  记忆→决策→结果→记忆闭合。这是 Generative Agents / doc 45 原意的恢复。
- **L2 常驻注入 + 补写入**：笔记量小（≤3 条）直接进记忆上下文；同时补一个写入方（分析后自动沉淀关键结论），
  否则注入的是空。
- **L3 top-N 技能**：按 `weight` 降序取 ≤3 条注入（source + method），让"哪个源有效、成功做法是什么"进决策。
- **不做 memory_recall 工具**：L2/L3 数据量小、L4 是短条目，为它们建按需检索工具是过度设计；
  等任一层数据量涨大再按 kb_recall（doc 56）同构补。

## 3. 模块/接口设计

### 3.1 唯一注入点扩展（`facade/api.py` `_memory_ctx_for`，~25 行增量）

```python
def _memory_ctx_for(self, competitor: str, task: str, dimension: str = "") -> str:
    """L1 会话 + L4 经验 + L2 笔记 + L3 技能（业内组合）。失败静默降级，各层空则跳过。"""
    if self._memory is None or not competitor or competitor == "unknown":
        return ""
    parts = []
    try:
        l1 = self._memory.recent_context(competitor, top_k=3, query=task)      # 现状
        parts.append("\n".join(l1)) if l1 else None
    except Exception:
        logger.warning("L1 召回失败: %s", competitor, exc_info=True)
    # L4-A 源失败排后（lead 级，无维度）：让规划避开历史失败源
    try:
        bad = self._memory.failure_patterns_for(competitor)
        if bad:
            parts.append(f"历史失败数据源（优先避开）：{', '.join(bad)}")
    except Exception:
        pass
    # L4-B 维度经验（subagent 级，有维度）：经验/反例含 outcome
    if dimension:
        try:
            pats = self._memory.retrieve_patterns_with_outcome(competitor, dimension)
            if pats:
                parts.append(f"{dimension} 维度历史经验："
                             + "；".join(f"{p}({o})" for p, o in pats[:3]))
        except Exception:
            pass
    # L2 长期要点（常驻，量小）
    try:
        notes = self._memory.retrieve_notes(competitor)
        if notes:
            parts.append("长期要点：" + "；".join(notes[:3]))
    except Exception:
        pass
    # L3 技能 top-N（按 weight，source+method）
    try:
        skills = sorted(self._memory.retrieve_skills(competitor),
                        key=lambda s: s.weight, reverse=True)[:3]
        if skills:
            parts.append("历史有效来源：" + "；".join(
                f"{s.source_name}({s.method or '有效'})" for s in skills))
    except Exception:
        pass
    return "\n".join(parts)
```

### 3.2 子 Agent 透传维度（`facade/api.py` :591/:677）

- `_subagent_run(name, sub_task)` 与另一子 Agent 构建处：`memory_context_fn=lambda t: self._memory_ctx_for(lead_competitor.name, t, dimension=name)`
  （子 Agent `name` 即维度，如 `pricing`/`feature`）。
- Lead（:621/:737 经 `_react_memory_context`）：不传维度 → 只走 L1/L4-A/L2/L3（全局层）。

### 3.3 L2 写入方（`facade/api.py`，~10 行）

- 分析完成后（`_record_memory_success` 之后，:295 附近）追加 `_persist_session_notes(report)`：
  从 `report.dimension_results` 取 summary 非空且 confidence ≥ 阈值（如 0.7）的关键结论，
  `save_note(competitor, "维度: 结论")`，每会话每竞品至多 1 条（去重）。
- 可选（M2）：CLI `note save <competitor> "<文本>"` 手动入口（`cli.py`）。

### 3.4 配置

- 无新 yaml 字段；各层 top_k 用模块常量（`_MEMORY_INJECT_TOPK = 3`）。`memory=None`（`enable_memory=False`）时
  整函数短路返回空——与现状一致，消融开关（doc 30）不受影响。

## 4. 接入方式

```
_memory_ctx_for（双引擎唯一注入点）
  ├─ L1 recent_context（现状，不动）
  ├─ L4-A failure_patterns_for ──► Lead 规划避开历史失败源（决策反馈）
  ├─ L4-B retrieve_patterns_with_outcome ──► 子 Agent 维度经验（subagent name 透传 dimension）
  ├─ L2 retrieve_notes ──► 常驻要点（量小）
  └─ L3 retrieve_skills top-N ──► 有效来源+成功做法
L2 写入方：分析后 _persist_session_notes（+ 可选 CLI note save）
```

- 空记忆/异常 → 该段跳过或返回空串，与现状一致（记忆召回本就是可选增强）。
- 回退：删各段即完全回退到仅 L1。

## 5. 验证方式

- **单测**（mock 记忆夹具）：注入 L2/L3/L4 假数据 → 断言 `_memory_ctx_for` 输出含四段、格式正确、
  subagent 维度透传生效（L4-B 按维度过滤）；空记忆 → 与现状逐字节一致；`memory=None` → 空串短路；
  各层异常 → 静默跳过不炸。
- **集成**：`test_memory_loop_45.py` 等既有用例不回归（L1 输出不变）；分析任务跑通且记忆上下文含 L4 段。
- **L2 写入**：分析后断言 note 落盘（置信度高结论入笔记、去重生效）。
- **回归**：全量 `pytest -q` + ruff/mypy；消融 no-memory 变体行为不变。

## 6. 实现优先级与工作量

| # | 里程碑 | 产出 | 工作量 |
|---|--------|------|--------|
| 0 | 设计文档 + 索引登记 | 本文档 + README 登记 | 0.2d ✅ 2026-08-24 |
| 1 | 注入接线 | `_memory_ctx_for` 四段 + subagent dimension 透传 + 单测 | 0.4d |
| 2 | L2 写入方 | `_persist_session_notes` + CLI `note save`（可选） + 单测 | 0.2d |
| 3 | 验证收口 | 集成回归 + 空数据短路断言 | 0.2d |

- 前置：35/45/49（写侧已就绪，读侧接线即可）；与 57/59/60 并行。
- 文档同步：doc 52 §2.4「不改 L2/L3/L4 记忆层（读侧无消费者是 doc 49 后的已知状态）」一句改为"读侧接线见 doc 58"。

## 7. 风险与缓解

1. **prompt 膨胀**：四段叠加可能挤占上下文。缓解：各层 top_k=3、空数据短路、`memory=None` 整体短路。
2. **L4 短文本噪音**（pattern 是单句）：格式化为一行一条 + 带 outcome，量少可控。
3. **L3 注入顺序语义**：按 `weight` 排序——`weight` 目前语义（是否随 `record_success` 累积）需在实现时核对
   `skill_store.record_success`；若 weight 恒 0 则退回按记录顺序注入（设计内降级）。
4. **L4 决策反馈无硬编码保证**：注入是 prompt 引导（LLM 感知），不是硬规则强制源排后。若实测 LLM 不采纳，
   后续可加 make_plan 硬编码降权（列为远期，本文档不引入）。
5. **L2 自动写入噪音**：阈值 confidence ≥ 0.7 + 每会话至多 1 条，控制笔记质量。
