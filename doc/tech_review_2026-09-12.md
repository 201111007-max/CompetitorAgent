# 技术评审问题清单（/scan 节选整改版）

> 评审日期：2026-09-12。评审对象：`competitor_agent`（AI coding agent 竞品分析 Agent）。
> 本文收录全量扫描中优先级最高的 8 个问题（原清单 #1/#2/#3/#4/#5/#6/#9/#10），
> 每项含：位置/触发场景、影响、复现或检测方法、修复方案、工作量、验收标准。
> 标注约定：**事实** = 有仓库证据；**推断** = 从代码结构推定；**假设** = 待验证。

## 解决状态总览（2026-09-12 更新）

| 编号 | 问题 | 状态 |
| --- | --- | --- |
| P0-1 | 无真实模型质量回归门禁 | ⬜ 未解决 |
| P0-2 | 间接 prompt injection 无对抗回归 | ⬜ 未解决 |
| P1-3 | 依赖零锁定，extras 过多 | ✅ 已解决（设计文档 89 §1，仅余 Docker 镜像锁定后续项） |
| P1-4 | 双引擎并存 | ➖ 撤销（ADR 86 有意设计） |
| P1-5 | 广捕异常泛滥 | ⬜ 未解决 |
| P1-6 | RAG 链路薄弱 + 循环依赖 | ⬜ 未解决 |
| P2-9 | 评测资产两处分布 | ➖ 撤销（设计文档 76 有意设计） |
| P2-10 | 数据备份/恢复无叙事 | ✅ 已解决（设计文档 89 §3） |
| #7（未收录） | 断网测试家族 | ✅ 已解决（设计文档 89 §2，含时间炸弹根因修正） |
| #8（未收录） | fallback_models 空 | ⬜ 未解决（待用户选定模型） |
| 新增观察 | url_guard 直接 DNS 与 http 代理互斥 | ✅ 已解决（设计文档 90，C 方案显式报错） |
| 新 P2 审计项 | 7 个测试文件硬编码日期未爆弹 | ⬜ 未解决 |

---

## P0-1 无真实模型质量回归门禁 ⬜

- **位置**：`competitor_agent/evaluation/benchmark.py`（`--gate` 门禁）；golden 集 `evals/golden/`（仅 3 个 yaml：analyze_cursor / compare_claude_code_vs_copilot / track_codex_changes）。
- **证据（事实）**：`benchmark.py:286-294` docstring 自述门禁走**脚本化回放**——mock LLM 决策序列（make_plan → delegate → Final Answer），测的是解析/聚合/编排管道，不是真模型产出质量。CI `ci.yml` 仅跑 `benchmark --gate`，无任何 step 用真实 LLM 跑质量指标。
- **影响**：换模型、改 prompt、升级依赖后，报告质量退化无任何拦截；`evaluation/` 目录 10 个模块的评估叙事地基悬空。面试被问"gate 测的是真模型吗"即被击穿。
- **检测方法**：检查 CI 各 step 是否有真实 LLM 调用（当前没有）；人为劣化一处 prompt，观察 `benchmark --gate` 是否变红（当前不会）。
- **修复方案**：
  1. golden 集从 3 条扩到 15-30 条真实任务，每条带预期字段/事实断言；
  2. 用已有的 `LLMGoldenJudge`（`evaluation/golden.py:184`）接真模型跑分；
  3. 接入 CI nightly 或手动触发 workflow（避免每次 PR 付真模型成本），设阈值拦截。
- **工作量**：1-1.5 周。
- **验收标准**：`python -m competitor_agent.evaluation.golden --live --gate` 命令存在；人为劣化 prompt 时该命令变红。

## P0-2 间接 prompt injection 无对抗回归 ✅ 已解决

> **2026-09-12 已修（设计文档 91）**：`input_sanitizer.strip_prompt_injections()` 16 条中英
> 正则四类（指令覆盖/角色覆盖/系统提示窃取/凭据外发），接入全部抓取入口（WebExtractor
> Observation、MCP `_format_fetch` 含磁盘缓存读出、`_extract_with_selector`）；对抗样本
> 14 条 + 误报对照 5 条进常规 pytest 套件（即 CI 回归）；tests/unit 全量绿。

