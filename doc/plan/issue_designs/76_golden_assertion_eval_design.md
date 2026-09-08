# 设计文档 76 —— 第二十六轮：黄金断言评测集 + 评测指标版本化（工单 1 + 4）

> **实施说明（2026-09-09，M1/M2 全落地）**：
> ① **M1 黄金断言**（新 `evaluation/golden.py`）：`GoldenVerdict` 五态 + `GoldenJudge` 协议 + `KeywordGoldenJudge`（mock/CI 默认：拉丁词元精确包含 + **CJK 连续段 bigram 匹配**（≥2 字公共子串容忍改写；tokenize 口径下连续汉字为单一 run，整串匹配不可用——实施期发现并修正设计的隐含假设）+ 产品名/别名经注册表动态剔除 + must_have 命中率 ≥0.6 且 ≥2 单元（单单元命中即 covered）、trap ≥2 单元命中才 tripped 防单 hit 误报如报告合理提到 "Anthropic"）+ `LLMGoldenJudge`（json verdict 解析、解析/调用失败保守缺省不误判）+ `build_golden_judge`（mock→Keyword / real→LLM）+ `load_golden_tasks`（verified_date 空/非法/>90 天 → stale_note 仅提醒不失败）+ `GoldenEvaluator`（固定任务经 `api.run()` 真实生成报告 → 逐条判定 → per_task 聚合；单任务失败不影响其余）。`Benchmark.__init__` 加 `golden_judge/golden_dir/use_golden_cache`，`run()` 末尾 `_run_golden()`（**进程级缓存**：mock 确定性下同 (dir,mode,llm) 重跑逐位一致，省 gate 测试重复 3×api.run；预算中止跳过；golden 成本并入 total_cost）；CSV/Markdown 增 golden 节 + stale 提醒；HARNESS_VERSION **0.11.0→0.12.0**；门禁不卡（--gate 只打印摘要，用户决策 ④）。
> ② **M2 版本化**（新 `evaluation/history.py`）：`git_head` / `snapshot`（ts/commit/harness_version/llm_mode/**tag 口径**/n_cases + 纯数字 metrics 含 must_have_recall/trap_pass_rate/`judge_spearman: null` 占位）+ `append_history`/`load_history` + `diff`（latest / latest/N / commit 前缀定位 → ± Δ 表）。CLI：`benchmark --snapshot` 透传 + 新 `eval-diff <from> <to>` 子命令（main() 内 API 构造前短路）。
> ③ **断言集**（`evals/golden/`）：3 任务 × 30 条落盘（analyze_cursor / compare_claude_code_vs_copilot / track_codex_changes，trap 密度按要求 task3 最高）；**verified_date 留空待用户逐条核实**（核实前 stale 提醒按设计打印，跑不失败）——人工核实环节待用户执行。`evals/history.jsonl` 首快照已入库（mock --tag normal）。
> ④ **测试**：`test_golden.py` 24（Keyword 确定性/单 hit 防误报/LLM 解析与保守缺省/注入/stale 三态/评测聚合/任务失败隔离/benchmark 接线/**mock 连跑 3 次逐位一致**/缓存命中）+ `test_history.py` 15（快照/roundtrip/diff 定位与越界/空历史）。tests/evaluation 全量绿（gate 13 / integration 10 / behavior+skill 29 / failure 19 / extract 27 / real+ablation 29）——§4 验收 4.2/4.3/4.4/4.5/4.6 达成，4.1 达成（≥30 条 ×3，verified_date 待用户回填）。

