# 设计文档 83 —— 第三十三轮：两周真实跟踪运行手册 + 人工锚点评分章程（工单 12 + 3）

> 目标：用系统对 10 个竞品做**两周真实跟踪**（每周 2 轮、每轮全量 10 个），保留全部报告与异动告警；期间**全量人工锚点打分**（工单 3 的真值数据来源），两周后素材与锚点同时就绪。本文档 = 运行手册（调度/环境/竞品注册）+ 评分章程（rubric/盲评/一致性机制）+ 打分工具设计。
>
> 本文档为**设计 + 运营规程**（调度配置实施，打分为人工规程）。
>
> **已确认决策（doc 75 §2，本文档为其操作化）**：
> ① 本机 + `run_scheduled`；机器可能关机 → 错过轮次**跳过不补跑**；
> ② LLM = opencode 同款 DeepSeek Key（`DEEPSEEK_API_KEY`，用户级 env 强制生效）；
> ③ 名单：国际 5（claude-code/cursor/copilot/codex/windsurf）+ 国内 5（trae/workbuddy/zcode/kimi-kcode/deepseek-harness），**每轮全量 10 个**；
> ④ 每周 2 轮；⑤ 锚点**全打**（约 20 份/周 × 20 分钟 ≈ 6~7 h/周，用户接受）。

---

## 1. 运行环境（启动前检查单）

| # | 项 | 要求 |
|---|----|------|
| 1.1 | API Key | `DEEPSEEK_API_KEY` 写入**用户级 env**（doc 74 §3.1：启动 `apply_user_level_environment` 强制应用，忽略 shell 注入）；不在仓库/日志出现 |
| 1.2 | 成本预算 | `llm.pricing_per_1k` 按 DeepSeek 实价配置；单轮成本上限沿用 config（超限 → partial 终止，成本护栏既有机制） |
| 1.3 | 搜索/抓取 | `enable_external_sources: true` + `TAVILY_API_KEY`（可选增强，doc 71 两层架构）；`FETCH_ENABLED` 默认开 |
| 1.4 | 报告落盘 | 输出目录 settings 指向 `output/`（doc 70 Part B 决策）；报告 JSON/MD 全部保留（工单 12 要求「保留全部」） |
| 1.5 | 告警 | alert sink 配置本地文件 sink（+可选 webhook）；异动事件是打分之外的第二观察面 |

## 2. 调度设计

```yaml
schedule:
  cron: "0 9,21 * * 2,5"     # 示例：周二/周五 09:00 与 21:00 各一轮（每周 2 轮，具体时刻可调）
  tasks: ["analyze_all"]     # 每轮全量 10 竞品：逐个 api.run(competitor)（串行；单竞品内部并行由编排层自管）
  missed_policy: "skip"      # 关机错过 → 跳过，不补跑（补跑挤压时间窗干扰 timeline diff，用户确认）
  refresh_dossiers: false    # doc 82 档案刷新默认关；跟踪结束后手动 build 一次
```

- 复用 `core/scheduler.py::WeeklyScheduler`（doc 67，cron 解析 + daemon 线程，job 异常不崩线程）——**零新组件**。
- 串行全量 10 竞品的依据：调度轮是无人值守批处理，吞吐不敏感；串行让成本与日志按竞品清晰隔离，失败互不影响（`run_scheduled` 现有语义）。
- 断档容忍：TTL 新鲜度标注天然兜底（报告带 as_of）；时间线 diff 对不规则间隔无假设。

## 3. 竞品注册（registry 扩充）

新增 5 个国内竞品注册表条目（`core/competitor_registry.py`，doc 79 合入后随 `coding_agent.yaml::registry_seeds`）。**核实结论已回填（2026-09-08，来源：web 核实 + 用户补充情报）**：

