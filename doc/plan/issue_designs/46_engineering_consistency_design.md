# 设计文档 46 — 工程一致性细节收敛

> 触发：2026-08-15 第三轮评审——六处工程一致性/健壮性问题：① 双编排实现并存（SingleOrchestrator+GapExecutor vs
> TeamOrchestrator+CollectorAgent.collect）；② ReAct 消息膨胀（每轮重发完整 task + Observation 原文入上下文不截断）；
> ③ async 是线程包装（`asyncio.to_thread`/`run_in_executor`）；④ `use_llm` 默认值不一致（cli.py:61 False vs
> api.py:95 True）；⑤ 评测全 mock LLM，真实模型健壮性未验证（`BaseAgent` 无直接覆盖测试）；⑥ 成本计价硬编码
> DeepSeek 单价（llm/client.py:33）。
> 依赖：设计文档 38-42（工具/评测基础已就绪）、40（工具注册表统一先例）；其中 ① 与 43/45 相关，②/④ 独立可修。

## 1. 问题现状

- **① 双编排并存**：single 走 `SingleOrchestrator`（core/orchestrator.py:189 经 GapExecutor 统一闭环），team 走
  `TeamOrchestrator`（team/orchestrator.py:119 → CollectorAgent.collect 自有采集循环，team/collector_agent.py:83）。
  两条"选源→采集→分析"实现，行为已漂移（记忆注入不对称见设计文档 45）。`fetch_candidate`（gap_executor.py:37-69）
  已收敛"选源→采集"分派，但 team 的 Analyzer 未复用 GapExecutor 的 RAG/记忆注入段。
- **② ReAct 消息膨胀**：`ReactAgent.run`（agent/react_agent.py:54-79）每轮 `messages + [{"role":"user","content":
  user_message}]` 重发完整任务；`Observation（工具结果...）: {wrap_untrusted(str(result))}` 原文入上下文**无截断/
  无 max_tokens/无压缩**——长页面抓取多轮后上下文失控（主路径 `_react_web_extract` 有 `max_content_chars` 截断，
  但循环内 Observation 无上限）。
- **③ async 是线程包装**：`asyncio.to_thread`（team/orchestrator.py:91/167、collector_agent.py:107）、
  `loop.run_in_executor`（facade/api.py:714）——并发上限是线程池而非事件循环；同步阻塞 I/O 包线程。
- **④ use_llm 默认不一致**：CLI（cli.py:61 `use_llm: bool = False`）与库入口（facade/api.py:95 `use_llm: bool = True`）
  默认相反 → 同一环境 CLI 与库行为不同。
- **⑤ 评测全 mock**：`evaluation/benchmark.py` 主用例跑 `BenchmarkMockLLM`，真实模型长上下文/工具调用健壮性未量化；
  `BaseAgent`（team/base_agent.py:57）无直接覆盖测试（codegraph 标注 ⚠️ no covering tests）。
- **⑥ 计价硬编码**：`_PRICING_PER_1K = {"input": 0.0003, "output": 0.0006}`（llm/client.py:33）DeepSeek 量级近似，
  换模型展示成本不准。

## 2. 目标设计

1. **编排收敛**：team 的 Analyzer 复用 GapExecutor 的"RAG/记忆注入 + 分析"段（或明确 team 委托 GapExecutor），
   消除两套分析实现；与 43/45 合并治理。
2. **ReAct 上下文上限**：循环内 Observation 截断（读 `max_content_chars`）+ 超长时摘要化/丢弃旧步；task 只发首轮。
3. **默认值统一**：`use_llm` 默认统一（库 True / CLI 随配置），文档标注差异。
4. **真实评测补充**：`--llm real` 报告 + `BaseAgent` 覆盖测试（status 决策路径单测）。
5. **计价可配**：单价从 config 读取（按模型覆盖），无配置沿用现有近似（行为不变）。

## 3. 模块/接口设计

### 3.1 编排收敛（`team/analyzer_agent.py` / `core/gap_executor.py`）

```python
# team AnalyzerAgent 复用 GapExecutor 的分析段（注入+校验+补全）而非自建
analyzer = GapExecutor(selector, extractor, registry.get(obs.gap_field), budget, ...)
# 或收敛为：AnalyzerAgent 持有统一 _analyze(observation, gap, context)（含 rag+memory 注入）
```

- 先做低成本收敛：AnalyzerAgent 增加 `memory_context` 注入（设计文档 45 已列），分析段抽到共享函数，两条路径调用同一实现。
- 完整合并（team 全委托 GapExecutor）列为 43 的一部分，避免重复治理。

### 3.2 ReAct 上下文上限（`agent/react_agent.py` / `agent/react_loop.py`）

```python
_OBS_MAX_CHARS = 4000          # 单条 Observation 截断（循环内）
MAX_HISTORY_STEPS = 8          # 超过后压缩旧 Tool 消息为摘要
def run(self, system_prompt, user_message, max_steps=6, obs_max_chars=4000):
    # 首轮之后不再重发完整 user_message；Observation 取 result[:obs_max_chars]
    # 历史超长时保留 system + 最近 N 步 + 最新任务提示
```

- 配置项读 `CollectorConfig.max_content_chars`（41 已加）或独立常量，优先复用前者。

### 3.3 默认值统一 + 计价可配 + 评测

- `facade/api.py:95` 保持 `use_llm=True`（库语义）；`cli.py:61` 改随 `config`/默认 True，README 标注。
- `config/loader.py` 增 `llm.pricing_per_1k`（可空），`_PRICING_PER_1K` 改为实例属性（config 优先、默认近似）。
- 评测：`--llm real` 已存在（37），补 `BaseAgent` 状态机单测（SUCCESS/RETRY/DEGRADED/FAILED 决策路径）。

## 4. 接入方式

```
编排：team Analyzer 复用共享分析段（45 先接线 memory，46 再抽公共函数）
ReAct：react_agent.run 加 obs_max_chars + 历史压缩；facade 透传 config.max_content_chars
默认值：cli.py use_llm 对齐 config（默认 True）
计价：config.llm.pricing_per_1k 注入 LLMClient（无配置 → 现值近似）
评测：BaseAgent 状态机单测 + 既有 --llm real
```

## 5. 验证方式

- **单测（ReAct 上下文）**：mock LLM 输出超长 Observation → 循环内消息总字符被截断、超步数压缩后仍可继续；task 只出现一次。
- **单测（默认值）**：cli 默认 `use_llm` 与库一致；无配置时 `_PRICING_PER_1K` 现值不变（回归）。
- **单测（BaseAgent）**：`_retry` 状态机（retries 耗尽 → FAILED；可重试 → RETRY）。
- **回归**：既有 CLI/ReAct/评测测试全绿；`test_api.py`/`test_cli.py` 行为不变。

## 6. 实现优先级与工作量

- 优先级：**中低**（多为一致性/健壮性细节，不影响报告正确性；② 的上下文失控在长页面下会真实掉点）。
- 工作量：约 1-1.5 天。
  - 编排收敛（公共分析段）：0.4 天（依赖 45 先接线 memory）；
  - ReAct 上下文上限：0.3 天；
  - 默认值/计价/BaseAgent 测试：0.3 天；
  - 回归：0.2 天。
- 前置：45（memory 注入先收敛）、41（`max_content_chars` 已有）。独立于 43/44。