> 目标：把评测从「能跑」做到「有说服力」的第一次落地——
> ① **黄金断言评测集**：3 个固定任务 × 每任务 30~50 条人工核实断言（must_have / trap 两型），新增 `must_have 召回率` 与 `trap 通过率` 两个指标，判定器**可注入**（CI 用确定性 mock，real 模式才走 LLM）；
> ② **评测指标版本化**：benchmark 每次运行产出带 commit hash 的指标快照，追加 `evals/history.jsonl`，提供 `eval-diff` 对比任意两版。
>
> 本文档为**设计**（不实现）。
>
> **归档依据**：`doc/plan/issue_designs/` 系列格式；决策来源 doc 75 §1 工单 1/4、§2 用户决策。
>
> **已确认决策（doc 75 §2）**：
> ① 3 个固定任务：「分析 Cursor」「对比 Claude Code vs Copilot」「追踪 OpenAI Codex 价格/版本变化」；
> ② 断言初稿由 opencode 基于现有知识库草拟，用户只做核实标注（含 `verified_date`，按季度过期提醒）；
> ③ 判定器可注入为**硬性要求**：must_have 召回率用 LLM 判定会引入「评测依赖 LLM」循环，mock 模式跑不了——接口参照 `BenchmarkMockLLM` 注入模式，CI 用确定性 mock；
> ④ 新指标**先只记录不卡 CI**（用户决策），攒到基线后再定红线。

---

## 1. 问题现状

### 1.1 现有评测资产（真实形态，均已核对）

```
competitor_agent/evaluation/benchmark.py
  FIXTURES_DIR = tests/evaluation/fixtures        # accuracy_cases.json / strategy_cases.json
  AccuracyCase(task, competitor, dimension, ground_truth, case_id, tags, mode, page, fail_urls)
  BenchmarkReport(accuracy, strategy, n_cases, trace_completeness, confusion_matrix,
                  accuracy_by_dimension, hallucination_by_dimension,   # ← 按维度拆分指标的先例
                  failure_stats, failure_records, llm_mode, cost_usd,
                  per_case_cost, cost_limit_usd, budget_aborted, behavior)
  build_benchmark_api(case, llm_mode=mock|real, enable_rag, enable_memory, engine, ...)
  BenchmarkMockLLM      # 确定性 mock：LLM 版接口上固定返回（doc 47 范式）
  AccuracyEvaluator / StrategyEvaluator / RecoveryEvaluator / RetrievalEvaluator / FoldRecallEvaluator
  benchmark --gate      # doc 55 门禁：指标退化 CI 变红
```

### 1.2 缺口

| 缺口 | 说明 |
|------|------|
| 无「断言级」召回指标 | 现有 `ground_truth` 是字段级真值（field_accuracy），不是「报告必须覆盖哪些结论」的召回口径——面试官问「你的评测能证明报告没漏关键结论吗」时无数字可答 |
| 无易过时信息陷阱 | 收购、价格变动类信息（trap）没有专门的错误率度量，时效性风险不可见 |
| 指标无历史 | benchmark 跑完即丢，无版本间对比；「这次改动让幻觉率降了 X%」讲不出证据链 |
| fixture 目录承担人工维护区职能 | `tests/evaluation/fixtures` 由代码资产惯例管理；黄金断言是**人工高频核实区**（季度过期），混放会互相干扰 |

---

## 2. 目标设计

### 2.1 目录与文件格式

```
evals/                                  # 仓库根新增（人工维护区，与代码资产解耦——刻意偏离 FIXTURES_DIR 惯例）
├── golden/
│   ├── analyze_cursor.yaml             # 任务 1：分析 Cursor
│   ├── compare_claude_code_vs_copilot.yaml   # 任务 2：对比（断言含 per_competitor 前缀）
│   └── track_codex_changes.yaml        # 任务 3：追踪（trap 密度最高）
├── history.jsonl                       # 版本化快照（追加写，纳入 git）
└── README.md                           # 断言核实流程说明
```

单文件格式（YAML）：

