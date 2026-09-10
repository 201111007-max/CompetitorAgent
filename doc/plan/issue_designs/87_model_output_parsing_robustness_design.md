# 设计文档 87 —— 第三十七轮：模型输出解析健壮性普查（硬编码/脆弱点清单）与双通道报告漂移治理

> 第三十七轮。目标：基于 2026-09-10 对「模型输出 → 结果文档」全链路的 codegraph 结构扫描，
> 系统记录解析层的硬编码/脆弱点（写死字段假设、文案当协议、旁路未共享主链路健壮化），
> 以及 doc 70 M1 两段式报告（①散文正文 + ②REPORT_SCHEMA JSON）固有的**双通道内容漂移**风险，
> 给出修复方案与优先级。
>
> 本文档为**设计**（暂不实现，仅记录存档）。实现方向以 §3 总体架构、§4 接口设计、§7 实施计划为准。
>
> **归档依据**：沿用 `doc/plan/issue_designs/` 系列既有归档方式（`编号_design.md` 命名、
> 第 X 轮 header blockquote、分节含「问题现状 / 总体架构 / 接口设计 / 配置清单 / 测试验收 /
> 实施计划 / 风险权衡 / 核心技术点总结」、`README.md` 索引登记），格式模板参考 **doc 73/74**。
>
> **状态（2026-09-10）**：待实施，仅记录存档。doc 74 §1.2 已记录「子 Agent 结果无最小成功校验」，
> 本文档 §1.2 是从**解析健壮性**角度对同一区域的补充证据（静默丢数据路径），交叉引用不重复定性。
>
> **修订（2026-09-10，v2）**：用户决策架构演进为**研究员/作家分离**（原 §3.4 M2 可选方案升格为
> 主线方向），落地形态定 **D2：代码骨架 + writer 叙事槽**（非 D1 writer 写全篇）。
> §10 记录该决策下本文档各条目的重估；§1.6/§3.3/§3.4 的原始分析保留作决策依据。
>
> **再修订（2026-09-10，v3）**：B 线（D2 架构本体：N1-N6 修改点、D1/D2 决策记录、
> 架构实施计划）整体迁至 **doc 88**，本文档收敛为**解析层健壮性专题**——
> 保留 §1 问题清单、§3-§4 解析修复方案、§10.1 命运表与 §10.2 工作线 A 实施顺序。

---

## 0. 设计依据：为什么需要一份「解析层普查」设计

doc 65/66 对 Lead Final Answer 主链路做了括号配平 + 轻修复的健壮化（`_extract_json_block` /
`_light_fix_json`），但本次全链路扫描发现：**健壮化只覆盖了主链路，其余三条解析旁路仍停留在
「裸 `json.loads` + 信任返回类型」的旧形态**。同期工作区的 `evaluation/benchmark.py` 在途改动
（plans dict 形态归一、字符串条目跳过、`plugins`/`repo_activity`/`polarity_ratio` 非 dict 防御）
正是真实 LLM 输出漂移在第四条旁路（benchmark 抽取）的实证——说明这不是理论风险，是已在
real 轨实际暴露的问题类别。

**已核实事实（2026-09-10 codegraph 扫描 + 逐文件精读，均读代码不臆测）**：

「模型输出 → 结果文档」共四条解析路径：

```
任务文本 ──► task_parser._parse_task_llm（json.loads 直解）            ← 路径① 未健壮化
Lead Final Answer ──► react_report.assemble
    ├─ _parse_report → _extract_json_block（括号配平 + 字符串感知 + 轻修复） ← 路径② 主链路，已健壮化
    ├─ _dimension_from_item（逐字段防御，confidence 缺省 0.5 / details 非 dict → {}）
    └─ 正文净化（_strip_json_blocks / _dedupe / _close_orphan_fence）
候选子 Agent ──► delegate_tool._collect_candidate（json.loads 直解）     ← 路径③ 未健壮化
    └─► comparison_report.assemble_comparison + _extract_conclusion
benchmark 评测 ──► _plan_price / _benchmark_score / _ecosystem_signal 等   ← 路径④ 在途修复中
```

主链路（路径②）本身是教科书级防御性解析（Postel 原则：宽容解析、兜底响亮），问题集中在旁路。

---

## 1. 问题现状

### 1.1 【P0】路径① task_parser 两处硬假设（task_parser.py:105,108）

