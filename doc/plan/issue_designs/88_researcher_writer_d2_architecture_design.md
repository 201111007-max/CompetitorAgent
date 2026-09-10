# 设计文档 88 —— 第三十八轮：研究员/作家分离架构（D2：代码骨架 + writer 叙事槽）

> 第三十八轮。目标：将报告生成从 doc 70 M1 两段式（Lead 一次产出散文正文 + REPORT_SCHEMA JSON）
> 演进为**研究员/作家分离**架构，落地形态 **D2：代码骨架 + writer 叙事槽**——
> 研究员（维度子 Agent）产结构化 JSON → 代码确定性聚合为 REPORT_SCHEMA payload + 蒸馏事实清单
> （单一事实源）→ 代码渲染骨架/表格/数字/注记，writer 只填叙事槽。
>
> 本文档为**设计**（暂不实现，仅记录存档）。问题重估与解析层配套修复见 **doc 87**
> （v2 起 87 收敛为纯解析层健壮性文档，B 线架构内容整体迁入本文档）。
>
> **归档依据**：沿用 `doc/plan/issue_designs/` 系列既有归档方式（`编号_design.md` 命名、
> 第 X 轮 header blockquote、分节含「问题现状 / 总体架构 / 接口设计 / 配置清单 / 测试验收 /
> 实施计划 / 风险权衡 / 核心技术点总结」、`README.md` 索引登记），格式模板参考 **doc 73/74**。
>
> **状态（2026-09-10）**：**§7 步骤 1-6 已实施**（commit 序列：聚合平移 → 蒸馏层 →
> 等价性切换 → 配置 → 骨架 → writer 接线 → SSE 骨架事件；步骤 7 Lead prompt 两段式退役
> 按原计划留待「3 稳定后」）。核心决策已定（§9 ADR）：
> ① 放弃两段式改单一事实源；② 落地形态 D2 非 D1；③ 聚合层代码确定性合并。
>
> **实施修正两处（与本文档原始表述的差异，以代码为准）**：
> ① `writer_pass=false` 的产物 = legacy `MarkdownRenderer.render()` **逐字节同现状**
> （非 §5/§6 原表述的「新骨架 + 全槽注记」）——保住 doc 76 式字节断言与既有测试零回归；
> writer 整体异常降级 = 保持 assemble 产物（legacy），单槽失败 = 新骨架 + 该槽注记，
> 两形态钉死无第三态（§6 降级验收条已相应修订）。
> ② 蒸馏层落位 `domain_types/distilled.py`（非 §4.1 所写的 `core/report_aggregator` 内）——
> memory/evaluation 两消费点只应依赖 domain_types，放 core 会拉入 observability 依赖并有
> 成环风险；聚合（core）→ 蒸馏（domain_types）方向合法，「三处共用一份蒸馏函数」意图不变，
> 且实际扩为四处（render/exporter/benchmark + timeline_memory 全部切同源）。

---

## 0. 设计依据：为什么从两段式演进

doc 70 M1 两段式让 Lead 在同一 Final Answer 里把同一内容写两遍（散文正文 + REPORT_SCHEMA JSON），
代码拆分后 `markdown_report` 信散文、数据层信 JSON——**两遍可互相矛盾且无告警**
（散文 "$20/月"、JSON 写 30；doc 87 §1.6 实证分析）。为兜住模型自由文本，项目已付出
doc 65（括号配平提取）/ doc 66（畸形 JSON 轻修复）/ doc 73（正文净化三件套）的复杂度，
且净化机器仍在随新的漂移形态膨胀。

根本症结：**两段式没有单一事实源**。本架构的解法不是再加校验，而是改变生成顺序——
先有结构化事实（JSON），正文（叙事部分）是事实的衍生品，两通道矛盾在架构上不可能发生。

