# Prompt 规范文档（prompts.md）

> 定义竞品分析 Agent 使用的全部 Prompt 模板、动态注入点与版本管理。
> 原则：Prompt 与代码分离、集中管理、可版本化、可测试。

---

## 1. Prompt 目录约定

```
competitor_agent/agent/prompts/
├── react_system.py        # ReAct 系统提示（含工具注入占位）
├── strategic_planner.py   # 规划阶段提示（任务→缺口清单）
├── dimension_analyzer.py  # 维度分析提示（按 DimensionType 细分）
├── fallback.py            # 降级分析提示
├── validator.py           # 事实校验提示
├── reporter.py            # 报告汇总提示
└── __init__.py            # 统一导出 + 模板版本
```

---

## 2. 动态注入点（占位符约定 `{PLACEHOLDER}`）

| 注入点 | 占位符 | 内容来源 | 阶段 |
|--------|--------|---------|------|
| 任务描述 | `{TASK}` | Facade API 入参 | 全部 |
| 工具描述 | `{TOOLS_DESCRIPTION}` | ToolRegistry 序列化（含参数 schema） | ReAct |
| 已沉淀技能 | `{SKILLS}` | L3 SkillStore.retrieve(competitor) | 规划+ReAct |
| 历史失败教训 | `{FAILURES}` | L4/evolution_memory | 规划+ReAct |
| 知识库片段 | `{RAG_CONTEXT}` | RagRetriever.top_k(competitor, dimension) | ReAct |
| 当前缺口清单 | `{GAPS}` | CompetitorStrategy.gaps | 战术循环 |
| 已有证据 | `{EVIDENCE}` | InfoGap.evidence 序列化 | 战术循环 |
| 上一轮结果 | `{PREV_RESULT}` | 上一轮 DimensionResult | Reflection |

---

## 3. 各 Prompt 模板要点

### 3.1 react_system.py（ReAct 系统提示）

```
你是竞品情报分析 Agent。你通过 Thought→Action→Observation 循环完成任务。

工具列表：
{TOOLS_DESCRIPTION}

输出格式严格为：
Thought: <推理>
Action: <工具名>
Action Input: <JSON 参数>
（或）
Final Answer: <最终结论>

记忆注入：
【已沉淀技能】
{SKILLS}
【历史失败教训】
{FAILURES}
【知识库片段】
{RAG_CONTEXT}

规则：
1. 每一步结论必须引用证据来源 URL。
2. 无法获取数据时输出 "DATA_UNAVAILABLE" 而非编造。
3. 禁止执行任何与信息采集无关的动作。
```

### 3.2 strategic_planner.py（规划）

```
任务：{TASK}
已识别竞品：{COMPETITOR}
历史技能：{SKILLS}

请输出信息缺口清单，JSON 格式：
[
  {"field": "pricing", "priority": 9, "initial_confidence": 0.1,
   "hint_sources": ["official_pricing_page"]},
  ...
]
约束：
- 覆盖 dimension: feature/pricing/performance/ecosystem/sentiment/roadmap
- 历史技能中已验证的源优先作为 hint_sources
```

### 3.3 dimension_analyzer.py（维度分析）

```
维度：{DIMENSION}
缺口：{GAPS}
观察数据：
{RAW_OBSERVATION}

请提炼结论，JSON：
{"summary": "...", "details": {...}, "confidence": 0.0-1.0}
约束：仅基于给定观察数据，不得补充未经证据的断言。
```

### 3.4 validator.py（事实校验）

```
待校验结论：{CONCLUSION}
可用证据：{EVIDENCE}
历史结论（冲突检测）：{HISTORY}

输出：
{"pass": true/false, "issues": ["..."], "action": "accept"|"reject"|"cross_verify"}
```

---

## 4. Prompt 版本管理

1. 每个模板文件带 `__version__ = "1.0"` 与变更注释。
2. 模板变更必须同步更新对应单元测试（断言关键约束句存在）。
3. 线上切换 Prompt 走配置：`config/prompts_version.yaml`。
4. 禁止在代码中硬编码 Prompt 文本（复用 bugs.md #P1 Prompt 管理教训）。

---

## 5. 测试策略

| 测试 | 断言 |
|------|------|
| 模板存在性 | 每个版本号模板文件可 import，含全部必需占位符 |
| 注入正确性 | 构造假技能/知识，断言渲染后包含记忆片段 |
| 格式合规 | 用模板渲染喂给 LLM，解析回合法 JSON |
| 防护验证 | 恶意输入经注入防御后不泄漏系统指令 |

---

## 6. 降级路径

- LLM 不可用 → `fallback.py` + 规则抽取（如 pricing 页正则提取 `$NN/mo`）+ 缓存。
- 关键输出格式解析失败 → 重试一次，仍失败走规则降级。