- **现象 A**：`json.loads(raw)` 直解（task_parser.py:105）——模型输出带 ```` ```json ```` 围栏或
  散文前缀（"好的，解析结果如下："）→ `JSONDecodeError` → 整条任务抛 `LLMUnavailableError` 失败。
  主链路的 `_extract_json_block` 未在此复用。
- **现象 B**：`data.get("competitors", [])` 假设 list（task_parser.py:108）——模型返回字符串
  `"competitors": "Claude Code"` 时，`[str(c) for c in ...]` **按字符迭代**，产出
  `["C","l","a","u","d","e",...]` 当竞品名——静默垃圾，比报错更糟。同函数内 `dimensions`（L111）
  与 `custom_sources`（L117）都做了 `isinstance` 检查，唯独 `competitors` 漏检。
- **影响**：任务入口级失败或静默垃圾竞品名，下游全链路被污染。

### 1.2 【P0】路径③ _collect_candidate 静默丢数据（delegate_tool.py:422）

- **现象**：`json.loads(rec.result or "")` 要求子 Agent Final Answer 是**裸 JSON**；解析失败
  `return` 静默跳过，**无任何日志**。
- **成因**：doc 65 给 Lead 路径做了散文前缀兼容，候选收集路径未复用；且失败时不记 warning。
- **影响**：子 Agent 输出只要带一句"分析完成，结果如下："，对比矩阵悄没声少一个竞品列——
  链路上唯一的静默丢数据点（与 doc 74 §1.2「无最小成功校验」同区域，互补证据）。

### 1.3 【P1】中文文案当协议：marker 契约三处手工对齐

| 隐性契约 | prompt 侧（生成） | 解析侧（消费） | 漂移后果 |
|---|---|---|---|
| `【市场格局核心结论】` | react_system.py:208；aggregate_tool.py:49 | comparison_report.py:23 `_MARKER` | marker 缺失 → `_extract_conclusion` 退化到「整段正文当结论」，整篇报告被复制追加到矩阵后 |
| `结构化数据` 标题 | react_system.py:215 | react_report.py:173 `_strip_structured_data_section` 正则 | 模型写英文/变体标题 → 机器段标题与散文残留在给人读的正文（JSON 本体有 `_strip_json_blocks` 兜底） |
| `"LLM 服务不可用"/"已达最大"/"推理已停止"` | react_loop.py 错误文案 | react_report.py:439 `_fallback_single_dimension` 字符串包含判定 | react_loop 改一个字 → unavailable 判定静默失效，置信度从 0.1 退化为 0.4（高估） |

- **根因**：把「生成侧文案」与「解析侧字符串匹配」当跨模块协议用，无常量共享、无结构化信号。
  尤其 unavailable 判定——terminal_state 已存在，缺的是结构化 error kind，不该靠中文包含。

### 1.4 【P2】轻微项

- **C1**：`_dimension_from_item`（react_report.py:387）`evidence_urls` 假设 list；模型返回单个
  字符串 URL → 按字符迭代产出 `"h","t","t","p"...` 证据。缺 `isinstance(list)` 归一。
- **C2**：`_looks_like_json_block`（react_report.py:311）5 个判定键（competitor/competitors/
  dimensions/conclusion/kind）与 REPORT_SCHEMA/对比 JSON 键靠人肉同步；schema 加键需记得回改。
- **C3**：维度集合三处重复定义——`_DIMENSION_WEIGHTS`（report_builder.py:16）、
  `react_schemas.DIMENSIONS`（L13）、`task_parser._VALID_DIMENSIONS`（L24）。有 0.1 权重兜底
  不算 bug，但属同源硬编码扩散；新增第 7 个维度需三处同步。
- **C4**：`_parse_report` 兜底键 `("conclusion","summary","answer")`（react_report.py:197）
  属「写死探测模型可能没有的字段」，但语义是可选探测而非必需，文档化充分，可接受。

### 1.5 主链路已做对的（保持不变，作为旁路对齐基准）

- `_extract_json_block` 括号配平 + 字符串字面量感知 + 懒提取兜底（react_report.py:214）；
- `_light_fix_json` 模型手滑轻修复（react_report.py:270）；
- 无证据 URL 的维度置信度封顶 0.5（react_report.py:36,388-390）；
- plan 声明但未产出维度 → `gaps_pending` 对账（react_report.py:96-100）；
- 对比矩阵纯代码渲染（计算权在代码，叙事权在模型——分工正确）。

### 1.6 【P1】双通道报告漂移（doc 70 M1 两段式的固有风险）

- **现象**：模型在同一 Final Answer 里把同一内容写两遍——①散文正文（markdown_report 采用，
  react_report.py:109-110）+ ②REPORT_SCHEMA JSON（dimension_results / 对比矩阵 / benchmark
  评测全部采用）。**两遍可以互相矛盾**：散文写 "$20/月"、JSON 写 30，同一份报告对外两个层面
  不一致，且无任何告警。
- **根因**：双通道各自生成，无单一事实源（single source of truth）。`markdown_report` 信散文，
  数据层信 JSON，无人校验两者一致。
- **业界模式对比**（详见 §2.3）：纯模型写作（Deep Research 式）/ 纯代码渲染（data-to-text 式）/
  研究员-作家分离（JSON 先行，writer 看着 JSON 写正文）/ 双通道混合（本项目）。漂移是双通道
  模式独有的代价。
- **现状缓解**：doc 77 NLI 校验器若覆盖「正文 vs payload 一致性」则缺口关闭；若只校验
  「正文 vs 采集证据」，本缺口仍在。**待核实**（实施前确认 doc 77 作用域）。

---

## 2. 目标与非目标

### 2.1 目标

1. 四条解析路径统一共享主链路的健壮化基建（提取 + 类型归一），消除静默丢数据/静默垃圾；
2. 文案级隐性契约收敛为共享常量或结构化信号，删除中文字符串包含判定；
3. 双通道漂移有告警（轻量校验）或根治（单一事实源），至少做到「不一致可观测」。

### 2.2 非目标

- 不改变主链路（路径②）现有解析语义与黄金断言（doc 76）；
- 不引入新 LLM 调用（writer 后置重写属可选演进 §3.4，需单独决策成本）；
- 不重写 prompt 体系（marker 文案不动，只做常量收敛 + 解析侧容忍变体）。

---

## 3. 总体架构

### 3.1 共享解析基建下移（治 §1.1/§1.2/§1.4-C1）

把 `_extract_json_block` / `_parse_json_candidate` / `_light_fix_json` 从 `facade/react_report.py`
下移到公共层（建议 `core/json_extract.py`，core 层无 facade 依赖，react_report 改 import 保持
向后兼容），并新增类型归一 helper：

```mermaid
flowchart LR
    subgraph core/json_extract（新公共层）
        A[extract_json_block<br/>括号配平+轻修复] 
        B[coerce_str_list<br/>str→单元素 list/None→[]]
    end
    P1[task_parser 路径①] --> A
    P1 --> B
    P3[_collect_candidate 路径③] --> A
    P2[react_report 路径② 主链路] --> A
    P4[benchmark 抽取 路径④] --> B