业界对照（doc 87 §1.6 / 值分析过程存档）：纯模型写作（Deep Research 式，格式/数字不可控）、
纯代码渲染（data-to-text，prose 僵硬）、研究员/作家分离（STORM、GPT Researcher、
Anthropic multi-agent research，本方向）、双通道混合（现状）。分节写作（outline-first +
逐节生成）为后续升级路径，当前报告体量（2-4 页）属过度工程（§9.4）。

---

## 1. 问题现状（要解决什么）

1. **双通道漂移**（doc 87 §1.6）：散文与 JSON 可矛盾，无单一事实源，无告警。
2. **净化机器膨胀**：`_strip_structured_data_section` / `【市场格局核心结论】` marker /
   `_strip_json_blocks` 等字符串契约三处手工对齐（doc 87 §1.3），模型措辞漂移即失效。
3. **Lead 聚合错误面**：现状 Lead LLM 把子 Agent 结果再聚合为最终 JSON，可能改写/丢失
   研究员的数字（待实证，§8 风险 1）。
4. **解析旁路未健壮化**：`_collect_candidate` 静默丢候选（doc 87 §1.2，P0）——
   本架构下研究员 JSON 是唯一事实源，该问题破坏面从「矩阵少一列」扩大为
   「整份报告系统性失真」。**前置依赖 doc 87 工作线 A 第 1-4 步**（§7）。
5. **SSE 体验**：整篇报告一次性出现，无渐进呈现。

---

## 2. 目标与非目标

### 2.1 目标

- JSON 成为唯一事实源：断言性内容（表格/数字/新鲜度注记/置信度标注）100% 代码渲染；
- LLM 调用收敛到两个不可代码化环节：「研究员读网页」「writer 写解读」；
- writer 幻觉面最小化：只接触蒸馏事实清单，不接触原始 details；
- doc 76 黄金断言大部分保留（骨架确定 + 叙事槽 mock 固定串）；
- SSE：骨架先出、叙事逐槽流入。

### 2.2 非目标

- 不改研究员（维度子 Agent）的采集/分析逻辑与 SUBAGENT_RESULT_SCHEMA 契约；
- 不改对比矩阵渲染（已纯代码，天然符合本架构）；
- 不做分节写作/outline-first（升级路径，§9.4）；
- 不接 API 原生引用（Anthropic citations，当前端点不可用，§9.4）。

---

## 3. 总体架构

```mermaid
flowchart TD
    subgraph 研究员层（现状保留）
        R1[维度子 Agent pricing] --> J1[_DIMENSION_RESULT_ITEM JSON]
        R2[维度子 Agent feature] --> J2[...]
        R6[维度子 Agent roadmap] --> J6[...]
    end
    subgraph 聚合层（新，纯代码，N1）
        AG[确定性合并 dimensions[]<br/>+ planned/produced 对账<br/>+ 置信度封顶/冲突检测 沿用] 
        DF[蒸馏事实清单 DistilledFacts<br/>writer 唯一输入]
    end
    subgraph 渲染层（代码骨架，扩展 MarkdownRenderer）
        SK[骨架渲染：标题/维度表格/价格表/<br/>新鲜度注记/置信度标注/时间线]
    end
    subgraph writer 层（新，LLM，report.writer_pass 开关）
        W[叙事槽填充：executive_summary /<br/>dimension_insight×n / market_conclusion]
    end
    J1 & J2 & J6 --> AG
    AG -->|REPORT_SCHEMA payload| SK
    AG --> DF
    DF -->|wrap_untrusted 包裹| W
    W -->|槽位 prose + N2 校验| INJ[槽位注入]
    SK --> INJ --> MD[markdown_report]
    W -.失败/校验不过.-> FB[槽位置「解读暂缺」注记<br/>骨架照常落盘]
    W -->|逐槽| SSE[text_delta 流式]
```

**权威切分**（架构判据：LLM 不得越权管事实/结构/引用）：

