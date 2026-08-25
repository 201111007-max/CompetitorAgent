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
  max_iterations: 10          # Lead ReAct 最大步数（设计文档 49：步数上限）
  max_parallel_subagents: 4   # 并行子代理上限
  token_high_water_mark: 120000  # 上下文 token 高水位，触发压缩
  token_compression_target: 80000 # 压缩后目标 token

# ===== 执行调度（设计文档 62 §3.8：硬上限，不再有 mode 决策开关）=====
# 并行与否归 Lead 决策（delegate 的 parallel+reason），代码只守硬上限。
execution:
  max_parallel_subagents: 4   # 并行子代理硬上限（= DelegateRunner 默认并发）
  max_discover_candidates: 10 # 候选竞品数硬上限（delegate 工具内收敛，注册维度不裁）

# ===== 维度清单 =====
dimensions:
  enabled: [feature, pricing, performance, ecosystem, sentiment, roadmap]

# ===== 数据源 =====
collector:
  cache_ttl_seconds: 86400   # 缓存 TTL（1 天）
  max_retries: 2
  timeout_seconds: 20
  rate_limit_per_second: 2   # 每源限速
  use_playwright: false      # SPA 采集开关（延迟安装依赖）
  user_agent: "competitor-agent/0.1"
  enable_external_sources: false  # 外部源多源路由（设计文档 23）：默认关，无网络/Key 测试安全

# ===== LLM =====
llm:
  model: "deepseek-chat"
  temperature: 0.1
  max_tokens: 2048
  fallback_models: []        # 主模型重试耗尽后的回退模型链（设计文档 36）
  timeout: 120
  max_retries: 3
  pricing_per_1k:            # 计价（美元/千 token，设计文档 46）
    input: 0.0003
    output: 0.0006

# ===== 记忆 =====
memory:
  enabled: true
  data_dir: "~/.competitor_agent"
  session_ttl_days: 30
  skills_max_per_competitor: 50
  evolution_window: 30       # L4 成功率统计窗口（天）

# ===== 报告 =====
report:
  include_confidence: true
  include_evidence_urls: true
  output_dir: "reports/competitor"
  export_json: true          # 结构化 JSON 导出（设计文档 28）
  comparison_dir: "reports/comparison"

# ===== 新鲜度 / 陈旧度（设计文档 26）=====
freshness:
  dimension_ttl_days: {pricing: 7, performance: 14, feature: 30, ecosystem: 30, sentiment: 7, roadmap: 14}
  refresh_check_enabled: true

# ===== 多 Agent LLM 主导编排（设计文档 49/62）=====
# run() 统一入口 = Lead ReAct 编排：make_plan → delegate 维度/候选子 Agent → 复核工具
# →（DISCOVERY 可 web_search_candidates 枚举 / 多竞品可 aggregate_report 聚合）→ Final Answer。
subagents:
  enabled: true             # 主路径开关（Lead 编排委派子 Agent）
  max_concurrent: 3         # delegate 一次最大并发子 Agent 数（对齐 execution.max_parallel_subagents）
  timeout_seconds: 60       # 子 Agent 单次执行超时

# ===== ReAct 循环压缩（设计文档 56 M1 Q4）=====
agent:
  max_history_steps: 8      # 子 Agent 工具步超过后折叠旧步为摘要（默认 8，行为不变）

# ===== Lead 编排（设计文档 62 §3.8）=====
# 迭代次数限制已移除（Lead max_steps=None 无限循环，靠 LLM 自然收敛 Final Answer）
lead:
  max_history_steps: 12        # Lead 上下文压缩保留步数（透传 ReactAgent._compress_history）

tools:
  validate_facts: true      # 复核工具（事实/数值冲突核验）注册
  detect_conflict: true     # 跨维度冲突检测工具注册
  check_freshness: true     # 新鲜度查询工具注册
  select_source: true       # 选源工具注册（确定性候选由代码生成）

# ===== 安全（Web/MCP）=====
security:
  cors_origins: ["http://localhost:8000"]
  auth_token: ""            # 优先从环境变量 COMPETITOR_AUTH_TOKEN 读取

# ===== 可观测性 =====
observability:
  log_level: "INFO"
```

---

## 3. 字段语义速查

| 字段 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `budget.max_iterations` | int | 10 | Lead ReAct 最大步数，防死循环（设计文档 49） |
| `budget.token_high_water_mark` | int | 120000 | 上下文高水位，触发压缩 |
| `dimensions.enabled` | list | 6 项 | 实际执行维度白名单 |
| `collector.cache_ttl_seconds` | int | 86400 | 采集缓存有效期 |
| `collector.use_playwright` | bool | false | SPA 采集开关（延迟安装依赖） |
| `collector.enable_external_sources` | bool | false | 外部源多源路由（设计文档 23），默认关保证离线测试安全 |
| `subagents.enabled` | bool | true | 主路径开关（设计文档 49：Lead ReAct 编排委派维度子 Agent） |
| `subagents.max_concurrent` | int | 3 | delegate 一次最大并发子 Agent 数 |
| `subagents.timeout_seconds` | float | 60 | 子 Agent 单次执行超时 |
| `tools.validate_facts` / `detect_conflict` / `check_freshness` / `select_source` | bool | true | Lead 复核工具注册开关（设计文档 49） |
| `freshness.dimension_ttl_days` | dict | 6 维 | 各维度新鲜度 TTL（设计文档 26） |
| `memory.data_dir` | str | ~/.competitor_agent | 记忆/向量库/凭据库根目录 |
| `report.include_evidence_urls` | bool | true | 报告附证据链接（防幻觉透明化） |
| `security.auth_token` | str | "" | Web/MCP 认证 Token（优先环境变量 `COMPETITOR_AUTH_TOKEN`） |

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

- 非法配置 → 启动时立即报错（fail-fast），不静默用默认值。
- 新增字段必须补 `tests/unit/config/test_config.py`。