```

三条旁路统一复用后，「裸 json.loads + 信任类型」形态在全仓库清零。

### 3.2 隐性契约收敛（治 §1.3）

- marker 字符串（`【市场格局核心结论】`、`结构化数据`、结构化段标题）收敛到单一常量模块
  （建议 `agent/react_schemas.py` 或新 `core/report_markers.py`），prompt 侧与解析侧都 import
  同一常量，禁止各自手抄；
- 解析侧对 marker 容忍 markdown heading 变体（`## 【…】` / `## …` 无括号形态）；
- unavailable 判定改结构化信号：react_loop 产出显式 `error_kind`（unavailable/max_steps/stopped），
  随 terminal_state 一并传入 `assemble`，删除 react_report.py:439 的中文字符串包含匹配。

### 3.3 双通道漂移：轻量校验先行（治 §1.6，M1）

不对称校验，零新 LLM 调用：payload 的 `details` 关键数字（价格/榜单分数）出现在散文正文中
才算一致；散文中出现而 payload 缺失的同型数字 → 记 warning + 报告追加「一致性存疑」注记。
比全量 NLI 便宜一个数量级，先做到「不一致可观测」。

### 3.4 双通道漂移：根治演进（可选，M2，需单独成本决策）

演进为「JSON 先行、writer 后置」：Lead 只产 REPORT_SCHEMA JSON → 代码渲染/校验 →
（可选）writer 调用看着已校验 JSON 写正文。收益：单一事实源、正文天然忠于数据；
成本：多一次 LLM 调用 + 正文延迟。**默认不启用**，待 §3.3 校验数据证明漂移频发后再决策。

---

## 4. 接口设计