| 信息类型 | 权威 | 实现 |
|---|---|---|
| 事实/数字 | 代码 | 聚合层合并 + 骨架表格渲染 |
| 结构/格式 | 代码 | 骨架模板 + 槽位契约 |
| 叙事/综合 | 模型 | writer 三个槽位（唯一 LLM 叙事环节） |
| 引用/出处 | 代码 | writer 标占位、代码后处理锚定 URL（N3） |

---

## 4. 接口设计

### 4.1 聚合层（N1，纯代码）

> 实施落位（修正②）：聚合层 = `core/report_aggregator.py`（`aggregate_researcher_results`），
> 蒸馏层 = `domain_types/distilled.py`（三层：第 0 层命名空间归一原语供
> benchmark/exporter/timeline_memory 直接消费、第 1 层 facts 视图供 writer/N2、
> 第 2 层查询 helper）。`DistilledFact` 实际字段为
> `term/label/value/unit/numeric/evidence_urls`（frozen dataclass + tuple）。

```python
# core/report_aggregator.py（新）
@dataclass
class DistilledFact:
    label: str            # "Pro 档价格"
    value: str            # "20"
    unit: str = ""        # "USD/month"
    as_of: str = ""       # 证据 access_time 日期
    evidence_urls: list[str] = field(default_factory=list)

@dataclass
class DimensionFacts:
    dimension: str
    confidence: float
    facts: list[DistilledFact]          # 从 details 命名空间蒸馏（plans/benchmarks/…）
    evidence_urls: list[str]

def aggregate_researcher_results(
    items: list[dict[str, Any]],        # 各研究员 _DIMENSION_RESULT_ITEM
    loop_plan: dict[str, Any] | None,
) -> tuple[list[DimensionResult], list[DimensionFacts], list[InfoGap]]:
    """代码确定性合并：_dimension_from_item 逐条解析（沿用置信度封顶）→
    planned/produced 对账（沿用）→ 同步蒸馏事实清单。无 LLM 调用。"""
```

要点：合并逻辑即现状 `assemble()` 里 `_dimension_from_item` 循环 + gaps 对账的**平移**，
消灭 Lead LLM 再聚合环节；蒸馏规则按 details 命名空间（plans/features/benchmarks/…）
逐维度写死映射（与 `report_exporter`/`benchmark` 抽取同源，三处共用一份蒸馏函数，
避免 doc 87 §1.4-C3 式重复）。

### 4.2 叙事槽契约（D2 核心）

```python
# agent/writer_slots.py（新）
SLOT_IDS = ["executive_summary", "market_conclusion"]  # + f"dimension_insight:{dim}"

@dataclass
class NarrativeSlot:
    slot_id: str
    heading: str                 # 代码渲染的槽位标题（骨架组成部分）
    input_facts: list[DimensionFacts]  # 该槽可见的蒸馏事实（executive/conclusion=全部，
                                       # dimension_insight=单维）
    mock_text: str = ""          # mock/CI 固定串（writer_pass=false 或 mock LLM 时注入）

def build_writer_messages(slot: NarrativeSlot) -> list[dict[str, str]]:
    """prompt = 槽位指令 + wrap_untrusted(json.dumps(input_facts))；禁写 URL/数字外事实。"""

def validate_slot_prose(slot: NarrativeSlot, prose: str) -> list[str]:
    """N2 保真度校验：prose 中关键数字 ⊆ slot.input_facts 数值集合；返回违规列表。"""
```

三个槽：执行摘要（全量事实）、维度解读×n（单维事实）、市场格局结论（全量事实）。
槽位标题由骨架渲染（代码），writer 只产段落 prose。

### 4.3 骨架渲染与槽位注入

```python
# core/markdown_renderer.py（扩展）
def render_skeleton(report: CompetitorReport, slots: list[NarrativeSlot]) -> str:
    """渲染标题/新鲜度注记/维度表格/价格表/置信度标注/时间线（现状逻辑平移），
    叙事槽位留 {{slot:slot_id}} 占位；show_gaps 语义不变。"""

def inject_slots(skeleton: str, prose_by_slot: dict[str, str]) -> str:
    """槽位注入；缺失槽 → 「（本维度解读暂缺）」注记（N4 降级），骨架照常产出。"""
```

