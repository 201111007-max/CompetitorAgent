# RAG 真实命中样本（设计文档 93 §2.4）

> 采集日期：2026-09-12。真实任务沉淀：本机配置（`deepseek-v4-flash` @ Ark
> 端点，`.env` 注入）跑 3 个真实竞品分析（`分析 Cursor 定价维度`、
> `分析 Cursor 的 feature 与 roadmap 维度…` 等），Lead/子 Agent 经 `web_extract`
> 真实抓取 `cursor.com/pricing`、`docs.cursor.com/account/{pricing,usage}`、
> `cursor.com/changelog` 等页面，共摄入 **46 个片段**（`Cursor/web` 通用域 +
> `cursor/pricing` 维度域两条写路径）。
>
> 环境如实说明：本机未缓存 `BAAI/bge-small-zh-v1.5` 与 `BAAI/bge-reranker-v2-m3`
> 权重，向量层与精排层均按设计自动降级（启动日志
> `向量层状态: degraded` / `精排层状态: degraded`），下列分数为 hybrid 降级后的
> 词袋分（`src=lexical`）× 时效衰减因子（片段刚摄入，`decay≈1.0`）。
> 代理出网沙箱中 URL 守卫 DNS 预检不适用，样本采集配置置
> `block_private_urls: false`（与测试 `_OFFLINE_CFG` 同模式）。

## 命中样本

### 样本 1

- **query**: `Cursor pricing subscription`（competitor=cursor, dimension=pricing）
- **片段摘要**: `…through the Admin Dashboard. How does Cursor use my data? Privacy mode can be enabled in settings or by a team admin. When it is enabled, we guarant…`
- **来源 URL**: https://www.cursor.com/pricing
- **ingested_at**: 1789202267（2026-09-12T08:37:47Z，epoch 秒）
- **分数**: 融合分 0.3184（src=lexical）× 衰减因子 0.9999

### 样本 2

- **query**: `pricing`（competitor=cursor, dimension=pricing）
- **片段摘要**: `…See all model attributes on the Models & Pricing page. Name / Default Context / Max Context / Capabilities — Claude Fable 5.1 300k 1M, Claude Opus 5 300k 1M…`（模型定价表）
- **来源 URL**: https://docs.cursor.com/account/usage
- **ingested_at**: 1789202302（2026-09-12T08:38:22Z）
- **分数**: 融合分 0.1987（src=lexical）× 衰减因子 0.9999

### 样本 3

- **query**: `Cursor pricing subscription`（competitor=cursor, dimension=pricing）
- **片段摘要**: `…invoice-based billing and wire transfers, please contact us to discuss the Enterprise plan. How does usage-based pricing work? Every plan includes a s…`
- **来源 URL**: https://cursor.com/pricing
- **ingested_at**: 1789202267（2026-09-12T08:37:47Z）
- **分数**: 融合分 0.2498（src=lexical）× 衰减因子 0.9999

### 样本 4

- **query**: `AI code editor features`（competitor=cursor, dimension=feature）
- **片段摘要**: `…Grok Bot access ✓ Agentic code reviews with Bugbot ✓ Usage analytics to understand team behavior ✓ Team-wide privacy mode ✓ SAML/OIDC SSO — Get Teams…`（Teams 版功能清单）
- **来源 URL**: https://cursor.com/pricing
- **ingested_at**: 1789202267（2026-09-12T08:37:47Z）
- **分数**: 融合分 0.0869（src=lexical）× 衰减因子 0.9999

### 样本 5（Lead 通用域写入 + 时效衰减可观测）

- **query**: `AI code editor features`（competitor=cursor, dimension=feature）
- **片段摘要**: 同样本 4 的 Teams 功能清单片段，但为 Lead 早一轮摄入的
  `Cursor/web` 通用域副本（决策 4 的"重复摄取刷新"因 chunk_id 维度前缀不同
  不去重——`Cursor/web` 与 `cursor/pricing` 是两条独立写路径）
- **来源 URL**: https://cursor.com/pricing
- **ingested_at**: 1789202130（2026-09-12T08:35:29Z，比样本 4 早 137 秒）
- **分数**: 融合分 0.0869 × 衰减因子 **0.9998**（同文更老 137 秒 → 衰减略低，
  时效衰减在真实数据上可观测）

## 复现命令

```bash
# 真实分析（需要 .env 里的 LLM Key；COMPETITOR_AGENT_DATA_DIR 隔离数据目录）
set -a && . ./.env && set +a
export COMPETITOR_AGENT_DATA_DIR=/tmp/rag_samples_data \
       COMPETITOR_AGENT_CONFIG=<含 block_private_urls: false 的配置> \
       SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt   # 代理出网沙箱需要
python -m competitor_agent.cli analyze "分析 Cursor 定价维度"

# 命中截取（对沉淀的知识库直接检索）
python - <<'EOF'
from competitor_agent.knowledge_base.competitor_store import CompetitorStore
store = CompetitorStore(data_dir="/tmp/rag_samples_data")
for chunk, score, src in store.search_hybrid("Cursor pricing subscription", top_k=5):
    print(score, src, store.decay_factor(chunk), chunk.source_url, chunk.ingested_at)
EOF
```
