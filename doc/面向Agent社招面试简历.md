# 个人简历 — 面向 Agent 开发社招面试

> **目标岗位**：AI Agent 开发工程师 / 智能体系统开发工程师  
> **背景**：Java 后端开发 + AI Agent 开发双栈经验

---

## 基本信息

| 项目 | 内容 |
|------|------|
| 姓名 | （请填写） |
| 联系方式 | （请填写） |
| 工作年限 | （请填写） |
| 学历 | （请填写） |
| 邮箱 | （请填写） |
| GitHub / 技术博客 | （请填写） |

---

## 专业技能

### AI Agent 开发
- **Agentic Workflow 编排**：主导设计 Conductor-Skill 架构，由 1 个主 Agent（编排器）编排 6 个专业子 Skill 协作完成复杂任务流水线，包含门禁系统、迭代修复、错误分类与降级机制
- **Agent 工作流设计**：设计 7 阶段流水线（参数确认 → 任务构建 → 算法设计 → 代码生成与验证 → 性能优化 → 报告输出 → 经验提炼），每阶段有严格的门禁检查和状态管理
- **Agent 安全机制**：设计基线冻结 + PreToolUse Hook + 自保护三层安全体系，防止 Agent 篡改源数据；实现 L1 闸门校验（sha256 锚定）
- **Agent 知识沉淀**：设计四层隔离复用模型（L1 约束 → L2 骨架 → L3 代码片段 → L4 历史代码），使 Agent 能从每次执行中学习并跨会话复用经验
- **Agent 错误处理**：设计 A/B/C 三类错误分类体系 + L1 兜底 + 超时降级，覆盖 Agent 执行中的各种异常场景
- **Agent 框架设计**：独立设计 6 层 Agent 架构（Facade → Orchestrator → Engine → Analyzer → Domain → Interface），基于 Protocol 接口契约实现依赖注入
- **Agent 迭代自改进**：实现 TacticalLoop 迭代执行引擎，支持多轮分析迭代、上下文压缩、边际递减检测自动停止
- **Agent 并行执行**：设计 SubAgent + ParallelRunner 并行架构，支持多阶段并发分析，每个 SubAgent 拥有独立预算和上下文
- **Agent 记忆系统**：设计四层记忆系统（SQLite 会话归档 → JSON 持久笔记 → YAML 技能沉淀 → LLM 梦境回顾整合），实现 Agent 自我进化
- **Agent 优雅降级**：实现 LLM 不可用时自动降级到规则引擎（FallbackAnalyzer），API 调用失败时指数退避重试
- **MCP 协议**：开发 FastMCP 工具服务器，提供 50+ 工具供外部 Agent 框架调用
- **Agent 可观测性**：实现 SSE 流式进度推送、结构化日志、会话可追溯（jsonl + markdown 导出）

### Java 后端开发
- **微服务架构**：精通 Spring Boot / Spring MVC + Apache ServiceComb 微服务框架，参与 28 个微服务模块的开发和维护
- **分布式系统**：熟练使用 DCS（Redis）分布式缓存、SDS 结构化数据存储、DMQ 消息队列、Elasticsearch 搜索服务
- **数据库**：精通 MySQL / GaussDB，MyBatis / MyBatis-Plus ORM 框架，Rainbow Proxy 数据库双活
- **安全与鉴权**：实现 RSA+SHA256withPSS 数字签名、AES-GCM 加密解密、OAuth2 鉴权、STS 密钥管理
- **高可用设计**：Sentinel 流量控制与熔断降级、多级缓存（Ehcache + Redis）、断路器/降级模式
- **性能优化**：多线程并发（FutureTask）、异步日志（Disruptor）、CDN 分发、缓存穿透防护

### 其他
- **编程语言**：Java（主力）、Python（Agent 开发）、Shell/Bash
- **AI 工具生态**：Claude Code、OpenCode、TRAE、Cursor、Copilot 多平台 Agent 开发经验
- **DevOps**：Maven 多模块构建、CI/CD 流水线、IaC 基础设施即代码、多环境部署管理
- **设计模式**：模板方法、策略、工厂、依赖注入、Facade、组合、观察者、令牌桶、适配器、异常层次

