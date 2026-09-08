# 设计文档 75 —— 第二十五轮：12 工单优化评审结论与决策归档（治理记录）

> 本文档是**治理记录**，不是功能设计：完整归档「外部评审提出 12 条优化工单 → opencode 逐条可行性分析（基于实际代码核对）→ 用户逐项拍板」的决策链。
> 目的：后续 76~86 号设计文档与全部实施的**唯一 source of truth**——砍了什么、为什么砍、改了什么验收标准、用户定了什么参数，均在本文档留痕。
>
> **项目定位（已确认）**：面试展示导向。每个工单都要产出可讲的证据（指标数字 / 对比表 / ADR）；两周跟踪跑完即停，不做长期运维承诺。
>
> **归档依据**：沿用 `doc/plan/issue_designs/` 系列格式（第 X 轮 header + 分节 + README.md 索引登记）。

---

## 1. 评审输入与结论总表

外部评审提出 12 条优化工单（P0 评测升级 / P1 领域深度 / P2 架构修整 / P3 面试包装）。opencode 逐条对照代码核对后，结论如下：

| 工单 | 原提案 | 评审结论 | 最终处置 |
|------|--------|---------|---------|
| 1 黄金断言评测集 | `evals/` 断言集 + must_have 召回率 / trap 通过率 | ✅ 可行，有现成挂点（`tests/evaluation/fixtures` + `BenchmarkReport` 按维度指标先例） | **采纳 + 修正**：判定器必须可注入（CI 用确定性 mock），否则评测依赖 LLM 循环 → doc 76 |
| 2 NLI 校验器 | `validate_facts` 升级为独立校验器，产品/评测双用 | ✅ 可行，现有 `validate_facts` 仅数值核对（`agent/review_tools.py::count_numeric_conflicts`），升级是自然延伸 | **采纳 + 升级**：双模式 snapshot/refetch + 三态判定（superseded）→ doc 77 |
| 3 LLM Judge 校准 | rubric 1~5 + 人工锚点 + Spearman ≥0.7 | ⚠️ 可行但工期瓶颈在人工锚点（评审低估） | **采纳 + 解除串行瓶颈**：锚点打分搭工单 12 便车，不占独立工期；**用户决定全打**（非抽样）→ doc 83 |
| 4 评测结果版本化 | commit hash 指标快照 + history.jsonl + eval-diff | ✅ 可行，一天活（`BenchmarkReport` 已含全部所需指标） | **采纳** → doc 76 |
| 5 Domain Pack | 6 维度子 Agent 下沉 yaml + 第二领域验证 | ✅ 可行但工作量比看起来大：领域渗漏不止 subagent_registry 三张 dict | **采纳 + 验收升级**：必须同步解耦 `Competitor.category` 默认值 / `COMPETITOR_REGISTRY` / `DIMENSIONS` 三处；验收 = 第二 pack 全链路独立 → doc 79 |
| 6 跑分口径校验 | provenance 字段 + 厂商自报显式标注 | ✅ 可行，`BenchmarkSourceProvider` 抽象已就位；投入产出比最高之一 | **采纳** → doc 80 |
| 7 Dossier 导出 | 基于 TimelineMemory 单竞品完整档案 | ✅ 可行，数据源全部现成（timeline / reports / knowledge_base） | **采纳** → doc 82 |
| 8 拆 facade/api.py | 拆为 assembly / analysis / compare / schedule 四服务 | ✅ 可行，god object 属实（~1700 行），拆分边界清晰 | **采纳** → doc 78 |
| 9 并发模型升级 | DelegateRunner 线程池 → asyncio + 成本压测 | ❌ **砍掉 asyncio 迁移**：① 论据不成立（`total_cost_usd` 已有 `threading.Lock` 原子累计，llm/client.py）；② 全链路同步设计，asyncio 化等于重写引擎层；③ 与工单 8 改动面叠加，回归风险不可接受 | **降级保留**：只做「并发压测 + 成本核算误差 = 0 断言」→ doc 78 |
| 10 无限 ReAct 收敛保障 | 连续无新信息注入收敛提示 + 预算耗尽 partial 产物 | ⚠️ 部分已存在（`analyze_react_report` 已产 partial、`CancelledResult`、BudgetController 三条件终止）；且 `max_steps=None` 是 doc 62 写进代码注释的**刻意决策** | **采纳 + 叙事修正**：不改回有界循环，落「自然收敛 + 停滞检测」，ADR 写演进而非推翻 → doc 81 |
| 11 README 重构 | 30 秒 GIF / 指标表 / 架构图 / ADR 索引 / 竞品对比表 | ✅ 可行，ADR 素材现成（doc 20~74） | **采纳**：三篇 ADR → doc 84/85/86；README 重构为工单 11 实施项 |
| 12 真实使用素材 | 两周真实跟踪 + examples/ 最佳报告 | ✅ 可行，`run_scheduled` + 告警 sink 已实现，纯运营动作 | **采纳 + 立即启动**（时间最不可压缩）→ doc 83 |

**净结果：砍 1（工单 9 的 asyncio 迁移）、修正 3（工单 1 判定器可注入 / 工单 5 验收升级 / 工单 10 叙事改演进）、补充 2（工单 2 三态判定 / 工单 3 锚点搭车）。**

---

## 2. 用户已确认参数（2026-09-08 决策记录）