| 竞品 | 规范名 | 别名（建议） | 官网核实结论 |
|------|--------|-------------|-------------|
| Trae（字节） | `trae` | trae-ai, trae ide | ✅ https://www.trae.ai（另有国内版 trae.cn）；定位 "AI Coding Engineer"（TraeCode）+ 办公（TraeWork） |
| WorkBuddy（腾讯） | `workbuddy` | tencent workbuddy, work-buddy | ✅ https://www.workbuddy.ai（文档 codebuddy.cn/docs/workbuddy；2026-03-09 上线的全场景 AI 办公工作台，开放平台 open.workbuddy.cn） |
| Z Code（智谱） | `zcode` | z-code, zhipu zcode, zcode agent | ✅ https://zcode.z.ai/cn（"GLM-5.3 官方 Harness"，氛围编程工具，macOS/Windows/Linux v3.11.2）；**检索限定词：`zcode.z.ai` 或 `智谱 Z Code`，裸搜 "Z Code" 全是噪声** |
| Kimi Code（月之暗面） | `kimi-kcode` | kimi kcode, kimi code, kimi k3 coding | ✅ https://www.kimi.com（Kimi K3 上线；Kimi Code 桌面端：kimi.ai/products/download；API 平台 platform.kimi.com） |
| DeepSeek Harness | `deepseek-harness` | deepseek harness | ✅ https://www.deepseek.com/harness（2026-08-27 developer preview，"Everything is a plugin"） |

**随核实确认的时间线情报（供 doc 80/82/时间线种子）**：
- Z Code 发布 2025-12-26（B 级来源）；**2026-06 转自研 ZCode Agent 内核、不再适配第三方 Agent**（重要时间线事件，首分析建档时应落 `version_release`/策略类事件）。
- GLM Coding Plan 证据统一 A 级来源：`https://docs.bigmodel.cn/cn/coding-plan/overview`；定价 ¥118 / ¥538 / ¥1078 三档（ZCode 官网首页展示价 Lite/Pro/Max，**2026-09 采集，一年内已两次调价，强时效**——pricing 维度断言/报告引用必须带 as_of）。
- 跑分 provenance 打标（doc 80 契约首个实战用例）：「Z Code vs Claude Code 通过率 +2.39%」→ `source_type=vendor_self_reported` + 自研 benchmark（Z.ai Code Bench），**风险等级最高**；「GLM-5.1 SWE-bench 77.8」→ **待核实**官方提交/第三方复测，采集时不得标注为 third_party。

## 4. 人工锚点评分章程（工单 3 真值来源）

### 4.1 评分对象与节奏

- 对象：每轮全部产出报告（全量 10 竞品 × 每周 2 轮 ≈ 20 份/周）；两周 ≈ **30~40 份**（含停机折损）。
- 节奏：每周一次评分 session（建议周末，一次连续打完，不跨天分摊——防标准漂移）；单份 15~20 分钟，session 约 6~7 h。
- n≥10 即可算 Spearman，n≥15 较稳；两周全打样本量充裕。

### 4.2 Rubric（只评「洞察质量」，事实准确性由 doc 77 NLI 机器测——两指标隔离防污染）

| 分 | 锚点描述 |
|----|---------|
| 1 | 纯事实罗列无推断；或存在明显编造推断 |
| 2 | 有结论但均为单维度常识（「价格有竞争力」），无跨维度综合 |
| 3 | 事实准确 + 少量单维度推断，推断有证据支撑 |
| 4 | 有跨维度综合推断（如「定价上调 + 生态扩张 → 转向企业市场」），证据链完整 |
| 5 | 推断反直觉且被证据支撑；或给出可操作决策建议（「此时不值得切换」） |

### 4.3 公平性机制（5 条，全部由打分工具强制）

1. **盲评**：报告文件名脱敏（`<hash>.md`），不显示生成时间/引擎/版本；顺序随机。
2. **理由必填**：每分附一句话理由，无理由分数不计入锚点集。
3. **自一致性抽查**：随机 20% 报告隔周重打；同一报告前后分差 >1 → 该报告两次分数均作废重评。
4. **固定 session**：一批一次打完。
5. **客观校准**：Judge 分 vs 锚点分 Spearman ≥0.7 才算校准（数字进 README）。

