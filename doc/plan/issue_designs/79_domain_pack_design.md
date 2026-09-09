# 设计文档 79 —— 第二十九轮：Domain Pack 配置化（工单 5：领域可插拔）

> **实施说明（2026-09-09，全落地）**：
> ① **模型与加载**（新 `core/domain_pack.py`）：`DimensionSpec`（name/description/tools/skills/data_sources）/`RegistrySeed`/`DomainPack` + `load_domain_pack`（**防呆 §4.4**：缺 domain/dimensions/registry_seeds 段、维度重复 → 可读 ValueError；文件缺失 → FileNotFoundError）+ `active_pack_name`（模块覆盖 > env `COMPETITOR_AGENT_ACTIVE_PACK` > `config.domains.active_pack`，缺省 coding_agent）+ `set_active_pack`（运行时切换并同步重建竞品注册表/子 Agent 注册表/技能加载器缓存）+ **双保险**：yaml 目录缺失/损坏 → 内联 coding 默认（`agent/subagent_registry_defaults.py`，与下沉前逐位一致）。
> ② **pack 文件**：`config/domains/coding_agent.yaml`（第一实例：6 维度 tools/skills/descriptions + 13 竞品 seeds + 权重，**与下沉前字面量逐位等价**——等价性冒烟断言 dims/tools/skills/desc/weights/registry 全 NONE-diff）+ `config/domains/saas_pm.yaml`（第二实例：pricing/feature/**integrations/adoption**/sentiment/roadmap + notion/linear/asana seeds + 独立权重，**全文无 coding agent 叙事**）。`DomainsConfig(active_pack)` + review_config.yaml `domains` 段。
> ③ **三处解耦**：**L1** `SubagentRegistry.from_pack(pack)` + `get_subagent_registry` 按 pack 名缓存构建（失败回退内联默认）+ `reset_subagent_registry`；**L2** `competitor_registry.COMPETITOR_REGISTRY` 由 pack `registry_seeds` 构建（`reload_registry_from_pack`；`canonicalize/resolve_competitor` 语义不变）+ `Competitor.category` 默认值 `"ai_coding_agent"`→`""`（**有意行为变更**，由 pack `category_label` 填充：注册表 seeds、`CompetitorDiscoverer._to_competitors`）；**L3** `react_schemas.pack_dimensions` 运行时枚举（DIMENSIONS 保留为 coding 静态镜像）+ `make_plan(allowed_dimensions)` 按 pack 裁剪 enum（三处调用经 `self._domain_pack.dimension_names` 注入）+ `ReportBuilder(dimension_weights)` 按注入（api 装配 `self._domain_pack`）。**L4** `SkillLoader` 叠加扫描 `skills/domains/<active_pack>/`（主目录同名优先）+ `skills/domains/saas_pm/` 8 个领域 skill。
> ④ **测试**：`test_domain_pack_79.py` 16——4.1 回归基线（yaml==内联逐位/注册表 seeds 等价/注册表形状/make_plan 6 维通过）+ 4.2/4.3 可插拔（saas_pm 切换后维度/注册表/品类/技能/发现品类注入/报告 pack 权重 + **零 coding agent 词汇 grep**）+ 4.4 防呆 5 条 + 兼容（from_pack/competitor 命名空间/reset）。回归：agent+domain+registry+discoverer 266、core+evaluation+config 440（4 失败为基线即有 chroma 文件锁环境问题，stash 验证）、facade 208 全绿；`test_domain_types` category 默认值断言随 L2 有意变更更新。

> 目标：把 6 个维度子 Agent 的定义从硬编码 dict 下沉为 yaml 配置（Domain Pack），并**同步解耦三处领域渗漏**；以第二个领域（SaaS 项目管理工具）全链路独立出报告为验收——证明架构不是硬编码。
>
> 本文档为**设计**（不实现）。
>
> **已确认决策（doc 75 §2）**：
> ① 验收标准升级：不是「yaml 能加载」，而是「第二个领域 pack 全链路（注册表/维度/数据源）独立，报告全文不出现 coding agent 痕迹」；
> ② 第二 pack 领域 = SaaS 项目管理工具（Notion / Linear / Asana）；
> ③ 每工单一分支，benchmark 全绿为合入门槛。

---

## 1. 问题现状（领域渗漏不止一处，均已核对）

| # | 渗漏点 | 位置 | 现状 |
|---|--------|------|------|
| L1 | 子 Agent 三张硬编码 dict | `agent/subagent_registry.py`：`_SUBAGENT_TOOLS`（pricing→analyze_pricing、ecosystem→github_* 等）/ `_SUBAGENT_SKILLS` / `_SUBAGENT_DESCRIPTIONS` | 模块级常量，`SubagentConfig.for_dimension/for_competitor` 直接读 |
| L2 | 竞品品类与注册表 | `domain_types/competitor.py:13` `category: str = "ai_coding_agent"`；`core/competitor_registry.py` `COMPETITOR_REGISTRY` 预注册 8 个 coding agent | 换领域即失真 |
| L3 | 维度枚举 | `agent/react_schemas.py::DIMENSIONS = [pricing, feature, performance, ecosystem, sentiment, roadmap]`（对齐 `DimensionType` 枚举） | PLAN_SCHEMA/REPORT_SCHEMA/子 Agent 注册表全部引用此 6 维 |
| L4（顺带） | skills/ 9 个 md（`pricing_analysis`…）| 注入清单按维度名约定 `f"{dim}_analysis"` | pack 需自带 skill 文件与映射 |

---

## 2. 目标设计

### 2.1 Pack 文件格式