| 决策点 | 结论 | 影响文档 |
|--------|------|---------|
| 项目定位 | 面试展示 | 全部 |
| LLM Key | 复用 opencode 同款 DeepSeek（`DEEPSEEK_API_KEY`，`LLMClient` 原生读取，零改造；项目启动经 `apply_user_level_environment` 强制用户级 env，规避 doc 74 P0① shell 污染） | 83 |
| 运行环境 | 本机 + `run_scheduled`；机器可能关机 → **错过轮次直接跳过不补跑**（补跑会挤压时间窗干扰 timeline diff），TTL 新鲜度标注天然兜底断档 | 83 |
| 竞品名单 | 国际 5 个（claude-code / cursor / copilot / codex / windsurf）+ 国内 5 个（**trae / workbuddy / zcode / kimi-kcode / deepseek-harness**）；**每轮全量 10 个** | 83 |
| 调度频率 | 每周 2 轮 | 83 |
| 评测门禁 | 新指标**先只记录不卡 CI**，攒到基线数据后再定红线 | 76/77 |
| NLI 产品默认 | 默认 snapshot，`verify(mode="refetch")` 发布前手动调用 | 77 |
| superseded 链路 | 采纳：现实已变 → 自动写 TimelineMemory + 异动告警 | 77 |
| 第二 Domain Pack 领域 | SaaS 项目管理工具（Notion / Linear / Asana） | 79 |
| 黄金断言 3 个固定任务 | 「分析 Cursor」「对比 Claude Code vs Copilot」「追踪 OpenAI Codex 价格/版本变化」（第三个覆盖 trap 类断言） | 76 |
| 断言初稿 | opencode 基于现有知识库草拟，用户只做核实标注 | 76 |
| 工程约定 | **每工单一分支**，PR 合入 main，benchmark 全绿才合 | 全部 |
| 锚点打分量 | **全打**（非抽样）：~20 份/周 × 20 分钟 ≈ 6~7 h/周，用户接受；评分章程（rubric/盲评/理由必填/20% 重测）写入 doc 83 保跨周一致性 | 83 |

---

## 3. 三周执行顺序（含依赖）

```
立即启动：工单 12 两周真实跟踪（run_scheduled + 告警，每周 2 轮 × 全量 10 竞品）

动工前必须先写的设计文档：75（本文档）、76、77、78、83

第 1 周（并行）：
├─ 工单 1  黄金断言集（判定器可注入）                    [doc 76]
├─ 工单 2  NLI 校验器（snapshot/refetch + 三态）          [doc 77]
├─ 工单 4  评测版本化                                     [doc 76]
└─ 工单 8  拆 facade（不按行数均分，Lead 编排闭包随       [doc 78]
            analysis_service 走；benchmark 全绿为验收）
每周锚点：全量报告人工打分（rubric 见 doc 83）

第 2 周：
├─ 工单 6  跑分口径 provenance                            [doc 80]
├─ 工单 5  Domain Pack（含三处解耦，第二 pack 验收）       [doc 79]
├─ 工单 9' 并发压测（半天）                               [doc 78]
└─ 每周锚点打分

第 3 周：
├─ 工单 3  Judge 校准（素材已就绪：两周全量锚点）          [doc 83 章程]
├─ 工单 10 停滞检测 + ADR                                 [doc 81]
├─ 工单 7  Dossier 导出                                   [doc 82]
└─ 工单 11 README 重构 + ADR 精选 + 开源竞品对比表         [doc 84/85/86]
```

**约束**：每工单一条分支；合入前 benchmark 全绿 + ruff/mypy 干净（沿用 CI 现状）。若面试临近只能做一部分，优先级：**工单 1+2（有数字可讲）> 工单 6（有差异化可讲）> 工单 12（有真实运行可讲）> 其余**。

---

## 4. 验证方式（治理层面）

| # | 验收项 | 通过标准 |
|---|--------|---------|
| 4.1 | 决策留痕 | 本文档 + 76~86 全部落盘，README.md 索引登记，状态 📝 待实施 |
| 4.2 | 逐工单验收 | 各自设计文档的验收节（76~86），全部以「pytest 全量 + benchmark 门禁 + ruff/mypy 干净」为底线 |
| 4.3 | 行为不变承诺 | 工单 8 拆分等纯重构以「外部签名逐位不变 + 既有全量测试不改动断言」为验收 |
| 4.4 | 治理闭环 | 每工单完成后回填对应文档状态（📝 待实施 → ✅ 已实现，含 deviation 说明），与本系列惯例一致 |

---

## 5. 实现优先级与工作量

本文档无实现工作。工作量分布在 76~86 各自的「实现优先级与工作量」节；三周排期见 §3。唯一持续投入：两周跟踪期间的锚点打分（用户 ~6~7 h/周，章程见 doc 83）。

---

## 6. 核心技术点总结

1. **评审方法论**：12 条建议不是照单全收——逐条对照代码核实论据后，砍 1 / 修正 3 / 补充 2，全部留痕。这正是「评测驱动 + 保证型代码兜底」项目应有的治理姿态。
2. **最大的一处推翻**：asyncio 迁移被否，理由是「伪需求 + 改动面 + 回归叠加」三连，压测断言保留为唯一真需求。
3. **最大的一处升级**：NLI 三态判定（superseded ≠ 幻觉）把质检组件反向接进时间线/告警链路，一条链路打通工单 2 / 6 / 12。
4. **叙事纪律**：工单 10 被明确要求写成 ADR「演进而非推翻」——与 doc 62 的 `max_steps=None` 刻意决策保持文档一致性，不打自己架构文档的脸。