### 4.4 打分工具（opencode 实现，用户零搭建成本）

```
python -m competitor_agent.cli eval-anchor          # 交互式打分
  --pool <reports_dir>        # 待打分报告池（*.md/*.json，自动排除已打分）
  --no-blind                  # 关闭盲评（默认开：hash 化展示名 + 确定性随机顺序）
  --out <data_dir>/anchors.jsonl   # {report_hash, score, reason, scored_at, session_id, is_retest}，缺省 <data_dir>/anchors.jsonl
  --retest-rate 0.2           # 从已打分池抽 20% 混入本周（盲态重测）
  --seed N                    # 洗牌种子（缺省随机，session 内固定）
python -m competitor_agent.cli eval-anchor-stats    # 统计：样本量/分分布/重测一致率/作废清单
```

> **实施说明（2026-09-09）**：`evaluation/anchor.py` 纯函数层（`report_hash` 内容短 hash 关联重测 / `collect_pool` 排除已打分+确定性洗牌+重测盲态混入 / `validate_entry` 理由必填+分数域 / `append_anchor`/`anchor_stats`/`load_scored_hashes`）+ CLI `eval-anchor`/`eval-anchor-stats` 两条子命令（main() 内 LLM/API 构造前短路）。20 个新单测（`test_registry_domains_83.py` 8 + `test_anchor.py` 12）；§6.2 注册表验收、§6.3 打分工具单测覆盖均达成。两周实跑与人工打分为运营规程（§1/§4.1~§4.3/§5），待用户执行；Judge 校准（Spearman）依赖本工具产出的锚点集，随 doc 76 评测体系实施。

两周结束后：LLM Judge（rubric 同表注入）对全部报告打分 → `judge_scores.jsonl` → Spearman 计算（`evaluation/golden.py` 或独立 `evals/judge_calibration.py`）→ 结果与散点图进 README（工单 11）。

## 5. 跟踪收口（两周后）

1. 选 1 份最佳报告（锚点最高 + NLI 幻觉率最低）脱敏入 `examples/`。
2. 全量报告 + 异动告警记录 + 档案（doc 82 `dossiers/`）= README「真实运行」证据位。
3. 指标快照（doc 76 `--snapshot`）记录跟踪期首末对比：幻觉率 / 召回 / 单报告成本 / 端到端耗时变化 → README 指标表。

## 6. 验证方式（运行手册层面）

| # | 验收项 | 通过标准 |
|---|--------|---------|
| 6.1 | 调度就绪 | cron 触发成功跑通一轮（10 竞品全部产出报告或可读失败原因）；错过轮次日志可见「skip」 |
| 6.2 | 注册表 | 5 个国内竞品可被 `resolve_competitor` 解析；官网核实结论回填 §3 |
| 6.3 | 打分工具 | 盲评脱敏/理由必填/重测混入 全部单测覆盖 |
| 6.4 | 素材闭环 | 两周后 examples/ 1 份 + README 指标表 + 锚点 n≥20 且 Judge 校准结论可计算 |

## 7. 工作量与优先级

P0（调度与打分工具约 1 天实施，其余为运营规程）。依赖：doc 76（快照 CLI）、doc 82（收口档案，可后置）；被依赖：工单 3 校准（素材来源）。

## 8. 核心技术点总结

1. **零新调度组件**：doc 67 的 `WeeklyScheduler` 直接复用，`missed_policy: skip` 只是一个配置语义的明确化。
2. **全打锚点的可行性靠工具**：盲评/随机/重测/理由必填全部由 `eval-anchor` 强制，把 6~7 h/周的人力约束在「纯判断」上。
3. **两指标隔离**：人工只评洞察质量，机器测事实准确性——rubric 不含事实分是防污染的关键设计。
