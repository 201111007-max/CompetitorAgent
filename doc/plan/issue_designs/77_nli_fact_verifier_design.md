# 设计文档 77 —— 第二十七轮：NLI 事实校验器（工单 2：snapshot/refetch 双模式 + 三态判定）

> 目标：把 `validate_facts`（现仅数值与原文核对）升级为**独立的报告级事实校验器**：
> 从报告抽取全部事实性断言 → 定位引用来源 → 获取来源原文 → NLI 判定，输出报告级幻觉率。
> 双角色复用：**产品功能**（报告发布前自查，接审批门）+ **评测组件**（benchmark 幻觉率新口径）。
>
> 本文档为**设计**（不实现）。
>
> **已确认决策（doc 75 §2）**：
> ① 双模式 `verify(mode="snapshot"|"refetch")`——评测用 snapshot 保确定性，产品侧发布前校验手动 refetch 保时效；
> ② **三态判定**（本评审新增）：`supported / contradicted / superseded`——矛盾 ≠ 幻觉：报告与快照一致但现实已变（如定价上调）→ `superseded`（信息过期），不得计入幻觉率；
> ③ superseded 自动写 `TimelineMemory` + 触发异动告警（复用 `_record_timeline` 与 alert sink 链路）；
> ④ 产品侧默认 snapshot，refetch 仅发布前手动调用。

---

## 1. 问题现状

```
现状校验能力（agent/review_tools.py）：
  validate_facts(details_json, raw_text)   # 仅数值：count_numeric_conflicts(details, raw_text)
  detect_conflict(dimensions_json)         # 跨维度同源数值冲突
  extract_verified_facts(rec)              # 核验通过 → pinned facts（doc 56 M2）
局限：
  ① 只核「数值」，不核语义断言（「Cursor 支持 Windows」「已发布 2.0」漏检）；
  ② raw_text 由 Lead 手动传参，无强制来源回溯——断言可指向未抓取过的页面；
  ③ 无「现实已变」分支：来源页更新后，旧断言与旧快照一致 ≠ 与现实一致；
  ④ 无报告级汇总口径（只有逐工具调用回灌文本）。
可复用资产（均已核对）：
  Retriever.retrieve(query, competitor, dimension)   # snapshot 模式的来源文本来源（含 source_url）
  _ingest_fetched → Ingester.ingest(competitor, dimension, text, source_url)   # 抓取原文已沉淀知识库
  web_extract + FetchPolicy                          # refetch 模式的抓取链（doc 71 护栏齐备）
  TimelineMemory / _record_timeline / alert sink      # superseded 的去向
  count_numeric_conflicts / _VERIFY_NUMERIC_KEYS      # 数值子断言的确定性核对（NLI 的代码兜底层）
```

---

## 2. 目标设计

### 2.1 模块与数据模型

```
competitor_agent/core/verifier.py（新；不落 agent/——它不是工具面成员，是复核子系统）
  @dataclass Claim
    text: str                    # 原子断言（一句一事）
    dimension: str               # 所属维度
    source_urls: list[str]       # 报告中该断言引用的 evidence_urls
    numeric: dict[str, float]    # 抽出的数值键值（走 count_numeric_conflicts 快路径）

  @dataclass Verdict
    claim: Claim
    verdict: "supported" | "contradicted" | "superseded" | "unverifiable"
    evidence_url: str            # 实际比对用的来源
    reason: str                  # 一句话理由（审计/日志）
    mode: "snapshot" | "refetch"

  class NLIVerifier:
    def __init__(self, llm, retriever, web_extract, fetch_policy, timeline=None, alert_sink=None): ...
    def verify_report(self, report_text, competitor, *, mode="snapshot") -> ReportVerification
    def verify_claim(self, claim: Claim, competitor: str, *, mode="snapshot") -> Verdict

  @dataclass ReportVerification
    hallucination_rate: float        # contradicted / total（superseded 不计入分母的减分项）
    verdicts: list[Verdict]
    superseded_events: list[dict]    # 已写入 TimelineMemory 的事件回执
```

### 2.2 流程（verify_report）