```python
# core/json_extract.py（新）
def extract_json_block(text: str) -> dict[str, Any] | None:
    """自 react_report._extract_json_block 平移，签名/语义不变。"""

def coerce_str_list(value: object) -> list[str]:
    """None→[]；str→[str]（整体一项，不迭代字符）；list→str 元素过滤空项；其余→[]。"""

# core/task_parser.py（改）
raw_list = coerce_str_list(data.get("competitors"))     # 治 §1.1B
payload = extract_json_block(raw) or raise LLMUnavailableError  # 治 §1.1A

# agent/delegate_tool.py（改）
payload = extract_json_block(rec.result or "")          # 治 §1.2
if payload is None:
    logger.warning("候选子 Agent 结果无法解析，已跳过: %s", rec.name)

# core/report_markers.py（新，治 §1.3）
CONCLUSION_MARKER = "【市场格局核心结论】"
STRUCTURED_DATA_HEADING = "结构化数据"
CONCLUSION_HEADING_RE = re.compile(r"^#{1,6}\s*【?市场格局核心结论】?", re.MULTILINE)

# react_loop → assemble 调用链（治 §1.3 unavailable）
@dataclass
class LoopTerminal:
    state: str            # 沿用 terminal_state
    error_kind: str = ""  # "unavailable" | "max_steps" | "stopped" | ""
```

## 5. 配置清单

无新增配置键。§3.4 writer 后置若启用，建议 `report.writer_pass: bool = false`（默认关），
届时单独评审。

## 6. 测试验收