---

## 项目经验

### 项目一：Triton 算子自动生成 Agentic Workflow 系统

**时间**：近期  
**角色**：Agent 系统架构师 & 核心开发者  
**项目链接**：`cannbot-skills/plugins-official/triton-op-generator`

#### 项目背景
在 Ascend NPU 上，Triton DSL 算子开发流程复杂、调试周期长。传统方式需要开发者手动完成算法设计、代码编写、精度验证和性能优化，效率低下。本项目旨在构建一个 **Agentic Workflow（智能体工作流）系统**，让开发者用自然语言描述算子需求，由系统按结构化流水线自动完成从任务构建到性能优化的全流程。

#### 核心贡献

**1. Conductor-Skill 编排架构设计**
- 设计 **Conductor（主 Agent / 编排器）+ 6 个专业子 Skill** 的编排架构
- Conductor 负责 7 阶段工作流编排、迭代状态维护、错误分类与决策
- 6 个子 Skill 各司其职：任务提取（triton-task-extractor）、算法设计（triton-op-designer）、代码生成（triton-op-coding）、验证测试（triton-op-verifier）、性能优化（triton-latency-optimizer）、瓶颈诊断（triton-simulator-optimizer）
- 每个 Skill 有独立的 SKILL.md 指令文件，职责边界清晰

**2. 7 阶段流水线设计**
```
Phase 0: 参数确认     → 硬件检测、输入模式判定（A/B/C 三种模式）
Phase 1: 任务构建     → 字节级复制基线 + sha256 冻结
Phase 2: 算法设计     → precheck 前置检查 + sketch.txt 算法草图 + Layer1 合规门
Phase 3: 代码生成验证  → 生成 → AST 检查 → 验证 → Conductor 分析（最多 10 轮迭代）
Phase 4: 性能优化     → 优化器分析 → 验证 → 基准测试 → 判定（最多 50 轮）
Phase 5-7: 报告/导出/经验提炼
```

**3. 门禁系统（Gate）设计**
- 每阶段之间设置严格门禁：基线冻结必须成功 → precheck 必须产出 → Layer 1 合规检查 → 验证必须全部通过
- 防止 Agent 跳过关键步骤或产生无效输出

**4. 迭代修复与错误分类**
- 设计 A/B/C 三类错误体系：A 类可修复（含 PyTorch 退化 3 个子类型）、B 类环境错误立即终止、C 类重复失败终止
- 同一 A 类子类型连续失败 ≥ 3 次自动终止，避免死循环

**5. 基线冻结与安全机制**
- 设计三层安全体系：sha256 锚定 + PreToolUse Hook 路径保护 + L1 闸门校验
- Hook 自保护机制防止 Agent 篡改自身配置
- 保护路径白名单/黑名单配置化

**6. 四层隔离复用模型（知识沉淀）**
- Layer 1：设计约束（硬性边界，必须遵守）
- Layer 2：算法骨架（仅作参考，输出必须是全新设计）
- Layer 3：关键代码片段（技巧可参考，禁止复制结构）
- Layer 4：完整历史代码（默认对 Agent 不可见）
- 每次执行后自动提炼经验写入 template/，实现跨会话持续改进

**7. 多工具兼容**
- init.sh 支持 OpenCode、Claude Code、TRAE、Cursor、Copilot 五种 AI 编程工具
- 体现跨平台 Agent 生态的设计思路

#### 技术栈
Triton DSL（Ascend）、PyTorch、CANN、Claude Code / OpenCode、Bash + jq、Python、pytest

#### 项目亮点
- 将复杂的算子开发流程拆解为 7 个可管理的阶段，每个阶段由专业子 Skill 负责，主 Agent 负责编排与决策
- 安全设计是业界前沿实践：基线冻结 + Hook 自保护，防止 AI 篡改源数据
- 知识沉淀机制使系统具备跨会话持续学习能力，每次执行都在积累经验
- 错误分类体系覆盖了 Agent 执行中可能遇到的各种异常情况，保证流程收敛
- 性能数据强制从基准测试产物读取，严禁编造，保证结果可信

---

### 项目二：Dota 2 赛后复盘智能 Agent 系统