```
1) 断言抽取：LLM 结构化输出（json_mode）从报告 markdown 抽原子断言清单 → Claim[]
   （数值断言并行走 count_numeric_conflicts 确定性核对，命中冲突直接 contradicted，不过 LLM）
2) 来源定位：snapshot → Retriever.retrieve(query=claim.text, competitor, dimension=claim.dimension)
              取 top chunk（其 source_url 即比对来源）；知识库无该断言来源 → unverifiable（不编造）
   refetch   → 逐 claim.source_urls 调 web_extract（受 FetchPolicy 上限/去重护栏，doc 71）
3) NLI 判定：LLM 输入（claim, 来源文本, 模式），输出 supported/contradicted + reason；
   refetch 模式下：先与知识库快照比对，若「与快照一致、与新抓原文矛盾」→ superseded（现实已变），
   若「与快照就矛盾」→ contradicted（真幻觉）
4) 落账：superseded → TimelineMemory.add_event(kind="price_change"/"version_release"...)
   + alert_sink 推送（与 weekly_report high_impact 触发项同源）；contradicted → 进审批门拒绝理由
```

### 2.3 双角色接线

| 角色 | 挂点 | 模式 |
|------|------|------|
| 产品（发布前自查） | `core/approval_gate.py`：`draft→pending_review` 时可选触发 `verify_report(mode="refetch")`；contradicted 条目进 `rejected` 理由；superseded 提示「报告含过期信息，建议重新分析」 | refetch（手动/配置开启） |
| 评测（幻觉率口径） | benchmark：`extract_prediction` 后对 mock/real 报告跑 `verify_report(mode="snapshot")`；产出 `verification.hallucination_rate` 与现有 `hallucination_by_dimension` 并列展示（**不替换**，双口径对照） | snapshot（确定性：知识库 chunk 固定 → 判定输入固定） |
| 知识库反馈 | superseded 事件携带新原文 → `Ingester.ingest` 以新 chunk 覆盖同 competitor×dimension（chunk_id 按内容哈希，自然新增；旧 chunk 过期由维度 TTL 治理） | — |

### 2.4 配置

```yaml
# review_config.yaml 增段
verifier:
  enabled: false            # 产品侧发布前校验开关（评测侧不受此开关控制）
  mode: "snapshot"          # 默认 snapshot；发布前手动 verify(mode="refetch")
  max_claims_per_report: 40 # 断言抽取上限（控成本）
  auto_ingest_superseded: true
```

---

## 3. 接入方式

- `facade/api.py`：`__init__` 装配 `NLIVerifier`（复用 self._llm/_retriever/_timeline/_alert 组装路径）；新增 `verify_report(competitor, mode)` 公共方法（门面薄路由）。
- `core/approval_gate.py`：审批策略加 `verify_before_approve: bool`（默认 false，向后兼容）。
- `evaluation/benchmark.py`：`run()` 内对每个 case 报告追加验证步骤；`BenchmarkReport` 加 `verification` 字段（mock 模式用注入的确定性 mock LLM，保 CI 可复现）。
- MCP/工具面**不注册** verify 为 Agent 工具（避免 Lead 自查自证）；它是复核子系统，走代码路径。

## 4. 验证方式

| # | 验收项 | 通过标准 |
|---|--------|---------|
| 4.1 | 三态单测 | 构造快照一致/快照矛盾/快照一致但新原文矛盾 三组 fixture，verdict 分别为 supported/contradicted/superseded |
| 4.2 | superseded 链路 | 触发后 TimelineMemory 新事件 + alert sink 收到推送（单测断言） |
| 4.3 | 评测确定性 | mock 模式连跑 3 次 `verification.hallucination_rate` 逐位一致 |
| 4.4 | 数值快路径 | 数值冲突断言不经 LLM 直接 contradicted（单测） |
| 4.5 | 护栏继承 | refetch 走 FetchPolicy：超限/重复 URL 被拦截（复用 doc 71 用例形态） |
| 4.6 | 回归 | 全量 pytest + benchmark 门禁 + ruff/mypy 干净；`validate_facts` 工具行为零改动 |

## 5. 实现优先级与工作量

P0，约 2 天（Claim 抽取 + 判定 1 天；superseded 链路 + 审批门/评测接线 1 天）。依赖：doc 76 的 benchmark 接线形态（并列指标字段）；被依赖：doc 83（Judge 校准的幻觉率口径参照）。

## 6. 核心技术点总结

1. **三态判定是本设计的灵魂**：把「时效性问题」从「质量问题」中剥离，否则 refetch 模式会把世界变化误记为幻觉，污染评测口径。
2. **superseded 反向喂时间线**：校验器不止质检——它是自动异动发现器，与 doc 26/67 的时间线/周报/告警体系合流，一条链路打通工单 2/6/12。
3. **snapshot/refetch 的确定性边界**：同一份知识库快照下，判定输入固定 → 评测可复现；产品侧才承担非确定性代价（真实网络）。
4. **不进 Agent 工具面**：自查自证的 Agent 是评测大忌，校验器固定走代码调用路径。
