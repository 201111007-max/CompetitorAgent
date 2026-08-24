# 竞品分析 Agent — 评测基准设计文档（Benchmark Design)

> 依据 `doc/plan/implementation_plan.md` §3.7「Benchmark 组合参考」与 `competitor_agent/docs/evaluation_guide.md`，设计一套**能力域组合 + 三层分层 + 可复现可归因**的评测基准。
> 核心主张：没有"唯一通用" benchmark；分数必须配版本号（benchmark + subset + harness）；评测必须有 trace 才能归因失败。

---

## 1. 设计目标

1. **可量化**：字段准确率、幻觉率、工具选择准确率、成本效率全部有数字。
2. **可复现**：任一 benchmark 分数可回放（固定 seed / 固定快照 / 固定 harness 环境）。
3. **可归因**：失败能定位到具体模块（采集 / 分析 / 规划 / 校验），而非黑盒"整体不行"。
4. **可信**：指标对齐业界主流基准的语义，可作为公开口径引用，且坦诚标注局限。

---

## 2. 设计原则

| 原则 | 说明 |
|------|------|
| **能力域组合评测** | 不押单一 benchmark，按 Agent 能力域匹配业界基准并映射到本系统模块 |
| **三层分层** | Component（单模块）→ Trajectory（路径）→ End-to-End（任务），逐层定位问题 |
| **分数带版本号** | 每个分数 = benchmark + subset + harness 版本，防止"上个数字误导"（harness 差异可差 10-20 分） |
| **快照标注** | 所有 ground_truth 来自标注时官网快照，存 `sources` 字段供复核，防网站改版误判 |
| **trace 全量落盘** | 每次评测记录工具调用/参数/成本/耗时，失败必须可回放 |
| **回归门禁** | 硬指标不达标（字段准确率 < 90% / 幻觉率 > 5%）阻断合并 |

---

## 3. Benchmark 组合映射

> 本项目是"竞品情报 Agent"，不是通用代码/终端 Agent。下述业界基准不作为外部依赖引入，而是**参照其评测语义**设计本系统的 benchmark 集。

| 能力域 | 参考业界基准 | 评测语义借鉴 | 本系统对应模块/用例 |
|--------|-------------|-------------|-------------------|
| 通用 Agent 能力 | AgentBench（清华，8 环境，ICLR 2024） | 多维任务自主执行打分 | StrategicLoop 目标解析 + 缺口排序（`strategy_cases.json`） |
| Web 操作 / 采集 | WebArena / BrowserGym | 真实网页流程完成度 | WebExtractor / SpaExtractor 采集用例（`accuracy_cases.json`） |
| 工具编排 / MCP | MCP-Atlas（Scale Labs, 2026） | 工具选择 + claim 级打分 | ToolDispatcher / SourceSelector 工具选择（`strategy_cases.json`） |
| 通用助手 / 规划 | GAIA | 多工具、规划、错误恢复 | TacticalLoop 缺口闭环 + 降级链（`strategy_cases.json`） |
| 代码 / 仓库修复 | SWE-bench Pro / Verified（参考） | 非本项目目标，**不引入** | — |
| CLI / 终端操作 | Terminal-Bench 2.0（参考） | 非本项目目标，**不引入** | — |

**引用口径**：本系统不宣称"在 SWE-bench 上取得 X 分"（领域不符），而是说"评测语义参照 MCP-Atlas / WebArena 的按能力域组合做法"，避免误导。

---

## 4. 三层分层评测

对应 `implementation_plan.md` §3.7 的三层，落点到本系统已有代码：

```
┌ End-to-End ── evaluation/accuracy_eval.py + benchmark.py（最终任务完成度）
│    字段准确率 ≥90%  幻觉率 ≤5%  工具选择 ≥85%  成本效率
│
├ Trajectory ── evaluation/strategy_eval.py（执行路径合理性）
│    工具选择准确率 / 命中排名 / 成本效率   ← 每缺口选源是否最优
│    错误恢复路径：解到阻塞→降级链顺序是否正确
│
└ Component ── tests/unit/（单模块正确性）
      collector 解析 / analyzer 判定 / budget 终止 / report 渲染
      （CI 全量跑，覆盖率 ≥94% 已有）
```

**逐层归因**：
- End-to-End 失败 → 先看 Trajectory：工具选对了吗？→ 再 Component：该工具输出对吗？
- 三层均有指标可回放，保证"知道坏在哪一层"。

---

## 5. 用例集设计（fixtures)

> 依据 §3.7「最小 eval 集建议」与 `evaluation_guide.md` §3，按**覆盖类型**而非仅按维度组织。