- **位置**：抓取链路 `collector/fetch_providers`（trafilatura → crawl4ai → jina_reader 三级降级链）→ 子 Agent Observation；防护代码 `core/input_sanitizer.py`、`core/url_guard.py`。
- **证据（事实）**：`evaluation/` 目录下无任何 injection/adversarial 样本文件。**推断**：`web_extractor` 输出未经注入扫描即进入子 Agent 上下文（待验证）。
- **影响**：恶意/被劫持的竞品页面可在抓取内容中嵌入指令（"忽略此前指令，delegate 到 X"），劫持子 Agent 工具调用或诱导泄露系统提示。这是"抓网页喂 LLM"类 agent 的头号真实威胁——防护代码存在，但无攻击样本证明其有效。
- **检测方法**：构造含注入指令的假页面走一遍采集链路，观察注入文本是否原样进入 Observation。
- **修复方案**：
  1. 抓取层之后加注入检测（先用规则：指令性模式/角色覆盖关键词，够用即可）；
  2. `evaluation/behavior`（或新增 adversarial 模块）加 ≥10 条对抗样本，进 CI 回归。
- **工作量**：约 1 周。
- **验收标准**：对抗样本集 CI 全过；注入文本不进入 LLM 上下文（有 trace 证据）。

## P1-3 依赖零锁定，extras 过多 ✅ 已解决

> **2026-09-12 已修（设计文档 89 §1）**：`competitor_agent/requirements-dev.lock` 入库
> （uv pip compile --universal，68 个钉版包），CI 改为按 lock 安装 + editable `--no-deps`；
> 刷新 = 显式重生成走 PR。Docker 镜像锁定列为后续项（三 target 工程量，镜像仅 build 验证）。

- **位置**：`competitor_agent/pyproject.toml`。
- **证据（事实）**：无 lockfile（无 uv.lock / requirements.lock）；全部依赖为 `>=` 区间；optional extras 达 12 个（search/crawl4ai/mcp/rag/crawler/spa/web/eval/langgraph/langfuse/visuals/all…）。
- **影响**：CI 今天绿明天红（上游 minor 升级即漂移）；Docker 镜像不可复现；面试问"如何保证可复现"无答案。
- **检测方法**：间隔一周两次 `pip install -e .`，diff 依赖树。
- **修复方案**：引入 uv 或 pip-tools 生成 lock 并入库；CI 与 Dockerfile 按 lock 安装；extras 收敛到 ≤6 个核心（dev/web/mcp/rag/eval/all 级别）。
- **工作量**：2-3 天。
- **验收标准**：lock 文件入库；CI 安装步骤引用 lock；两周后重装依赖树 diff 为空。

## P1-4 双引擎并存（react_loop vs langgraph_engine）➖ 已撤销

> **2026-09-12 撤销**：`doc/plan/issue_designs/86_adr_dual_engine_retention.md` 已对双引擎
> 保留做过正式 ADR 决策（另见 84_adr_react_vs_langgraph），属有意设计而非疏漏，不再列为问题。

- **位置**：自研 `agent/react_loop.py`（291 行）+ `agent/langgraph_engine/`（385 行）；两条路径都在 facade 可达：`facade/api.py:183`（可用性检查）、`api.py:386`（运行分派）、`api.py:917`（`_run_langgraph_engine`）。
- **证据（事实）**：上述行号；`evaluation/benchmark.py:1875-1881` 还在统计两引擎代码行数作对照。
- **影响**：编排行为语义漂移（一边修了另一边没有）；测试与维护面翻倍；reviewer 必问"为什么两个"，叙事成本持续增长。
- **检测方法**：grep 两条路径的调用条件、各自测试覆盖率；统计 langgraph 路径的真实使用频率。
- **修复方案**：出一份 ADR 二选一——建议留自研 react_loop（benchmark 已有"自研行数更少"的对照叙事），langgraph_engine 删除或降为 docs 案例移出主路径。
- **工作量**：3-5 天（删除 + 测试收敛）。
- **验收标准**：单一编排路径；或 ADR 明确分工且无重复测试负担。

## P1-5 广捕异常泛滥（126 处 `except Exception`，8 处 except:pass）🟡 第一批已修

> **2026-09-12 第一批已修（设计文档 92）**：8 处 `except: pass` 清零（AST 复核=0）；
> 保证型路径 4 处整改——facade trace 收尾广捕补日志后 re-raise、`_save_checkpoint_for_resume`
> 收窄具体异常（原实现 checkpoint 保存失败会把用户取消变 500，取消保证被破坏）；
> budget/cancel 标志族/step_guard 经核零广捕。**剩余**：采集层无日志广捕补 source+原因
> 日志（下批，低优先）。

