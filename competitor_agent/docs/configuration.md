# 配置说明（configuration.md）

> `config/review_config.yaml` 全部字段的含义、默认值与作用范围。
> 变更配置需同步更新本文档与相应单元测试。

---

## 1. 配置文件位置

- 默认：`competitor_agent/config/review_config.yaml`
- 运行时覆盖：环境变量 `COMPETITOR_AGENT_CONFIG` 指向自定义文件。

---

## 2. 完整配置示例

```yaml
# ===== 预算（BudgetController）=====
budget:
  max_iterations: 10          # 战术循环最大迭代轮数
  max_parallel_subagents: 4   # 并行子代理上限
  cost_limit_usd: 1.0         # 单次分析 LLM 成本上限（美元）
  token_high_water_mark: 120000  # 上下文 token 高水位，触发压缩
  token_compression_target: 80000 # 压缩后目标 token

# ===== 终止阈值 =====
termination:
  core_priority_threshold: 8  # 核心缺口优先级判定线
  core_confidence: 0.8        # 核心缺口关闭所需置信度
  satisfaction_min_gap: 5     # 关闭缺口数占比较低线（触发核心满足）

# ===== 维度清单与预算分配 =====
dimensions:
  enabled: [feature, pricing, performance, ecosystem, sentiment, roadmap]
  default_budget:            # 各维度默认迭代预算
    feature: 3
    pricing: 2
    performance: 3
    ecosystem: 2
    sentiment: 2
    roadmap: 1
  analysis_order: [pricing, feature, performance, ecosystem, sentiment, roadmap]

# ===== 数据源 =====
collector:
  cache_ttl_seconds: 86400   # 缓存 TTL（1 天）
  max_retries: 2
  timeout_seconds: 20
  rate_limit_per_second: 2   # 每源限速
  use_playwright: false      # M1 关；M2 接入后按需开
  user_agent: "competitor-agent/0.1"

# ===== LLM =====
llm:
  model: "deepseek-v4-flash"
  temperature: 0.1
  max_tokens: 2048
  cache_enabled: true

# ===== 记忆 =====
memory:
  data_dir: "~/.competitor_agent"
  session_ttl_days: 30
  skills_max_per_competitor: 50
  evolution_window: 30       # L4 成功率统计窗口（天）

# ===== 报告 =====
report:
  markdown: true
  include_confidence: true
  include_evidence_urls: true
  output_dir: "reports/competitor"

# ===== 多 Agent 领域差异化编排（设计文档 49）=====
orchestration:
  reviewer:
    enabled: false          # 对抗式评审第 5 角色：Validator→Reviewer→Reporter，needs_revision 回灌修订 ≤1 轮，超限标注 [REVIEWED]
  freshness_delegation:
    enabled: false          # 新鲜度驱动委派：过期维度优先采集、新鲜维度跳过采集复用归档、时间线事件提权重采
  cross_dimension_conflict:
    enabled: true           # 跨维度冲突检测：同源（content_hash）同键异值 → 冲突标注/评审
  source_dedup:
    enabled: true           # 跨竞品同源去重：URL→content_hash 缓存，多竞品共享源省抓取
  experience_routing:
    enabled: true           # 经验路由委派：按 L4 模式排序缺口执行顺序（纯排序不改缺口集合）

# ===== 可观测性 =====
observability:
  log_level: "INFO"
```

---

## 3. 字段语义速查

| 字段 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `budget.max_iterations` | int | 10 | 战术循环最大迭代，防死循环 |
| `budget.cost_limit_usd` | float | 1.0 | 成本硬上限，超额强制终止 |
| `budget.token_high_water_mark` | int | 120000 | 上下文高水位，触发 Compressor |
| `termination.core_priority_threshold` | int | 8 | ≥ 此优先级为核心缺口 |
| `termination.core_confidence` | float | 0.8 | 核心缺口置信度达标线 |
| `dimensions.enabled` | list | 6 项 | 实际执行维度白名单 |
| `dimensions.default_budget` | dict | — | 维度→迭代预算（可被战略循环覆盖） |
| `collector.cache_ttl_seconds` | int | 86400 | 采集缓存有效期 |
| `collector.use_playwright` | bool | false | SPA 采集开关（延迟安装依赖） |
| `orchestration.reviewer.enabled` | bool | false | 对抗式评审（设计文档 49）：低置信 COMPLETE 命中维度回灌修订 ≤1 轮，超限标注 `[REVIEWED]` |
| `orchestration.freshness_delegation.enabled` | bool | false | 新鲜度驱动委派：新鲜维度跳过采集复用归档、过期维度照常采集、时间线事件提权重采 |
| `orchestration.cross_dimension_conflict.enabled` | bool | true | 跨维度冲突检测：同源（content_hash）同键异值 → 报告「跨维度冲突备注」 |
| `orchestration.source_dedup.enabled` | bool | true | 跨竞品同源去重：URL→content_hash 缓存，按"单次分析"为界（不破坏时间线/新鲜度语义） |
| `orchestration.experience_routing.enabled` | bool | true | 经验路由委派：按 L4 模式排序缺口执行顺序 |
| `memory.data_dir` | str | ~/.competitor_agent | 记忆/向量库/凭据库根目录 |
| `report.include_evidence_urls` | bool | true | 报告附证据链接（防幻觉透明化） |

---

## 4. 凭据环境变量（SecretVault 解析顺序）

| 用途 | 变量 | 顺序 |
|------|------|------|
| LLM | `OPENAI_API_KEY` > `DEEPSEEK_API_KEY` > `LLM_API_KEY` | 复用 dota_helper 的 get_first |
| GitHub | `GITHUB_TOKEN` | 可选，无则公开限额 |
| 追踪 | `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` | 可选 |

> 全部经 SecretVault（加密落盘 `~/.competitor_agent/vault.key`），禁止硬编码。

---

## 5. 校验规则

- 配置加载时校验：`enabled` 维度必须在 `default_budget` 有预算；终止阈值 ∈ [0,1]。
- 非法配置 → 启动时立即报错（fail-fast），不静默用默认值。
- 新增字段必须补 `tests/unit/config/test_config.py`。