| 项 | 验收 |
|---|---|
| §1.1B | 单测：`competitors` 返回字符串/None/混合 list 三形态，结果分别为单元素/空/过滤后 list |
| §1.1A | 单测：带 ```` ```json ```` 围栏与散文前缀的解析输出，parse_task 正常返回不抛 |
| §1.2 | 单测：子 Agent 结果带散文前缀 → 候选仍被收集；完全无 JSON → 跳过且有 warning 日志 |
| §1.3 | 单测：marker heading 两种变体均能提取结论；error_kind 驱动置信度（无字符串匹配残留，grep 验证） |
| §3.3 | 单测：正文含 payload 缺失的价格数字 → 报告追加一致性注记；黄金断言（doc 76）零改动通过 |
| 回归 | `pytest` 全绿 + `ruff`/`mypy` CI 通过；黄金报告逐字节不变（doc 76 门禁） |

## 7. 实施计划（建议顺序）

| 序 | 内容 | 量级 | 优先级 |
|---|---|---|---|
| 1 | §1.1 task_parser 两处修复 + 2 单测 | ~15 行 | P0（入口级） |
| 2 | §1.2 _collect_candidate 复用 extract + warning | ~10 行 | P0（唯一静默丢数据点） |
| 3 | core/json_extract 下移 + react_report 改 import（含黄金回归） | 0.5 天 | P0 前置基建 |
| 4 | §1.3 marker 常量收敛 + heading 变体容忍 | 0.5 天 | P1 |
| 5 | §1.3 error_kind 结构化信号（react_loop→assemble 链路） | 0.5-1 天 | P1 |
| 6 | §3.3 双通道一致性轻量校验（先确认 doc 77 作用域） | 1 天 | P1 |
| 7 | §1.4 C1/C2/C3 顺手项 | 随 1-4 附带 | P2 |
| 8 | §3.4 writer 后置根治 | 需成本评审 | 暂缓 |

## 8. 风险权衡

- **黄金回归风险**：`extract_json_block` 下移必须纯平移（签名/语义/行为零变化），落地后立即跑
  doc 76 黄金断言；任何"顺手优化"都禁止混入本次平移。
- **容忍度副作用**：task_parser 改宽容解析后，原本「响亮失败」的畸形输入会静默落到 CHAT 默认
  分支（task_parser.py:119-121 语义）——可接受，这是既有设计决策（doc 64 §5.4），但需在
  warning 日志保留 raw 截断供排查。
- **双通道校验误报**：散文合理改写数字格式（"$20" vs "20 USD"）可能误报——校验只做「数字集合
  包含」粗判并降级为注记，不阻断报告。
- **不做的事**：不追求 schema 全量强制校验（`_validate_schema` 用于工具参数契约，报告解析侧
  维持 Postel 宽容 + 兜底响亮的既有方向）。

## 9. 核心技术点总结

1. **两代解析代码并存是根因**：doc 65/66 的主链路健壮化没有横向辐射到旁路；修复的本质是
   「基建下沉 + 全路径复用」，而非逐点打补丁。
2. **静默失败 > 响亮失败 > 容错**：`_collect_candidate` 的静默跳过是全链路最差形态；
   task_parser 字符迭代次之；修复后统一为「容错解析 + warning 留痕」。
3. **文案不是协议**：凡跨「LLM 生成 ↔ 代码消费」边界的契约，要么结构化（error_kind），
   要么共享常量（marker）；中文字符串包含判定一律视为 bug 苗子。
4. **双通道的代价是漂移**：叙事权在模型、计算权在代码是正确分工，但需要单一事实源或
   一致性校验兜底；业界「研究员-作家分离」是根治方向，轻量校验是务实第一步。

---

## 10. 修订（2026-09-10，v3）：架构演进下的问题重估（D2 设计已迁 doc 88）

**架构决策**（详见 **doc 88**）：报告生成从 doc 70 M1 两段式演进为**研究员/作家分离**，
落地形态 **D2：代码骨架 + writer 叙事槽**——研究员产结构化 JSON → 代码确定性聚合 +
蒸馏事实清单（单一事实源）→ 代码渲染骨架/表格/数字/注记，writer 只填叙事槽
（执行摘要/维度解读/市场格局结论），且只接触蒸馏事实不接触原始 details。
LLM 调用收敛到两个不可代码化的环节：「研究员读网页」与「writer 写解读」。

### 10.1 原条目命运表

| 原条目 | 新架构下状态 | 实施变化 |
|---|---|---|
| §1.1 task_parser（P0） | **不受影响** | 与报告架构无关，修复内容原样保留 |
| §1.2 `_collect_candidate`（P0） | **权重上升** | 研究员 JSON 成唯一事实源，静默丢一个 = 正文/矩阵/评测全部基于残缺数据失真。与 doc 74 §1.2 meaningful-output gate **合并实施** |
| §1.3 `结构化数据` 机器段 | **消解** | Final Answer 不再两段式，`_strip_structured_data_section` 可退役 |
| §1.3 `【市场格局核心结论】` marker | **消解** | 结论改 JSON 字段 + 代码渲染标题（或 writer 结构化输入），字符串契约消失 |
| §1.3 unavailable 字符串判定 | **仍要修，更重要** | 失败点变多（研究员/聚合/writer 三路失败），`error_kind` 是区分降级路径的前提 |
| §1.4 C1 `evidence_urls` 归一 | **升 P1** | writer 引用锚定（doc 88 §4.2/N3）直接依赖 |
| §1.4 C2 `_looks_like_json_block` | 降级 | 正文来自 writer 不含 JSON dump，`_strip_json_blocks` 退为纯兜底 |
| §1.4 C3 维度集合三处重复定义 | **不受影响** | 六维枚举仍是 schema/权重/任务解析三处共享硬编码，与新架构正交；顺手项随基建下移一并收敛 |
| §1.6 双通道漂移 | **结构性根治** | 正文叙事是 JSON 的衍生品；数字/表格代码渲染不经 LLM，两通道矛盾架构上不可能发生 |
| §3.3 一致性校验 | **保留但重新定位、范围缩小** | 从「双通道漂移检测」变为「writer 叙事槽保真度校验」；只需校验叙事槽段落（表格/数字段代码渲染天然可信），设计见 doc 88 §4.2 |
| §3.4 writer 后置 | **升格为主线，形态定 D2** | 原 M2 可选方案成为架构本体；落地为代码骨架 + 叙事槽（决策记录 doc 88 §9.2） |

### 10.2 工作线 A 实施顺序（本文档范围，与 doc 88 解耦可先行）

| 序 | 内容 | 依赖 |
|---|---|---|
| 1 | `core/json_extract` 基建下移（纯平移 + 黄金回归，C3 顺手收敛） | 无 |
| 2 | §1.1 task_parser 修复 | 1 |
| 3 | §1.2 `_collect_candidate` + meaningful-output gate（合并 doc 74 §1.2） | 1 |
| 4 | `error_kind` 结构化信号（react_loop→assemble→writer 降级链） | 无 |

**B 线已迁出**：N1 代码聚合层、N2 叙事槽保真度校验、N3 引用锚定、N4 `writer_pass` 配置、
N5 成本与注入面、N6 SSE 流式、D1/D2 决策记录与架构实施计划，整体见 **doc 88**
（其 §7 将本线第 1-4 步列为前置依赖）。

**风险重申**：第 1 步基建下移必须纯平移（签名/语义/行为零变化），落地后立即跑
doc 76 黄金断言；任何"顺手优化"禁止混入平移 PR。
