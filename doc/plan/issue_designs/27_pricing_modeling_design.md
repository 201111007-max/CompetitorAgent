# 设计文档 27 — 定价分层 / 用量建模增强

> 对应 `implementation_plan.md` §12.3 #6（P2）「定价分层/用量建模弱」。
> 依赖：`analyzers/pricing_analyzer.py`、设计文档 28（结构化导出）。

## 1. 问题现状

- `analyzers/pricing_analyzer.py` 主要从定价页抓取标价，测试覆盖轻；对 AI coding 工具普遍存在的"免费档 / Pro / Business / Enterprise + 按量（请求 / 模型档位）混合"成本结构捕捉不足。
- 现状常只抓"单档标价"而漏掉真实成本结构：免费档限制、按量计费单价、模型档位差异、团队/企业档隐藏定价、年付折扣。
- 报告无法回答用户最关心的**真实成本**（"以我每天 100 次请求的中等用量，月成本多少"）。

## 2. 目标设计

1. **结构化定价模型**：输出 `PricingPlan`（免费档/付费档：名称、月付/年付价格、关键限额）与 `UsageBilling`（单位、单价、模型档位表）。
2. **用量成本估算**：给定典型用量场景（如轻量 30 次/天、中等 100 次/天、重度 1000 次/天），按各档限额与按量单价估算月成本，产出 `cost_scenarios`。
3. **模型档位**：提取涉及基础/标准/高级模型档位的差异定价（AI coding 工具常见"按模型档位计价"）。
4. **置信度与缺失标注**：隐藏定价（企业档需联系销售）明确标"需询价"，不编造数字；复用证据链。

## 3. 模块/接口设计

### 3.1 定价模型 `domain_types/pricing.py`

```python
@dataclass
class PricingPlan:
    tier: str                # free / pro / business / enterprise / ...
    name: str = ""
    monthly_price_usd: float | None = None
    annual_price_usd: float | None = None
    limits: dict[str, str] = field(default_factory=dict)   # 请求上限/并发/座位等
    requires_quote: bool = False                           # enterprise 询价

@dataclass
class UsageBilling:
    unit: str = "request"          # request / token / seat / agent-run
    per_unit_usd: float | None = None
    model_tiers: dict[str, float] = field(default_factory=dict)  # tier → 单价
    included_units: int | None = None                      # 档内包含量

@dataclass
class PricingProfile:
    plans: list[PricingPlan]
    usage: UsageBilling | None = None
    cost_scenarios: dict[str, float | None] = None         # light/medium/heavy → 月成本 USD
    as_of: str = ""
    source_urls: list[str] = field(default_factory=list)
```

### 3.2 `analyzers/pricing_analyzer.py` 增强

```python
def analyze(self, observation, gap, context) -> AnalysisResult:
    profile = self._extract_profile(observation.raw_text, source_urls=[...])
    profile.cost_scenarios = self._estimate_costs(profile, scenarios=("light","medium","heavy"))
    # → AnalysisResult 附 PricingProfile（payload）
```

- `_estimate_costs`：每档取 `monthly_price`；超限额用量按 `usage.per_unit_usd` 追加；无按量数据时 `None`（不估算，避免幻觉）。
- 输出在报告正文呈现定价表 + 成本场景表；进入品类矩阵时按 `[OK]>[PARTIAL]>[N/A]` 与置信度排序（复用 `markdown_renderer`）。

### 3.3 结构化落盘

- `PricingProfile` 随报告序列化到 JSON（设计文档 28 的导出 schema 含 `pricing.profile`），供成本对比与设计文档 26 的价格变化 diff。

## 4. 接入方式

```
PricingAnalyzer.analyze → PricingProfile → AnalysisResult.payload
  └─ report_builder 把 pricing 结果渲染为定价表/成本场景表
  └─ 导出（设计文档 28）与时间线 diff（设计文档 26：price_change 事件读 profile.monthly_price）
```

- 无需改动规划/采集路径，纯分析器内增强 + 领域模型。

## 5. 验证方式

- **单测（结构抽取）**：构造含"Free $0 / Pro $20/mo / Teams $40/mo / Ultra $60/mo + 每千请求 $0.5"的页面 → `_extract_profile` 产出 4 档 + usage 单价正确。
- **单测（成本估算）**：轻量用量不超限额 → 月成本 = 档价；中等用量超限额 → 档价 + 按量追加；无按量数据 → `None`（不编造）。
- **单测（询价标注）**：enterprise 无价 → `requires_quote=True`。
- **集成**：`analyze("Cursor", dimensions=["pricing"])` 报告含定价表与成本场景；回归：现有 pricing 测试（简单标价）仍通过。

## 6. 实现优先级与工作量

- 优先级：**中低**（P2；增强可信度与差异化，非致命缺口）。
- 工作量：约 1.5 天。
  - 领域模型 + 结构抽取：0.5 天；
  - 成本估算 + 询价标注：0.5 天；
  - 渲染 + 测试 + 回归：0.5 天。
- 前置：无；与设计文档 28（导出）和 26（diff）共享 `PricingProfile`。