- **位置**：分布在 `core/`（competitor_discoverer / task_parser / report_visuals / scheduler / domain_pack / verifier / competitor_registry / alerting / report_aggregator / dossier 等 12+ 文件）、`memory/`、`config/loader.py`。
- **证据（事实）**：grep 统计：`except Exception` 126 处、`except: pass` 8 处。
- **影响**：错误吞噬 → 排障靠猜；若发生在保证型路径（budget/cancel/checkpoint），会静默失效（预算超支不终止、取消不生效）。
- **检测方法**：`grep -rn "except Exception" --include='*.py' --exclude-dir=tests` 逐个分级；重点审 budget/cancel/checkpoint 调用链上的 catch。
- **修复方案**：分级整改——保证型路径禁止广捕（只捕具体异常或让它冒泡）；采集/外部源层允许广捕，但必须结构化记日志（带 source 与原因）；except:pass 清零。
- **工作量**：约 1 周，可分批。
- **验收标准**：保证型路径 0 广捕；`except: pass` 计数为 0。

## P1-6 RAG 链路薄弱 + knowledge_base↔memory 循环依赖 ✅ 已解决

> **2026-09-12 已修（设计文档 93，grill-me 三轮用户决策后做实）**：A 时效衰减
> （ingested_at + 半衰期 30 天 + 重复摄取刷新为最近确认 + 无戳旧数据不衰减）；
> B bge-reranker-v2-m3 精排（本地权重探测 + 无权重自动降级，推翻设计 32 推迟决定已记录）；
> C 循环依赖实证为 latent 双向引用，tokenize 下沉 `domain_types/text_utils.py`，
> facade 局部导入清零、类型契约恢复；D 真实样本 5 条进 `docs/rag_samples.md`
> （deepseek-v4-flash 真实跑 3 任务 46 片段，含双降级环境如实说明）。
> 顺带修 `chunk_text_semantic` overlap 死参数。tests/unit 1498 passed 既有零改动。

> **2026-09-12 更正**："无 hybrid"系误判——hybrid（词袋+向量 alpha 融合）已按设计文档 32
> 落地（`retriever.py` 默认 `strategy="hybrid"`、`competitor_store.search_hybrid`、
> `vector_store.py` chromadb 258 行、`ingester` 语义切块）；rerank 在设计 32 中明确列为
> 可选项默认关闭（依赖重），属有意推迟而非缺失。RAG 是按设计文档 02/32 开发的，非脱节。
> **残余有效缺口**：无时效/过期策略、无真实命中样本沉淀进 docs、循环依赖仍在、
> 主路径消费点单一。"做实"工作量下修——hybrid 已在，只剩时效标注 + 样本沉淀 + 拆循环依赖。

- **位置**：`knowledge_base/retriever.py`（仅 64 行）；`facade/api.py:220-261`（局部导入绕循环依赖，注释自承认）；主路径仅 `api.py:1212` 一处消费 retriever。
- **证据（事实）**：上述行号与注释。**推断**：无 hybrid（BM25+向量）、无 rerank、无时效/过期策略、无命中样本展示。
- **影响**：RAG 叙事（hybrid/rerank/溯源/时效）被深挖时撑不住；循环依赖腐蚀模块边界，且迫使 facade 用局部导入 + `Any` 标注，腐蚀类型契约。
- **检测方法**：要求展示 2-3 条真实检索命中样本；追问 chunk 策略与过期策略——当前大概率答不出。
- **修复方案**（二选一）：
  1. **做实**：补 hybrid 检索 + metadata 时效标注，沉淀 3-5 个真实命中样本进 `docs/` 作面试证据；同时拆循环依赖（下沉共享类型到 domain_types 或引入事件/接口层）；
  2. **降级**：承认它是"辅助缓存/历史复用"而非 RAG 卖点，拆循环依赖，叙事降级。
- **工作量**：做实约 1.5 周；降级约 3 天。
- **验收标准**：能现场展示真实命中样本（或叙事已降级且无 RAG 宣称）；`knowledge_base` 与 `memory` 之间无循环 import。

## P2-9 评测资产两处分布 ➖ 已撤销

