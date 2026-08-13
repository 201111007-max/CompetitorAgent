# 设计文档 25 — 性能数字直连榜单源

> 对应 `implementation_plan.md` §12.2 #4（P1）「性能数字靠 LLM 读网页」。
> 数据源依赖设计文档 23（`BenchmarkSourceProvider`）；评测见设计文档 29。

## 1. 问题现状

- `analyzers/performance_analyzer.py` 从抓取的网页文本中由 LLM/规则抽取性能数字（如 "SWE-bench: 62%"），完全依赖官网/文档页恰好提到该数字。
- 对快速变动的 AI coding 工具，榜单数字易缺失、过时或被营销话术干扰；同一工具在不同页面说法不一致时无权威基准裁决。
- MCP `run_benchmark` 工具存在（`mcp_server/tools/benchmark_tools.py`）但只做自身能力评测，从不作为竞品性能榜单的数据源接入。

## 2. 目标设计

1. **权威榜单直连**：`BenchmarkSourceProvider`（设计文档 23）直接抓取/拉取权威榜单——SWE-bench Verified、Aider polyglot leaderboard、Terminal-Bench、LMArena 等——按竞品名匹配分数。
2. **榜单优先 + 页面兜底**：`PerformanceAnalyzer` 的优先级改为 **榜单证据 > 官网/文档页数字**；两者冲突时以榜单为准并在报告注明来源（避免"谁准"争议）。
3. **可缓存 + 新鲜度**：榜单结果按 `config.collector.cache_ttl_seconds` 缓存；带上 `retrieved_at` 供设计文档 26（新鲜度/时间线）消费，数字缺失/过期时明确标 `[PARTIAL]`。

## 3. 模块/接口设计

### 3.1 `collector/providers/benchmark_source.py`

```python
class BenchmarkSourceProvider(ExternalSourceProvider):   # 实现设计文档 23 协议
    kind = "benchmark"
    name = "benchmark_board"

    BOARDS = {
        "swe_bench_verified": ("https://www.swebench.com/", "SWE-bench Verified"),
        "aider_polyglot":     ("https://aider.chat/docs/leaderboards/", "Aider polyglot"),
        "terminal_bench":     ("https://www.terminal-bench.com/", "Terminal-Bench"),
        "lm_arena":           ("https://lmarena.ai/leaderboard", "LMArena"),
    }

    def fetch_scores(self, competitor: str) -> dict[str, BenchmarkScore]:
        """返回 {board: BenchmarkScore(score, metric, retrieved_at, source_url)}"""
```

- 抓取用 `web_extract`（MCP）；失败返回空 dict（正常降级），不阻塞主流程。
- `BenchmarkScore` 放 `domain_types/observation.py` 或 `domain_types/benchmark.py`（dataclass，含 `board / metric / score / unit / retrieved_at / source_url`）。

### 3.2 `analyzers/performance_analyzer.py` 增强

```python
def analyze(self, observation, gap, context) -> AnalysisResult:
    board_scores = context.benchmark_scores or {}     # 注入：榜单直连结果
    page_numbers = self._extract_page_numbers(observation.raw_text)
    merged = _merge(board_scores, page_numbers)       # 榜单优先，页面兜底
    # 输出 benchmark_scores: list[dict]（含 board/score/来源/时间）+ 置信度
```

- `_merge` 规则：同指标时榜单 > 页面；仅有页面 → 置信度降档；均无 → `[PARTIAL]` 注明"无权威榜单数据"。

### 3.3 注入路径

- `GapExecutor` 分析前把 `context.benchmark_scores = provider.fetch_scores(competitor.name)` 注入 `AnalysisContext`（仅 `performance` 缺口触发，避免额外开销）；provider 由 `CompetitorAnalysisAPI.__init__` 装配（设计文档 23）。

## 4. 接入方式

```
设计文档 23 路由：performance 缺口 → BenchmarkSourceProvider 候选（trust 0.9，榜单优先）
  → GapExecutor.fetch_candidate 调 fetch_scores → 注入 context.benchmark_scores
  → PerformanceAnalyzer._merge(榜单, 页面) → 报告/矩阵
```

- 无网络 / provider 失败 → `benchmark_scores={}` → 完全回退到现状（页面抽取），行为不劣化。

## 5. 验证方式

- **单测（Provider）**：mock `web_extract` 返回榜单 HTML → `fetch_scores` 解析出各 board 分数；抓取失败 → 空 dict 不抛异常。
- **单测（合并优先级）**：构造榜单 62% vs 页面 58% → 报告取 62% 且注明来源榜单；仅页面 → 置信度降档；均无 → `[PARTIAL]`。
- **单测（新鲜度）**：`retrieved_at` 写入分数对象；超过 TTL 后重抓（mock 计数验证）。
- **集成**：mock 榜单 + 固定页面，`analyze("Cursor", dimensions=["performance"])` 报告 benchmark_scores 来自榜单且带 source_url。
- **评测**：新增 performance 用例含"榜单与页面冲突取榜单"的 ground truth（设计文档 29）。
- **回归**：无 provider / 抓取失败时输出与现状一致；全量测试零真实网络。

## 6. 实现优先级与工作量

- 优先级：**中**（P1；数字权威性影响报告可信度，但非 0 维度类致命伤）。
- 工作量：约 1.5-2 天。
  - `BenchmarkScore` + Provider + 榜单解析：1 天；
  - PerformanceAnalyzer `_merge` + 注入路径：0.5 天；
  - 测试（Provider/合并/集成）：0.5 天。
- 前置：设计文档 23（provider 协议与装配）；无前置可先做 Provider 独立单测。