```yaml
task: "分析 Cursor"
task_id: analyze_cursor
verified_date: "2026-09-15"        # 人工核实日期；每季度过期提醒（见 §2.4）
assertions:
  - id: cursor-pricing-free-tier
    claim: "Cursor 提供免费档（hobby），限制在补全次数。"
    type: must_have                 # must_have = 报告应覆盖的正确结论
    source_of_truth: "https://www.cursor.com/pricing"
    tags: [pricing]
  - id: cursor-trap-acquisition
    claim: "Cursor 于 2025 年被 Anthropic 收购。"   # 示例：故意易过时/易混淆
    type: trap                      # trap = 报告**不得**复述的错误或易过时信息
    source_of_truth: "官方无此事件"
    tags: [ownership]
  # ... 每任务 30~50 条
```

**断言产出流程**：opencode 从知识库（`Retriever.retrieve_by_dimension`）+ 官方链接草拟 → 用户逐条核实标注 `verified_date` → 落 yaml。每季度（1/4/7/10 月 1 日）benchmark 运行时检查 `verified_date` 距今 > 90 天 → 报告头部打印过期提醒（仅提醒，不失败）。

### 2.2 判定器接口（可注入，硬性要求）

```python
# competitor_agent/evaluation/golden.py（新）
class GoldenVerdict(Enum):
    covered = "covered"        # 报告覆盖且语义一致
    missing = "missing"        # 未覆盖（must_have 计入召回率分母）
    contradicted = "contradicted"   # 报告断言与 golden 矛盾（must_have 严重失败 + 计入幻觉口径）
    passed = "passed"          # trap：报告未复述该错误信息
    tripped = "tripped"        # trap：报告复述了（失败）

class GoldenJudge(Protocol):
    def judge(self, report_text: str, assertion: GoldenAssertion) -> GoldenVerdict: ...

class KeywordGoldenJudge:   # CI/mock 默认：确定性关键词+数值匹配（无 LLM、无网络）
    """must_have：claim 规范化分词在报告文本命中（同 CompetitorStore.tokenize 口径）→ covered；
       trap：claim 关键词命中 → tripped。同义改写识别不到是已知局限——real 模式下由 LLM 判定器补足。"""

class LLMGoldenJudge:       # real 模式：LLM 判定覆盖/矛盾（prompt 含 claim + 报告全文相关段落）
    def __init__(self, llm: LLMClient) -> None: ...

def build_golden_judge(llm_mode: str, llm: LLMClient | None) -> GoldenJudge:
    """mock → KeywordGoldenJudge（确定性，CI 可复现）；real → LLMGoldenJudge。"""
```

注入方式与 `build_benchmark_api(llm_mode=...)` 同构：`Benchmark` 构造加 `golden_judge` 参数（None → 按 llm_mode 默认），与现有 `accuracy_eval`/`strategy_eval` 注入点并列。

### 2.3 指标与 BenchmarkReport 扩展

```python
@dataclass
class GoldenResult:                      # 挂进 BenchmarkReport.golden
    must_have_recall: float              # covered / (covered+missing+contradicted)
    trap_pass_rate: float                # passed / (passed+tripped)
    contradicted_count: int              # 矛盾数（额外暴露，幻觉率交叉参照）
    per_task: dict[str, dict[str, float]]   # 按任务拆分（3 任务各自召回/陷阱通过率）
    stale_warnings: list[str]            # verified_date 过期断言提醒
```

3 个固定任务的报告通过 `api.run()` 真实生成（mock 模式下 `BenchmarkMockLLM` 按任务脚本化返回固定报告——**这是 CI 确定性的关键**：报告固定 → KeywordGoldenJudge 判定固定 → 指标固定）；real 模式跑真实报告 + LLM 判定。

### 2.4 评测版本化（工单 4）