### 4.4 编排接线（facade/api.py）

`_react_competitor` 收尾改为：`assemble`（研究员 JSON 聚合，不再解析 Lead 两段式）→
骨架渲染 → `writer_pass` 开 → 逐槽 `llm.complete_with_tools(stream_sink=…)`（复用
doc 64 text_delta 通道，N6）→ N2 校验 → 注入落盘；Lead 循环保留规划/委派/对话职责，
其 Final Answer 不再需要两段式（prompt 侧 doc 72/70 M1 段落退役，§7 第 8 步）。

## 5. 配置清单

| 键 | 默认 | 说明 |
|---|---|---|
| `report.writer_pass` | `false` | writer 叙事槽总开关；false = legacy `render()` 逐字节同现状（mock/CI/黄金断言确定路径，修正①） |
| `report.writer_slot_max_retries` | `1` | N2 校验不过的单槽重试次数，仍败 → 槽位注记降级 |

无其他新键；成本走既有 cost_limit 护栏（writer 约占单轮总成本 5-10%，doc 87 §10.2-N5）。

## 6. 测试验收

| 项 | 验收 |
|---|---|
| 聚合层 | 单测：多研究员 JSON 合并顺序确定、置信度封顶沿用、planned 未产出 → gaps；蒸馏事实与 `report_exporter`/`benchmark` 抽取同源（同输入三者输出一致） |
| 槽位契约 | 单测：三槽 input_facts 切分正确；mock 固定串注入后骨架逐字节确定（doc 76 适配后零回归） |
| N2 校验 | 单测：槽 prose 含清单外数字 → 违规；重试仍败 → 注记降级且骨架/他槽不受影响 |
| N3 引用 | 单测：prose 占位 → 代码锚定 URL 正确替换；prose 自写 URL → 校验剔除 |
| 降级 | 两形态钉死（修正①）：writer 整体异常 → 不动 report（保持 assemble 产物 = legacy render）；单槽异常/N2 两败 → 新骨架 + 该槽注记，他槽/骨架不受影响；无第三态 |
| SSE | 集成：骨架事件先于槽 text_delta；槽间顺序稳定 |
| 回归 | pytest 全绿 + ruff/mypy；`writer_pass=false` 黄金断言（doc 76）零改动 |

## 7. 实施计划

| 序 | 内容 | 依赖 |
|---|---|---|
| 0 | **前置：doc 87 工作线 A 第 1-4 步**（基建下移 / task_parser / `_collect_candidate`+gate / error_kind） | — |
| 1 | `core/report_aggregator`：确定性合并 + 蒸馏事实清单（含与 exporter/benchmark 共用蒸馏函数） | 0 |
| 2 | 骨架渲染扩展 + 槽位占位/注入 + mock 固定串（`writer_pass=false` 全链路确定） | 1 |
| 3 | writer pass（prompt + `wrap_untrusted` + 逐槽 SSE） | 2 |
| 4 | N2 保真度校验 + 槽位重试/降级 | 3 |
| 5 | N3 引用锚定后处理 | 3 |
| 6 | doc 76 黄金断言适配（mock 固定串）+ 真实轨报告断言策略切换（骨架段字节断言 + 叙事段走 N2/doc 83 锚点评分） | 2 |
| 7 | Lead prompt 两段式段落退役 + `_strip_structured_data_section`/marker 字符串契约删除 | 3 稳定后 |

## 8. 风险权衡

1. **Lead 聚合错误面（待实证）**：N1 推荐代码合并的依据是"LLM 再聚合可能改写数字"；
   实施前查 `~/.competitor_agent/logs` 真实轨 llm.call 记录找实证，写入 §9 ADR 增强说服力；
   若无实证，代码合并仍为更优默认（少一个 LLM 环节少一类错误）。
