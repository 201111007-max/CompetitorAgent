# 数据源目录（data_sources.md）

> 竞品分析 Agent 的采集数据源清单、降级链、采集方式与反爬注意事项。
> 本文档随 collector/ 实现持续维护。所有数据源实现 `ICompetitorDataSource`。

---

## 1. 数据源分类

| 类别 | 覆盖维度 | 采集方式 | 可信度 |
|------|---------|---------|--------|
| 官方官网 | 功能/定价/生态 | 静态 HTML 或 Playwright | 高 |
| 官方文档/Changelog | 功能/路线图 | 文档站抓取 + RAG ingester | 高 |
| GitHub API | 生态/活跃度/版本 | REST API（Token 经 SecretVault） | 高 |
| 评测榜单 | 性能 | SWE-bench / Aider leaderboard 抓取 | 中高 |
| 社区评价 | 口碑 | HN / Reddit / 商店，采样 | 中 |
| 第三方资讯 | 生态/口碑 | 聚合站抓取 | 中 |

---

## 2. 降级链（SourceSelector 规则）

对每个缺口 `field`，定义候选源有序列表；前一个失败则换下一个。

### 示例：PRICING

```
1. official_pricing (官网定价页)
2. docs_pricing (官方文档 pricing 章节)        ← SPA 官网必挂时
3. third_party_overview (聚合定价站)          ← 可信度降档
4. cache (历史缓存，标 stale)
5. BLOCK 缺口（不编造，等待人工/下次）
```

### 示例：PERFORMANCE

```
1. benchmark_official (SWE-bench/Aider 官榜)
2. third_party_benchmark (第三方复测)
3. community_bench (社区测评帖，低可信)
4. cache → BLOCKED
```

### 降级语义
- 每降一格降可信度（`SourceEvidence.raw_level`）。
- 降级过程中把"该源失败"写进 evolution_memory（L4），下次直接提顺位。
- 全部失败 → 缺口 `BLOCKED`，报告如实标注，**禁止编造**。

---

## 3. 预置竞品清单（COMPETITOR_REGISTRY）

| 竞品 | 规范名 | 覆盖源 | 备注 |
|------|--------|--------|------|
| Claude Code | claude-code | official docs/pricing | Anthropic |
| Copilot | github-copilot | official, github api | GitHub |
| Cursor | cursor | official, pricing, changelog | SPA 需 Playwright |
| Windsurf | windsurf | official | — |
| Codex | openai-codex | official docs | OpenAI |
| Cline | cline | official, github | 开源 |
| Aider | aider | github, official | 开源 |
| Codeium/Windsurf 竞品 | windsurf | — | — |
| Trae | trae | official | ByteDance |

> 未知竞品 → 未注册走兜底 web 抓取 + 规划阶段确认。

---

## 4. 采集注意事项

| 注意点 | 处理 |
|--------|------|
| SPA 动态渲染 | `web_extractor.py` 检测：初始 HTML 无内容 → 自动升 Playwright（M2+） |
| 频率限制 | ToolGuard 每源令牌桶限速；避免瞬时打爆 |
| 缓存 | 命中缓存优先（config 调 TTL）；缓存带时间戳防过期结论 |
| User-Agent / 代理 | 统一 UA；异常网络走错误分类器 |
| 内容去重 | `evidence.content_hash` 去重，多源同结果减少分析 |
| 数据新鲜度 | 头部/正文带采集时间，报告按时间戳排序 |

---

## 5. GitHub 数据源（github_tools）

```
字段：stars / open_issues / releases（版本+日期） / commit_activity / contributing
API：GET /repos/{owner}/{repo}
Token：经 SecretVault.require("GITHUB_TOKEN")，未配置则按公开限额
限流：X-RateLimit 处理，60 次/h 公开额度；超限记录并降级
```

---

## 6. 评测 / 口碑源（benchmark / review）

| 源 | 方法 | 可信度 |
|----|------|--------|
| SWE-bench 官方 | 抓取 leaderboard | 高 |
| Aider benchmark 列表 | 抓取 html | 中高 |
| 社区口碑聚合 | 搜索 API 采样 top-N，标注样本量 | 中 |

> 口碑结论必须带样本量与时间窗（R13 缓解）。

---

## 7. 新增数据源流程

1. 实现 `ICompetitorDataSource`。
2. 注册到 `collector/data_source_registry.py`（含优先级与适用维度）。
3. 在 data_sources.md 补一条+降级链。
4. 写单测（respx/mock 页面）覆盖成功与失败两条路径。