**时间**：近期  
**角色**：Agent 系统独立开发者  
**项目链接**：`DotaHelperAgent`

#### 项目背景
Dota 2 比赛数据量大、分析维度多（对线、团战、经济、决策、视野），传统复盘工具只能提供数据统计，缺乏深度分析和可操作的改进建议。本项目旨在构建一个 **自主 Agent 系统**，能够像专业教练一样对比赛进行多维度深度分析，并生成结构化报告。

#### 核心贡献

**1. 6 层 Agent 架构设计**
```
Facade 层      → PostMatchReviewAPI（统一外部入口）
Orchestrator 层 → ReviewOrchestrator + StrategicLoop + TacticalLoop
Engine 层      → PromptBuilder + StopVerifier + Budget + Compressor + DataFormatter
Analyzer 层    → BaseLLMReviewAnalyzer（模板方法）+ 5 个子类 + 2 种扩展
Domain 层      → MatchData / AnalysisResult / ReviewReport / ReviewAgentState
Interface 层   → 11 个 Protocol 接口契约
```

**2. 依赖注入容器（Runtime）**
- 设计 Runtime 作为 DI 容器，`build_orchestrator()` 方法组装全部 15+ 组件
- 基于 `typing.Protocol` 定义 11 个接口契约，实现松耦合
- 支持运行时组件替换（如 LLM 不可用时自动降级到规则引擎）

**3. 模板方法模式的分析器基类**
- `BaseLLMReviewAnalyzer.analyze()` 定义分析骨架：构建提示词 → LLM 调用 → 解析响应 → 置信度计算 → 结果验证
- 子类只需实现 `phase_name` 和 `_format_domain_data()` 即可扩展新的分析维度
- 支持 JSON 解析失败时自动降级到文本提取

**4. 迭代自改进引擎（TacticalLoop）**
- 每次迭代：消费预算 → 检查停止 → 执行分析 → 更新最佳结果 → 验证质量 → 上下文压缩 → 生成反馈
- 迭代反馈指导下一轮分析方向，实现自我改进
- 边际递减检测（连续 3 次增量 < 500 tokens 自动停止）

**5. 战略评估与预算分配（StrategicLoop）**
- 根据比赛数据（时长、比分差）将比赛分为 5 类：NORMAL / STOMP / COMEBACK / QUICK_PUSH / CLOSE_GAME
- 每类比赛有不同的优先级阶段列表和预算分配策略
- 令牌桶算法控制迭代配额，避免无限消耗

**6. 并行执行架构**
- SubAgent 拥有独立的 IterationBudget 和 AnalysisContext
- ParallelRunner 基于 asyncio.Semaphore 控制并发度
- TaskQueue 保证结果按索引顺序收集

**7. 四层记忆系统（Agent 自我进化）**
- Level 1：SQLite 会话归档 — 归档每次复盘会话
- Level 2：JSON 持久笔记 — 持久化高置信度分析模式
- Level 3：YAML 技能沉淀 — 可复用分析技能（如插眼效率、Roshan 时机）
- Level 4：LLM 梦境回顾 — 跨会话整合与模式发现
- BackgroundReviewer 后台执行 5 步自我审查：质量评估 → 归档 → 模式提取 → 持久化 → 整合

**8. 优雅降级体系**
- LLM 不可用 → FallbackAnalyzer 规则分析（454 行规则引擎）
- JSON 解析失败 → 文本提取降级
- API 调用失败 → 指数退避重试（最多 3 次）
- tiktoken 不可用 → 字符估算

**9. YAML 驱动可扩展分析**
- SkillDrivenAnalyzer 从 YAML 文件动态创建分析器，无需编写 Python 代码
- 验证必要字段：phase、name、stable_layer、volatile_layer
- 内置 3 个分析技能（ward_efficiency、roshan_timing、late_game_decisions）

**10. SSE 流式输出与可观测性**
- ProgressEmitter 实时推送进度事件（phase_start、phase_complete、progress、report、error）
- 结构化日志（dh.* 命名空间）
- MCP 工具服务器提供 50+ 工具供外部 Agent 框架调用