2. **叙事连贯性**：D2 段落间呼应弱于 D1 全篇写作——竞品报告以信息密度为先，可接受；
   连贯性成主要扣分项（doc 83 锚点数据）时触发 §9.4 升级评估。
3. **蒸馏丢信息**：蒸馏事实清单是 details 的子集，writer 看不到原始网页细节 →
   解读可能偏浅。缓解：蒸馏规则覆盖报告表格同款字段 + 每事实带 evidence_urls 供
   writer 理解语境；宁浅勿假（幻觉的代价 > 浅薄的代价）。
4. **双引擎对照**（doc 51/86）：langgraph 引擎共用聚合层/渲染层，writer 挂在 facade 收尾
   而非引擎内，双引擎行为一致，不破坏对照实验语义。
5. **黄金断言适配窗口**：第 6 步前真实轨正文断言需临时放宽，CI 门禁策略需明确
   （骨架段保持字节断言），防止窗口期质量裸奔。

## 9. ADR：关键决策记录

### 9.1 放弃 doc 70 M1 两段式，改单一事实源

- **决策**：报告正文（叙事部分）不再由 Lead 与 JSON 同答产出；JSON 先行，叙事衍生。
- **理由**：两段式无单一事实源，漂移不可避免且净化机器持续膨胀（doc 65/66/73 复杂度即代价）；
  衍生式生成使两通道矛盾在架构上不可能发生。
- **保留**：REPORT_SCHEMA 机器路径（对比矩阵/导出/benchmark 抽取）不受影响；
  `report.lead_formatted_body` 开关随两段式退役（由 `report.writer_pass` 取代）。
- **代价**：+1 次 LLM 调用（5-10% 单轮成本）；Lead prompt 与 doc 72/70 M1 相关段落需修订。

### 9.2 落地形态 D2（代码骨架 + 叙事槽），否 D1（writer 写全篇）

六维对比与完整决策理由见 doc 87 §10.4（幻觉面/黄金断言/连贯性/成本/格式一致性/叙事价值）。
核心：本项目报告价值在数字可信度，D1 废 doc 76 字节级断言不可接受；D2 让断言性内容
完全不经 LLM 手。

### 9.3 聚合层代码确定性合并，否 Lead LLM 再聚合

研究员产出即 `_DIMENSION_RESULT_ITEM`，合并是纯数据操作，引入 LLM 只增加错误面
（改写/丢失数字）不增加价值；LLM 叙事职责已由 writer 槽位承担（市场格局结论槽）。

### 9.4 暂缓项与升级触发条件

- **分节写作**（STORM/GPT Researcher 式 outline-first + 逐节生成/重试）：报告 >5 页或
  doc 83 锚点评分显示连贯性为主要扣分项时评估；
- **API 原生引用**（Anthropic citations 等）：当前端点 DeepSeek/OpenAI 兼容不可用，
  换端点时评估收编 N3（接入前以官方文档核实为准）；
- **对比报告 writer 化**：对比矩阵已纯代码，结论槽可复用单竞品 market_conclusion 机制，
  待单竞品路径稳定后推广，不在本期。

## 10. 核心技术点总结

1. **单一事实源优于一致性校验**：校验让漂移"可观测"，衍生式生成让漂移"不可能"——
   架构消问题优于流程兜问题。
2. **权威切分是 Agent 报告系统的第一性设计**：事实/结构归代码，叙事归模型，引用归代码
   锚定；评判任何生成方案看 LLM 是否越权。
3. **蒸馏事实是幻觉防火墙**：writer 输入做减法的收益大于做加法——接触面越小，
  校验越容易、幻觉载体越少。
4. **降级路径即架构的一部分**：`writer_pass=false` 不只是配置，是 CI 确定性、
   writer 失败兜底、灰度切换三位一体的设计。