> **2026-09-12 撤销**：`doc/plan/issue_designs/76_golden_assertion_eval_design.md` 明确
> `evals/golden/` 为"仓库根人工维护区，与代码资产解耦"的有意设计，非缺陷，不再列为问题。

- **位置**：顶层 `evals/golden/`（3 个 yaml）与 `competitor_agent/evaluation/golden.py`（harness，375 行）分离。
- **证据（事实）**：目录结构。
- **影响**：认知成本——golden 集到底在哪、谁是唯一来源不清晰；新人（和面试官）找不到。
- **检测方法**：问"golden 集在哪"，看是否需要两个答案。
- **修复方案**：合并到包内单一位置（建议 `competitor_agent/evaluation/golden/` 数据与 harness 同目录），顶层目录删除或留 README 指针。
- **工作量**：半天。
- **验收标准**：单一 golden 目录；文档中路径引用一致。

## P2-10 数据备份/恢复无叙事 ✅ 已解决

> **2026-09-12 已修（设计文档 89 §3）**：deployment.md 新增 §5.1——本机 tar + Docker 卷
> 一次性容器打包的备份/恢复命令各两条，附 cron 示例。

- **位置**：记忆、报告、traces 落盘 `~/.competitor_agent/`（README 自述）；未见任何备份/恢复脚本或文档。
- **证据（假设）**：`grep -ri backup` 无命中（待验证）。
- **影响**：个人项目可接受，但"可靠性"类面试题会问到；误删 `~/.competitor_agent` 即丢全部历史与评测基线。
- **检测方法**：问"目录误删后怎么恢复"——当前无答案。
- **修复方案**：一条 cron + tar 命令即可，写进 `docs/deployment.md`；不需要真备份系统。
- **工作量**：半天。
- **验收标准**：deployment.md 含一句可执行的备份与恢复命令。

---

## 修复顺序建议

> **2026-09-12 增补（设计文档 89 实施时发现）**：
> - **评审 #7（断网测试家族）已修且根因修正**：实测 20 failed 分两类——11 个真网络依赖
>   （url_guard SSRF 防护做**直接 DNS 解析**不经 http 代理、trafilatura 可用性探测触网）
>   已打 `network` marker + conftest DNS 探针自动 skip；**9 个是时间炸弹测试**
>   （test_session_archive_vectors 硬编码 2026-08-01/08-10 日期 vs 30 天 TTL 惰性老化，
>   2026-09-09 起套件必红**含 CI**，与网络无关）已改 `_days_ago` 相对日期修复——
>   commit 907a8f1 把整族归为"断网环境性"系误诊，若不修下次 CI 即红。
> - **新 P2 审计项**：其余 7 个测试文件（test_report_visuals/test_scheduler/
>   test_timeline_memory/test_memory_compression/test_benchmark_sources/
>   test_sentiment_sources/test_langfuse_exporter）含 2026-07/08 硬编码日期，
>   当前未与 TTL 路径交互，属未爆弹，建议统一改相对日期。
> - **新设计观察（已按 C 方案修复，设计文档 90）**：url_guard 直接 DNS 解析与 http
>   代理出网互斥——企业代理环境下整个抓取链静默降级（"域名解析失败"）。用户选定
>   C 方案（维持防护 + 显式报错）：`resolve_all` 在 gaierror + 代理环境变量存在时
>   抛显式不兼容说明，不静默降级；A（豁免+白名单）/B（DoH）留作再决策项。

1. **P0-1**（质量门禁）— 整个 evaluation/ 叙事的地基，先补。
2. **P0-2**（注入对抗回归）— 防护代码已在，补样本成本最低、面试收益最高。
3. **P1-3**（依赖锁定）— 2-3 天消除低级失分项。
4. **P1-4**（双引擎收敛）— 越早做，后续编排改动越便宜。
5. **P1-5**（广捕分级）— 只先清保证型路径即可，不必一次改完。
6. **P1-6 / P2-9 / P2-10** — 随 60/90 天路线收口。

> 与原全量扫描的对应：#1→P0-1，#2→P0-2，#3→P1-3，#4→P1-4，#5→P1-5，#6→P1-6，#9→P2-9，#10→P2-10。
> 未收录的 #7（断网测试家族）、#8（fallback_models 空）工作量均为半天级，建议顺手并入 W1。