#### 技术栈
Python 3.9+、FastAPI、OpenAI SDK（DeepSeek）、httpx、asyncio、pydantic、pyyaml、sqlite3、FastMCP

#### 项目亮点
- 完整的 6 层 Agent 架构，从接口层到引擎层职责清晰
- 迭代自改进 + 记忆系统使 Agent 具备持续学习能力
- 优雅降级体系确保系统在各种异常情况下仍能提供有价值输出
- YAML 驱动扩展使非开发者也能添加新的分析维度

---

### 项目三：华为主题云 — 表盘资源签名校验服务

**时间**：（请填写在职时间段）  
**角色**：Java 后端开发工程师  
**项目链接**：`ThemeCloud/ThemeCloud-TIS`

#### 项目背景
华为主题云（ThemeCloud）是华为终端云服务旗下的主题商店后端系统，包含约 28 个微服务模块。表盘资源签名校验服务负责对手表表盘资源进行合法性校验和数字签名，确保只有经过授权的表盘才能在华为手表上安装使用。

#### 核心贡献

**1. 接口设计与实现**
- 设计并实现 `/theme/v2/service/resource/getresourcesign` 接口
- 面向表盘 SDK 的简化版本，去掉用户 ID 校验步骤，参数校验更严格
- 支持 MCU（运动表）和 AP（智能表）两种设备类型

**2. 权益判断逻辑**
- 设计链式优先级判断策略：试用标记 → 联盟资源 → 资源不存在放通 → 免费/已购 → 会员资源 → 试用期 → 非法
- 每种状态对应不同的响应码和业务处理逻辑

**3. RSA+SHA256 数字签名**
- 使用 BouncyCastle 解析 PKCS8/PEM 加密私钥
- AES-GCM（KEK）解密私钥口令
- RSA-SHA256withPSS 对响应内容签名，确保端侧可验证响应真实性
- MCU 和 AP 使用不同的签名私钥

**4. 多级缓存与降级策略**
- DCS（Redis）缓存健康云查询结果（默认 5 分钟 TTL）
- 健康云异常时通过配置开关决定是否放通，避免级联故障
- 配置中心（IAC）动态管理白名单、黑名单、逃生开关

**5. 审计与可追溯**
- SDS 记录每次签名结果（`t_resource_sign_record`）
- 会员签名记录（`t_member_sign_record`）

#### 技术栈
Java 21、Spring MVC、Apache ServiceComb、MyBatis、MySQL、DCS（Redis）、BouncyCastle、Fastjson2

#### 项目亮点
- 链式策略模式实现复杂的权益判断逻辑，代码清晰可维护
- 多级缓存 + 断路器降级确保高可用性
- RSA 数字签名保障端到端安全

---

### 项目四：华为主题云 — 栏目内容分发服务

**时间**：（请填写在职时间段）  
**角色**：Java 后端开发工程师

#### 项目背景
主题商店首页需要加载多个栏目的内容（推荐、热门、新品等），每个栏目需要从不同数据源获取内容并进行广告匹配和资源过滤。传统串行加载方式响应慢，用户体验差。

#### 核心贡献
- 设计并实现 `/theme/v2/restrict/column/common/column-detail` 接口
- 使用 FutureTask 实现多栏目并行加载，显著降低接口响应时间
- 多维度资源过滤（付费状态、设备兼容性、地区限制等）
- DCS 缓存热点数据，减少数据库查询

#### 技术栈
Java、Spring MVC、ServiceComb、MyBatis、MySQL、DCS（Redis）

---

## 对 Agent 开发的理解与思考

### 我对 Agent 开发的核心理念

1. **Agent 不是 Chatbot**：Agent 的核心是自主决策和任务执行能力，而非对话能力。一个好的 Agent 系统应该能在最少人工干预下完成复杂任务。

2. **结构化 > 自由发挥**：Agent 的工作流应该是有结构的流水线而非自由对话。门禁系统、阶段划分、错误分类等结构化设计是 Agent 系统可靠性的基石。

3. **安全是 Agent 系统的第一优先级**：Agent 有代码执行能力，必须有完善的安全机制（基线冻结、路径保护、自保护）防止 Agent 越权操作。