| 类型 | 数量（MVP） | 说明 | 归属文件 |
|------|------------|------|---------|
| 正常路径 | 10 | 定价/功能/版本 ground truth 精确核对 | `accuracy_cases.json` |
| 边界路径 | 5 | 罕见定价模型、多币种、多语言文档、空缺字段 | `accuracy_cases.json` |
| 工具失败 | 3 | 采集 404 / 反爬 / SPA 需降级 → 验证降级链 | `strategy_cases.json` |
| 安全/拒绝 | 2 | 无证据不臆断、冲突证据被 Validator 拦截 | `accuracy_cases.json` + 冲突用例 |

> 纳入正式评测前扩至 50+ 条并纳入回归；先满足 §3.7「20 条起」的最小集。

**每条 case 字段**（沿用 `evaluation_guide.md` §2）：
```json
{
  "case_id": "cursor_pricing_2026",
  "competitor": "cursor",
  "dimension": "pricing",
  "expected": {...},
  "expected_tool": "pricing_source",
  "sources": [...],
  "tags": ["pricing", "usd", "boundary"]
}
```

---

## 6. 指标口径

| 指标 | 口径 | 目标 | 来源 |
|------|------|------|------|
| 字段准确率 | 抽取正确字段数 / ground truth 字段总数（规范化后 exact-match） | ≥ 90% | `accuracy_eval.py` |
| 幻觉率 | 无证据支撑断言数 / 总断言数（可回溯 SourceEvidence） | ≤ 5% | `accuracy_eval.py` + Validator |
| 工具选择准确率 | 正确选源步数 / 总决策步数 | ≥ 85% | `strategy_eval.py` |
| 成本效率 | 基准成本 / 实际成本 | ≥ 0.85 | `strategy_eval.py` |
| trace 完整率 | 有完整 trace 的 case / 总 case | 100% | 评测 harness |

---

## 7. 评测 harness（考场）

```
tests/evaluation/fixtures/*.json  ──►  Benchmark.run()
                                          ├─ AccuracyEvaluator.evaluate(accuracy_cases)
                                          ├─ StrategyEvaluator.evaluate(strategy_cases)
                                          └─ BenchmarkReport（均值/方差 + 逐 case 明细 + 幻觉实例 + 混淆矩阵）
                                              │
                                              ▼
                              reports/benchmark_<date>.md（含 harness 版本号）
```

- **确定性**：固定 Python + 依赖版本（pyproject）、固定 fixture 快照。
- **归一化**：沿用 `accuracy_eval._normalize()`（货币符号/单位/标点），保证语义友好可比。
- **回放**：评测失败 case 落盘 trace（工具/参数/成本/耗时），可复现定位。

**运行**
```bash
pytest tests/evaluation -v                 # 全量
python -m competitor_agent.evaluation.benchmark --out reports/benchmark.csv
```

---

## 8. 回归门禁

| 门槛 | 触发 | 阻断 |
|------|------|------|
| 核心指标回归 | CI / 手动 evaluation | 字段准确率 < 90% 或 幻觉率 > 5% 阻断合并 |
| 新增采集器 | 新 collector 提交 | 必须附带覆盖该源正/负样本 case |
| trace 回放 | 任何指标异常 | 无 trace 的失败 case 不予合入，先补齐 |

---

## 9. 落地清单（对照已有/待办）

- ✅ `evaluation/accuracy_eval.py`：字段准确率 / F1 / 幻觉率
- ✅ `evaluation/strategy_eval.py`：工具选择 / 命中排名 / 成本效率
- ✅ `evaluation/benchmark.py` + `BenchmarkReport`
- ✅ fixtures：`accuracy_cases.json`（8 条）+ `strategy_cases.json`（6 条）→ 当前合计 14 条
- ⏳ 扩充至边界/工具失败/安全类 ≥20 条（§5 最小集）
- ⏳ trace 全量落盘 + 报告带 harness 版本号（§6/§7）
- ⏳ CI 接入 `pytest tests/evaluation` + 报告归档（.github/workflows/ci.yml 的 M4 已含 pytest --cov，需确认含 evaluation）

---

## 10. 引用与局限（坦诚声明）

- 本系统评测**不是**逐项复现 AgentBench / WebArena / MCP-Atlas 分数，而是**借鉴其能力域划分与按层归因的语义**。
- 所有数字配版本号（fixture 日期 + 依赖版本 + harness 版本），避免"上个数字误导"。
- 官网改版会令 ground truth 过期 → 每 case 存 `sources` 快照，季度刷新，改版即更新并在 commit 说明。