```
competitor_agent/config/domains/
├── coding_agent.yaml          # 第一实例：现有 6 维度原样下沉（行为零变化的回归基线）
└── saas_pm.yaml               # 第二实例：验证可插拔
```

```yaml
# coding_agent.yaml（示例节选）
domain: coding_agent
category_label: "ai_coding_agent"
dimensions:
  - name: pricing
    description: "分析竞品定价：套餐档位、按量计费、月付/年付价格与成本场景估算。"
    tools: [web_extract, web_search, analyze_pricing]
    skills: [pricing_analysis, fact_verification, confidence_disclosure]
    data_sources:                              # 数据源清单（声明式，供 skill/prompt 引用）
      - {name: official_pricing_page, notes: "定价页变动频繁，引用需带 as_of"}
  - name: ecosystem
    tools: [web_extract, web_search, github_stars, github_releases, github_commits]
    # ...
registry_seeds:                                # L2 解耦：预注册竞品随 pack 提供编码
  - name: cursor
    aliases: [anysphere, cursor ai]
    official_links: {home: "https://www.cursor.com", pricing: "..."}
    external_refs: {github_repo: "getcursor/cursor"}
default_dimension_weights: {pricing: 0.25, feature: 0.25, performance: 0.2, ecosystem: 0.1, sentiment: 0.1, roadmap: 0.1}
```

`saas_pm.yaml` 同构：维度如 `pricing/feature/integrations/adoption/sentiment/roadmap`；数据源换为 help docs / changelog / G2 类页；registry_seeds = notion/linear/asana；**全文无 coding agent 叙事**（验收硬指标）。

### 2.2 加载与解耦落点

| 渗漏点 | 解耦后 |
|--------|--------|
| L1 | `DomainPackLoader`（复用 skills loader 的 frontmatter/缓存范式）→ `SubagentRegistry.from_pack(pack)`；`get_subagent_registry()` 改为按激活 pack 构建（代码内保留 `coding_agent` 内联默认作为 yaml 缺失时的兜底，行为与现状逐位一致） |
| L2 | `Competitor.category` 默认值改 `""`，由 `CompetitorDiscoverer._to_competitors` / registry 返回条目按 pack `category_label` 填充；`COMPETITOR_REGISTRY` 模块常量改为 `Registry.from_pack(pack)` 构建（`canonicalize/resolve_competitor` 语义不变） |
| L3 | `react_schemas.DIMENSIONS` 保留为 coding pack 的静态镜像（测试/兼容引用）；运行时 schema 由 `plan.dimensions ∩ pack.dimensions` 决定：`PLAN_SCHEMA.dimensions.enum`、子 Agent 注册、ReportBuilder 权重（`_DIMENSION_WEIGHTS`）全部改为按 pack 注入 |
| L4 | pack 声明 skills 名；`SkillLoader` 增 pack 目录解析（`skills/domains/<pack>/`），缺失 skill 静默跳过（既有纪律） |

### 2.3 配置与切换

```yaml
# review_config.yaml
domains:
  active_pack: "coding_agent"     # 默认不变；切 saas_pm 即整体换领域
```

`AppConfig` 增 `DomainsConfig`；`load_config()` 时加载激活 pack 并注入装配层（doc 78 拆分后落 `assembly.py`，未实施前落 `api.py.__init__`）。

---

## 3. 接入方式

- `agent/subagent_registry.py`：`SubagentRegistry.from_pack(pack)` 新增；`build_subagent`/`build_subagent_dispatcher` 入参不变（内部读注册表实例）。
- `core/competitor_registry.py`：`resolve_competitor/canonicalize` 保持模块函数（内部查激活 pack 的注册表实例）。
- `agent/react_schemas.py`：`DIMENSIONS` 保留；新增 `pack_dimensions(config)` 运行时取值；`make_plan` 校验改按 pack 维度。
- `core/report_builder.py`：`_DIMENSION_WEIGHTS` → `pack.default_dimension_weights`。
- skills：`competitor_agent/skills/domains/saas_pm/*.md` 新增 6+2 个。

## 4. 验证方式

| # | 验收项 | 通过标准 |
|---|--------|---------|
| 4.1 | 回归基线 | `active_pack=coding_agent` 下全量 pytest + benchmark 门禁逐位不变（yaml 下沉 = 现状等价改写） |
| 4.2 | 可插拔 | `active_pack=saas_pm` 跑「分析 Notion」真实出 6 维报告；报告全文 grep 无 `coding|AI IDE|代码补全` 等 coding agent 词汇 |
| 4.3 | 三处解耦 | saas_pm 报告的 category/注册表/维度均来自 saas_pm.yaml（单测断言来源） |
| 4.4 | 防呆 | pack yaml 缺维度/skill/registry 段 → 启动报可读错误或安全回退（不静默半装配） |
| 4.5 | 工程纪律 | ruff/mypy 干净；每工单一分支 |

## 5. 实现优先级与工作量

P1，约 2.5 天（loader + L1 下沉 1 天；L2/L3 解耦 1 天；saas_pm pack + 全链路验证 0.5 天）。依赖：建议 doc 78 拆分后实施（装配点更干净）；被依赖：无。

## 6. 核心技术点总结

1. **「yaml 能加载」≠ 可插拔**：真正的验收是第二个领域出报告且零领域渗漏——L2/L3 两处（品类默认值、维度枚举）是最容易被漏掉的渗漏点，本设计显式列出。
2. **coding pack 下沉即回归网**：第一个 pack 的内容与现状逐位等价，任何行为差异都是 bug 而非特性。
3. **schema 的运行时化要克制**：`PLAN_SCHEMA` 等静态 schema 保留（兼容/测试引用），运行时才按 pack 裁剪——避免为可插拔引入两套真相。