4. **Agent 需要持续学习**：四层记忆系统、知识沉淀、经验提炼等机制让 Agent 不是一次性工具，而是能持续进化的智能系统。

5. **优雅降级是工程落地关键**：LLM 不可用、API 超时、解析失败等异常在 Agent 系统中是常态，必须设计完善的降级策略。

### 我对 Agent 架构的理解

```
┌─────────────────────────────────────────────────────┐
│                   用户接口层                          │
│   (API / Web / CLI / MCP / IDE Plugin)              │
├─────────────────────────────────────────────────────┤
│                  编排层 (Orchestrator)               │
│   工作流编排 / 状态管理 / 迭代控制 / 错误处理        │
├─────────────────────────────────────────────────────┤
│                  引擎层 (Engine)                     │
│   提示词构建 / 预算控制 / 上下文压缩 / 停止验证      │
├─────────────────────────────────────────────────────┤
│                  执行层 (Executor)                   │
│   LLM 调用 / 规则引擎 / 工具调用 / 代码生成          │
├─────────────────────────────────────────────────────┤
│                  记忆层 (Memory)                     │
│   会话归档 / 持久笔记 / 技能沉淀 / 跨会话整合        │
├─────────────────────────────────────────────────────┤
│                  接口层 (Interface)                  │
│   Protocol 契约 / 依赖注入 / 可替换组件              │
└─────────────────────────────────────────────────────┘
```

---

## 面试问题准备

### 关于 Agent 开发的常见问题

**Q1：Agentic Workflow 和纯自主 Agent 的取舍？**
- 纯自主 Agent 适合开放性问题，能自主规划、反思、记忆，但不可控、难复现
- Agentic Workflow 适合结果可验证的封闭任务，用结构化流水线 + 门禁约束 LLM，可控、可靠、可审计
- 我的实践中，算子生成是结果可验证的任务，采用确定性工作流最大化利用这一特性；Dota 项目是开放任务，采用自主 Agent 架构。**任务类型决定架构**

**Q2：如何保证 Agent 输出的质量？**
- 门禁系统：每阶段输出必须通过验证才能进入下一阶段
- 迭代修复：允许 Agent 在预算内自我改进
- 停止验证：三段验证（完整性 → 证据 → 置信度）
- 错误分类：A/B/C 三类错误体系，避免死循环

**Q3：Agent 系统的安全性如何保障？**
- 基线冻结：sha256 锚定源文件，防止篡改
- PreToolUse Hook：在文件操作前检查路径合法性
- 自保护：防止 Agent 修改自身配置
- L1 闸门：运行时校验文件完整性

**Q4：Agent 如何从经验中学习？**
- 四层记忆系统：从会话归档到技能沉淀
- 知识提炼：每次执行后自动总结设计决策
- 四层隔离复用：约束可复用但代码不可直接复制

**Q5：Agent 系统如何应对 LLM 的不确定性？**
- 结构化输出约束（JSON schema）
- 多次采样 + 投票
- 置信度评估
- 降级到规则引擎

---

## 自我评价

- 具备 **Java 后端 + AI Agent 开发** 的双栈能力，能独立完成从架构设计到代码实现的全流程
- 有 **Agentic Workflow（智能体工作流）** 从零到一的完整设计经验，包括编排架构、安全机制、迭代优化、知识沉淀
- 对 Agent 系统的 **安全性、可靠性、可扩展性** 有深入思考和实践
- 具备 **微服务架构** 的工程落地经验，熟悉分布式系统常见问题和解决方案
- 善于从 **工程实践** 角度思考 Agent 系统的落地问题，而非停留在理论层面

---

## 附：项目代码链接

| 项目 | 路径 | 核心文件 |
|------|------|---------|
| Triton Op Generator | `cannbot-skills/plugins-official/triton-op-generator` | `AGENTS.md`（1097 行 Agentic Workflow 编排提示词） |
| DotaHelperAgent | `DotaHelperAgent` | `orchestrator/`、`analyzers/`、`memory/`、`facade/` |
| ThemeCloud 签名服务 | `ThemeCloud/ThemeCloud-TIS` | `CheckWatchResourceRightController.java` |
