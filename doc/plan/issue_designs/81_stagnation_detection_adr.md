# 设计文档 81 —— 第三十一轮：ADR——自然收敛策略的停滞检测补充（工单 10）

> 形态：**ADR（架构决策记录）**，叙事为「演进而非推翻」——`max_steps=None` 是 doc 62 写进代码注释的刻意决策（「移除迭代次数限制，靠 LLM 自然收敛 Final Answer；防失控退化为子 Agent 各自的 max_steps 兜底 + 硬性安全护栏」），本决策不推翻它，而是补充一个**客观收敛信号**。
>
> 本文档为**设计**（不实现）。
>
> **已确认决策（doc 75 §2）**：保留自然收敛为主路径；新增停滞检测；ADR 写演进。

---

## 1. 背景与问题

| 项 | 现状（已核对） |
|----|---------------|
| Lead 循环 | `ReactLoop(max_steps=None, budget=None)`（api.py `_react_loop`）——无限步，靠 LLM 自主收尾 |
| 子 Agent | `build_subagent(max_steps=None)` 同样无限 |
| 兜底 | 子 Agent 各自 `max_steps` 注释已说明移除；实际防线 = 取消（checkpoint `is_cancelled` + session_id 协作）+ LLM/tool 超时 + URL 护栏 + FetchPolicy |
| partial 产物 | `analyze_react_report`：`budget_exhausted → terminal="partial"`；`CancelledResult` 语义存在 |
| 真实缺口 | **停滞循环不可见**：LLM 反复调用相同工具/相同参数、工具结果高度重复时，没有任何机制提示收敛——线程与 token 在静默燃烧，直到人工取消（doc 74 P2④ 已点名此风险，用户当时决定暂不修复） |

## 2. 决策（Decision）

**保留 `max_steps=None` 自然收敛为主路径；新增停滞检测器（StagnationDetector）作为客观收敛信号，注入而非强制。**

1. **停滞检测（纯本地计算，不调 LLM）**：`ReactLoop` 每步结束后，对最近窗口（默认 8 步）的 transcript 工具调用计算**重复度**：
   - `tool_signature = (tool_name, 规范化 args)` 重复次数；
   - `result_dup_rate`：工具结果文本 `tokenize` 后与窗口内既有结果的 jaccard 相似度均值。
   判定：窗口内同 signature ≥3 次 **或** `result_dup_rate > 0.85` 连续 2 轮 → 停滞。
2. **收敛提示注入（一次）**：停滞触发时，向历史注入一条 system 消息（`wrap_untrusted` 包裹）：
   > 「系统提示：最近 N 步工具调用与结果高度重复（证据：signature ×k / 重复率 r）。若无新增信息来源，请综合已有证据产出 Final Answer；若确需新信息，请更换工具、查询词或 URL。」
   同一 session 停滞提示**最多注入 2 次**（防提示本身成为循环）。
3. **强制收尾保留现有机制**：`IterationBudget` 触发（`self._budget.record_iteration` 路径）→ 现有 `partial` 流程不变；新增「停滞 2 次仍未收尾」时在事件流发 `progress` 警示（可观测，不强制截断——截断权留给用户取消与预算）。
4. **不做**：硬性 max_steps 回退（推翻 doc 62 决策）、自动终止循环（误杀长任务的风险大于收益）。

## 3. 理由（Rationale）

1. 自然收敛在绝大多数真实运行中工作良好（doc 62 落地以来的运行记录），问题仅是**病态停滞无信号**——对症下药是「信号」，不是「上限」。
2. 停滞检测是纯本地计算（transcript 已在内存），零 LLM 成本、零网络依赖、确定性可测。
3. 注入提示与 LLM 自主性兼容：模型仍拥有「继续搜」的自由，只是获得客观事实反馈——与「LLM 主导编排 + 保证型代码兜底」的项目主旨一致。
4. ADR 叙事为演进：doc 62 的决策语境（防硬上限截断深挖任务）不变，本补充不改变该语境。

## 4. 后果（Consequences）

- 正面：病态停滞从「不可见燃烧」变为「可观测 + 有反馈」；面试叙事完整（「我们发现无限循环的边界并给了实证方案」）。
- 代价：ReactLoop 每步多一次窗口统计（O(window)）；提示注入需回归验证不破坏压缩/pinned facts 流。
- 风险与缓解：重复度高 ≠ 一定无新信息（如分页抓取同构页面）→ 阈值可配 + 提示文案明确允许「换查询词继续」；`args` 规范化需剔除时间戳/随机数类噪声参数（配置 `ignore_arg_keys`）。

## 5. 实现落点与验证

| 项 | 内容 |
|----|------|
| 落点 | `agent/react_loop.py`（每步统计 + 注入）；`config`（`agent.stagnation: {window: 8, dup_threshold: 0.85, sig_repeat: 3, max_hints: 2, ignore_arg_keys: [ts, _t, nonce]}`）；事件：停滞触发发 `progress` |
| 单测 | signature 重复触发；dup_rate 触发；提示最多 2 次；分页场景（正常连续翻页）不误触；ignore_arg_keys 生效 |
| 评测用例 | **预算耗尽 → partial 报告并标注完成度**作为评测用例入 benchmark（工单 10 原文要求；复用 `build_benchmark_api` 注入紧预算） |
| 回归 | 全量 pytest + benchmark 门禁 + ruff/mypy 干净 |

## 6. 工作量与优先级

P2，约 1 天（含评测用例）。依赖：无；被依赖：无。

## 7. 核心技术点总结

1. **ADR 的价值在叙事一致性**：演进式补充与 doc 62 决策共存，避免「今天的自己打昨天的自己」。
2. **停滞信号三要素**：signature 重复、结果重复率、注入上限——缺「上限」会把收敛提示变成新的循环源。
3. **评测用例闭环**：预算耗尽的 partial 产物从「代码行为」升格为「被评测保证的行为」。
