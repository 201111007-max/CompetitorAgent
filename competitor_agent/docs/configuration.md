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
  fallback_analyzer: true    # LLM 不可用时规则降级
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

# ===== 可观测性 =====
observability:
  log_level: "INFO"
  tracing: true
  metrics: true
  langfuse_enabled: false
  langfuse_public_key_env: "LANGFUSE_PUBLIC_KEY"
  langfuse_secret_key_env: "LANGFUSE_SECRET_KEY"
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
| `llm.fallback_analyzer` | bool | true | 无 LLM 时规则降级 |
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