```python
# competitor_agent/evaluation/history.py（新）
def snapshot(report: BenchmarkReport, *, commit: str | None = None) -> dict:
    return {
        "ts": iso_utc(), "commit": commit or git_head(),
        "harness_version": HARNESS_VERSION, "llm_mode": ...,
        "metrics": {  # 只收数字，保证 diff 可计算
            "field_accuracy": ..., "hallucination_rate": ...,
            "must_have_recall": ..., "trap_pass_rate": ...,
            "judge_spearman": None,          # doc 83 校准后回填
            "cost_usd": ..., "per_case_cost": ..., "wall_seconds": ...,
        },
    }

def append_history(path: Path, snap: dict) -> None: ...   # evals/history.jsonl 原子追加
def diff(from_rev: str, to_rev: str) -> str: ...          # 按 commit/ts 定位两条快照，逐指标 ± Δ 表格
```

CLI 接线：`python -m competitor_agent.cli benchmark --snapshot`（跑完即写快照）与 `python -m competitor_agent.cli eval-diff <from> <to>`（commit 短 hash 或 `latest/N`）。`Makefile`（如仓库无则 README 提供命令）登记 `eval-diff` 便捷入口。README 放最近 3 版指标变化表（工单 11 落地时回填）。

---

## 3. 接入方式

| 挂点 | 改动 |
|------|------|
| `evaluation/benchmark.py` | `Benchmark.__init__` 加 `golden_judge`/`golden_dir` 参数；`run()` 末尾 `_run_golden()` 产出 `GoldenResult` 挂 `BenchmarkReport.golden`；`benchmark --snapshot` 开关写 history |
| `evaluation/__init__.py` | 导出 `GoldenJudge`/`build_golden_judge`/`snapshot`/`diff` |
| `cli.py` | `benchmark` 子命令加 `--snapshot`；新增 `eval-diff` 子命令 |
| CI（`.github/workflows/ci.yml`） | 沿用现有 benchmark job；golden 指标**只打印不卡门禁**（`--gate` 扩展读取 golden 字段但阈值暂不启用，用户决策） |
| `eval-diff` 输出 | 同时供 README「最近 3 版指标变化表」人工粘贴（工单 11） |

## 4. 验证方式

| # | 验收项 | 通过标准 |
|---|--------|---------|
| 4.1 | 断言集落盘 | 3 个任务 yaml 各 ≥30 条，`verified_date` 全部非空（用户核实标注完成） |
| 4.2 | mock 确定性 | mock 模式连跑 3 次 `must_have_recall`/`trap_pass_rate` 逐位一致 |
| 4.3 | 判定器注入 | 单测：KeywordGoldenJudge 纯本地（断网跑）；LLMGoldenJudge 经注入 mock LLM 验证 prompt 组装与 verdict 解析 |
| 4.4 | 版本化 | 快照含 commit/hash/version；`eval-diff` 对人为构造的两条历史输出 ± Δ 表 |
| 4.5 | 过期提醒 | 篡改 `verified_date` 超 90 天 → stale_warnings 出现，运行不失败 |
| 4.6 | 回归 | 既有全量 pytest + benchmark 门禁 + ruff/mypy 干净；HARNESS_VERSION 0.11.0 → 0.12.0（新增指标口径） |

## 5. 实现优先级与工作量

P0，约 2 天（断言草拟 0.5 天由 opencode 完成、用户核实标注另计；判定器 + benchmark 接线 1 天；版本化 + CLI 0.5 天）。依赖：无（第 1 周并行起点）；被依赖：doc 77 门禁扩展、doc 83（Judge 校准复用 golden 报告流）。

## 6. 核心技术点总结

1. **评测不依赖 LLM 的底线**：KeywordGoldenJudge 保证 CI 全链路零 LLM、零网络、可复现——这是 doc 47「mock 在 LLM 版接口上固定返回」范式的延续，而非新发明。
2. **人工维护区与代码资产区分离**：`evals/` 刻意不放 `tests/evaluation/fixtures`，因为断言要人工季度核实，git 职责不同。
3. **版本化的最小闭环**：快照只收数字 + commit + harness 版本，diff 是纯函数——历史文件纳入 git，本身就是「评测驱动」的展示品。
