# Agent 开发项目简历与面试应对（Triton 算子生成工作流 + 华为主题云 Java 项目）

> **用途**：作为社招 Agent 开发岗位的简历撰写与面试应对素材，涵盖两个项目：
> - **项目一（Agentic Workflow）**：Triton 算子生成工作流系统（`cannbot-skills/plugins-official/triton-op-generator`）
> - **项目二（Java 后端）**：华为主题云两个 Java 项目（表盘资源签名校验服务 + 栏目内容分发服务）
>
> 两个项目形成互补：一个证明 **Agent 编排与可靠性工程** 能力，一个证明 **Java 后端工程** 能力。

---

# 第一部分：Triton 算子生成工作流项目（Agentic Workflow）

> 项目：`cannbot-skills/plugins-official/triton-op-generator`
> 定位：**Agentic Workflow（智能体工作流 / 编排层）项目**，不是纯自主 Agent
> 本文回答三个问题：① 整个算子生成流程是什么 ② 简历怎么写（STAR） ③ 工作流项目如何呈现 Agent 开发能力

---

## 一、整个算子生成流程（工作流全景）

### 1.1 一句话概括

这是一个 **Conductor（主 Agent / 编排器）+ 6 个专业子 Skill** 的算子自动生成系统：用户用自然语言描述算子需求，系统按 **7 个阶段（Phase 0-7）** 的流水线，自动完成「任务构建 → 算法设计 → 代码生成 → 精度验证 → 性能优化 → 报告输出 → 经验沉淀」的端到端流程，最终产出可在 Ascend NPU 上运行的 Triton 算子代码。

### 1.2 7 阶段流水线

```
Phase 0: 参数确认      硬件架构检测（npu-smi）、输入模式判定（A/B/C 三种）
Phase 1: 任务构建      从用户代码提取算子任务文件 + 基线 sha256 冻结
Phase 2: 算法设计      precheck 前置检查 → designer 产出算法草图 sketch.txt → Layer1 合规门
Phase 3: 代码生成验证   生成 → AST 预检 → 精度验证 → Conductor 分析（迭代，最多 10 轮）
Phase 4: 性能优化      优化器 → 验证 → 基准测试 → 判定（迭代，最多 50 轮）
Phase 5: 输出报告      report.md + summary.json
Phase 6: 会话导出      session.jsonl + session.md
Phase 7: 经验提炼      四层隔离模型归档到 template/，跨会话复用
```

### 1.3 三种输入模式（Phase 0 判定）

| 模式 | 触发条件 | 处理方式 |
|------|---------|---------|
| **A 标准算子** | 提供 PyTorch 标杆（单 case / 多 case） | 调用 `triton-task-extractor` 构建任务文件；单 case 自动扩展为 ≥5 种 shape |
| **B GPU Kernel** | 仅提供 GPU Triton kernel（含 `@triton.jit`） | 当前会话自建 Model（优先返回预存 gpu_output，兜底手写 PyTorch 参考） |
| **C 直接描述** | 自然语言描述算子需求 | 自动构建任务描述文件 |

### 1.4 核心机制（工程亮点）

**① 门禁系统（Gate）**：每个阶段之间强制校验，不通过不能进入下一阶段
- 基线冻结必须成功 → precheck 必须产出 → Layer1 合规检查 → 验证必须全部通过

**② 迭代修复 + 错误分类（Conductor 决策）**
- A 类（代码逻辑错误，可修复）→ 生成 conductor_suggestion 重试
- B 类（环境/基础设施错误）→ 立即终止
- C 类（同一错误连续 ≥ 阈值）→ 终止防死循环
- 含 PyTorch 退化 3 子类型（Type1 无 kernel / Type2 未调用 / Type3 部分退化）

**③ 基线冻结 + 安全机制（防 Agent 篡改）**
- Phase 1 用 `freeze_baseline.py` 对源 benchmark 做 sha256 锚定
- verify/benchmark 启动时校验 sha256，不匹配 exit 4（C 类终止）
- PreToolUse Hook（`guard-baseline-paths.sh`）拦截对源数据路径的 Edit/Write
- 自保护（self_guard）：禁止 Agent 修改 hook 自身配置（防篡改）

**④ 四层隔离复用模型（知识沉淀 / 跨会话学习）**
- Layer 1 设计约束（硬性边界）→ Layer 2 算法骨架（参考方向）→ Layer 3 关键代码片段（可参考不可复制）→ Layer 4 完整历史代码（默认不可见）
- 每次执行后自动提炼经验写入 `template/{category}.md`，后续同类算子自动读取约束

**⑤ 性能数据真实性保障**
- 严禁编造/估算性能数据，必须从 `perf_result.json` 读取
- benchmark 超时自动降级 `--repeats`（50→20→10→5）

**⑥ 多工具兼容**：init.sh 支持 OpenCode / Claude Code / TRAE / Cursor / Copilot / CodeArts 六种 AI 编程工具

### 1.5 6 个专业子 Skill

| Skill | 职责 | 触发阶段 |
|-------|------|---------|
| triton-task-extractor | 从用户代码提取算子，构建任务文件 | Phase 1 |
| triton-op-designer | 设计算法草图 sketch.txt | Phase 2 |
| triton-op-coding | 生成 Triton-Ascend kernel 代码 | Phase 3 |
| triton-op-verifier | 精度验证 + 性能基准测试 | Phase 3/4 |
| triton-latency-optimizer | 逐步性能优化（31 个优化点 + IR 分析） | Phase 4 |
| triton-simulator-optimizer | msprof 采集 + 瓶颈诊断（MMAD 占比） | Phase 4 |

### 1.6 技术栈
Triton DSL（Ascend）、PyTorch、CANN Toolkit、Claude Code / OpenCode、Bash + jq、Python、pytest、PreToolUse Hook 机制

---

## 二、简历怎么写（STAR 法则）

> 说明：下面给出「标准版」和「精炼版」两个版本。标准版适合投递时详细展示，精炼版适合简历空间有限时使用。

### 2.1 标准版（推荐，约 300-400 字）

**项目：Triton-Ascend 算子自动生成工作流系统（Agentic Workflow）**
**时间**：近期　**角色**：Agent 工作流架构师 & 核心开发者
**项目链接**：`cannbot-skills/plugins-official/triton-op-generator`

**S（背景）**：在 Ascend NPU 上，Triton DSL 算子开发需人工完成算法设计、代码编写、精度验证和性能调优，流程复杂、调试周期长、对开发者要求高。传统方式效率低下，且难以沉淀经验。

**T（任务）**：构建一套 **Agentic Workflow 系统**，让开发者用自然语言描述算子需求，由系统自动完成从任务构建到性能优化的全流程，并实现质量门禁、安全防护和经验复用。

**A（行动）**：
1. **设计 Conductor + 6 子 Skill 编排架构**：主 Agent 负责 7 阶段工作流编排、迭代状态维护、错误分类与决策；6 个专业子 Skill 各司其职（任务提取/算法设计/代码生成/精度验证/性能优化/瓶颈诊断），职责边界清晰。
2. **实现 7 阶段流水线与门禁系统**：参数确认 → 任务构建 → 算法设计 → 代码生成验证 → 性能优化 → 报告输出 → 经验提炼；每阶段强制门禁校验，不通过不能进入下一阶段，保证输出质量。
3. **设计迭代修复 + 错误分类机制**：A/B/C 三类错误体系（A 可修复重试、B 环境错误终止、C 重复失败防死循环），支持最多 10 轮代码生成迭代和 50 轮性能优化迭代。
4. **构建安全防护体系**：基线 sha256 冻结 + PreToolUse Hook 路径保护 + 自保护（防 Agent 篡改自身配置），杜绝 Agent 篡改源数据导致结果失真。
5. **实现四层隔离经验复用模型**：每次执行后自动提炼设计约束/算法骨架/关键代码片段到 template/，后续同类算子自动读取约束，实现跨会话持续改进。
6. **保障性能数据真实性**：强制从基准测试产物读取数据，严禁编造；超时自动降级重试。

**R（结果）**：
- 支持 3 种输入模式（PyTorch 标杆 / GPU Kernel / 自然语言描述），覆盖单 case 与多 case（≥5 种 shape）泛化验证
- 算子生成全流程自动化，精度验证通过率 100%（passed == total）后才进入性能优化
- 性能优化以几何平均加速比为目标（config 配置 target_speedup），优化不劣化（speedup ≥ 1.0）为底线
- 已沉淀 tensor-transform / normalization / quantization / transformer-inference 等多类算子经验模板
- 兼容 OpenCode / Claude Code / TRAE / Cursor / Copilot / CodeArts 六种主流 AI 编程工具

**技术栈**：Triton DSL（Ascend）、PyTorch、CANN、Claude Code / OpenCode、Bash + jq、Python、pytest

### 2.2 精炼版（简历空间有限时，约 150-200 字）

**Triton-Ascend 算子自动生成工作流系统（Agentic Workflow）**
- 设计 **Conductor + 6 子 Skill** 编排架构，实现「任务构建→算法设计→代码生成→精度验证→性能优化→经验沉淀」7 阶段流水线，用户自然语言描述即可自动生成 NPU 算子
- 实现**门禁系统 + A/B/C 错误分类 + 迭代修复**（生成最多 10 轮、优化最多 50 轮），保证输出质量与收敛性
- 构建**基线 sha256 冻结 + PreToolUse Hook + 自保护**三层安全体系，防止 Agent 篡改源数据
- 设计**四层隔离经验复用模型**，实现跨会话知识沉淀与持续改进
- 支持 3 种输入模式、6 种 AI 编程工具，性能数据强制从基准测试产物读取（严禁编造）

---

## 三、工作流项目如何呈现 Agent 开发能力（重点）

### 3.1 先想清楚：这个项目到底是不是 Agent？

**诚实回答：它是「Agentic Workflow（智能体工作流）」项目，不是纯自主 Agent。**

区别在于：
- **纯 Agent**（如你的 Dota 项目）：有自主规划（planning）、自我反思（reflection）、记忆（memory）、工具选择（tool selection）等能力，能根据环境反馈自主决策下一步。
- **本工作流项目**：是一个**确定性的编排引擎**，把 LLM 当作流水线中的一个执行单元，通过**预定义的工作流 + 门禁 + 迭代 + 错误分类**来驱动它完成复杂任务。

**但这不是缺点，反而是优势。** 面试官真正关心的是「你能不能把 LLM 可靠地落地到生产环境」。工作流项目恰恰证明了你在 **LLM 可靠性工程** 上的能力，这比一个玩具 Agent 更有价值。

### 3.2 如何把工作流项目「翻译」成 Agent 能力（关键话术）

不要否认它是工作流，而是把它定位为 **「Agent 系统的编排层 / 可靠性工程」**。用下面的框架来呈现：

| 工作流项目里的机制 | 对应的 Agent 能力 | 面试话术 |
|-------------------|------------------|---------|
| Conductor 编排 7 阶段 + 6 子 Skill | **工作流编排 / 任务分解** | "我设计了 Conductor-Skill 架构，把复杂算子开发拆解为 7 个阶段，每个阶段由专业子 Skill 负责，主 Agent 负责编排和决策" |
| 门禁系统（每阶段强制校验） | **质量保障 / 输出可靠性** | "通过门禁系统保证每个阶段的产出必须通过验证才能进入下一阶段，这是 Agent 系统可靠性的核心" |
| A/B/C 错误分类 + 迭代修复 | **Agent 自主决策 / 错误处理** | "设计了错误分类体系，让 Agent 能区分可修复错误、环境错误和重复失败，避免死循环" |
| 基线冻结 + Hook + 自保护 | **Agent 安全 / 防越权** | "Agent 有代码执行能力，我设计了基线冻结和路径保护，防止 Agent 篡改源数据" |
| 四层隔离经验复用 | **Agent 记忆 / 持续学习** | "实现了跨会话经验复用，让 Agent 从每次执行中学习，而不是一次性工具" |
| 性能数据真实性强制 | **Agent 可信度 / 防幻觉** | "强制 Agent 从真实基准测试产物读取数据，严禁编造，保证结果可信" |

### 3.3 面试时的定位话术（直接背）

> **"这个项目我定位为 Agentic Workflow，也就是智能体工作流的编排层。它和纯自主 Agent 的区别在于：纯 Agent 强调自主规划，而工作流强调**可控性、可靠性和可复现性**。在实际生产中，LLM 是不确定的，直接让它自由发挥是不可靠的。我的做法是把 LLM 放进一个结构化的流水线里，用门禁、迭代、错误分类、安全防护这些工程手段来约束它，让它稳定地产出高质量结果。这恰恰是 Agent 系统从 Demo 走向生产的关键能力。"**

### 3.4 面试可能追问及应答

**Q1：这个项目里 LLM 的自主性体现在哪？**
> "自主性体现在两个层面：一是**编排层**，Conductor 根据验证结果自主决定是重试、换策略还是终止（A/B/C 分类决策）；二是**生成层**，每个子 Skill 内部由 LLM 自主完成算法设计和代码生成。但整体流程是确定性的，这是刻意的设计——为了可复现和可审计。"

**Q2：为什么不直接做成一个纯自主 Agent？**
> "因为算子生成是**结果可验证**的任务（有精度比对和性能基准），确定性工作流能最大化利用这个特性。纯自主 Agent 适合开放性问题，而这里每一步都有明确的通过标准，用门禁和迭代比自由发挥更高效、更可靠。这是**任务类型决定架构**的典型例子。"

**Q3：你如何保证 Agent 生成的结果可信？**
> "三层保障：一是**门禁**，精度验证必须 100% 通过才进入优化；二是**基线冻结**，源数据 sha256 锚定，防止 Agent 篡改基准；三是**数据真实性**，性能数据强制从基准测试产物读取，严禁编造，超时自动降级重试。"

**Q4：这个项目和纯 Agent 项目（如 Dota）你更认可哪种？**
> "两者解决不同问题。Dota 项目是**开放任务**，需要 Agent 自主规划、反思、记忆，我用的是 6 层架构 + 迭代自改进 + 四层记忆。算子生成是**封闭任务**，结果可验证，我用的是确定性工作流。我两种都做过，能根据任务类型选择合适架构，这是我最大的优势。"

### 3.5 简历措辞建议（避免被质疑）

- ✅ 用 **"Agentic Workflow"** / **"智能体工作流"** / **"工作流编排"** 作为定位词
- ✅ 强调 **编排、门禁、错误分类、安全、经验复用** 这些工程能力
- ⚠️ 避免过度声称 "自主 Agent"、"自我反思"、"自主规划"（这些本项目没有，面试会被追问穿帮）
- ✅ 如果简历同时有 Dota 项目（纯 Agent），可以形成互补：**"一个证明编排与可靠性工程，一个证明自主 Agent 架构"**

---

## 三.6 我该怎么介绍这个项目（1-2 分钟完整话术）

> 面试官让你"介绍一下这个项目"时，按下面脚本讲。**控制在 90 秒左右**，先讲清楚"是什么 + 解决什么问题"，再讲"我怎么做的"，最后落到"结果和亮点"。

### 开场（30 秒）—— 是什么 + 为什么做

> "这个项目叫 **Triton 算子自动生成工作流系统**。背景是：在华为昇腾 Ascend NPU 上，用 Triton DSL 开发算子，传统上需要开发者手动完成算法设计、写代码、精度验证、性能调优，流程长、门槛高、经验难沉淀。我的目标是做一个 **Agentic Workflow**，让开发者用自然语言描述算子需求，系统自动走完从任务构建到性能优化的全流程。"

### 主体（45 秒）—— 我怎么做的（挑 2-3 个亮点讲）

> "我设计了 **Conductor + 6 个专业子 Skill** 的编排架构，把整个流程拆成 7 个阶段：参数确认、任务构建、算法设计、代码生成验证、性能优化、报告输出、经验提炼。核心是三个工程机制：
> **第一，门禁系统**——每个阶段产出必须通过验证才能进下一阶段，保证质量；
> **第二，迭代修复 + 错误分类**——把错误分成 A 可修复 / B 环境 / C 重复失败三类，让系统能自主决定重试还是终止，避免死循环；
> **第三，安全防护**——对源基准做 sha256 基线冻结，再用 PreToolUse Hook 拦截篡改，防止 Agent 改坏数据导致结果失真。"

### 收尾（15 秒）—— 结果 + 亮点

> "最终系统支持三种输入模式，能自动生成并优化算子，精度验证 100% 通过后才进入优化，性能以几何平均加速比为目标、不劣化为底线。最有价值的是**四层隔离经验复用**——每次执行后自动把设计约束、算法骨架、关键代码沉淀下来，后续同类算子自动复用，实现跨会话持续改进。"

### 一句话总结（备用，被打断时用）

> "一句话：这是一个把 LLM 放进结构化流水线、用工程手段保证它稳定产出高质量算子的 **Agentic Workflow 系统**，核心价值在编排、门禁、错误分类、安全和经验复用。"

---

## 三.7 面试官可能深挖的技术细节问题（含应答）

> 前面 3.4 是"定位层面"的问题，这里是"技术细节层面"的追问。**这些是面试官真正会深挖的**，务必提前准备。

### Q1：门禁系统具体是怎么实现的？怎么防止 Agent 跳过？

> "门禁是**硬编码在编排逻辑里**的，不是靠 LLM 自觉。比如 Phase 1 结束必须调用 `freeze_baseline.py` 落锚文件，Phase 2 必须产出 `precheck.json` 且 `loaded_via` 字段只能是 `explicit_path`，否则禁止进入下一步。更关键的是**下游脚本自校验**：verify.py / benchmark.py 启动时会校验基线的 sha256 是否等于锚文件记录值，锚缺失 exit 3、被篡改 exit 4，都是 C 类终止。也就是说，即使编排器逻辑有 bug 漏了门禁，底层脚本也会兜底拦截。"

### Q2：A/B/C 错误分类是怎么落地的？Conductor 怎么判断？

> "Conductor 读取验证产物 `verify_result.json`，根据错误特征分类：**A 类**是代码逻辑错误（输出不一致、语法错误、shape 不匹配、kernel 参数错误、DSL API 用错、退化成 PyTorch），可修复，生成 `conductor_suggestion` 后重试；**B 类**是环境错误（文件路径、设备不可用、依赖缺失、超时），不可修复，立即终止；**C 类**是同一 A 类子类型连续失败达到阈值，终止防死循环。另外有个专门检测 **PyTorch 退化** 的 AST 预检查，分三个子类型：Type1 完全没有 kernel、Type2 有 kernel 但 forward 没调用、Type3 部分计算还在用 PyTorch。"

### Q3：基线冻结 + Hook 自保护具体怎么防篡改？

> "三层：**第一层 sha256 锚定**，Phase 1 用 `freeze_baseline.py` 对源 benchmark 算 sha256 写入锚文件，之后任何修改都会导致下游校验失败；**第二层 PreToolUse Hook**，`guard-baseline-paths.sh` 在 Claude Code 每次 Edit/Write 前拦截，用正则匹配保护路径（如 `npu_benchmark/*.py`），命中就 deny；**第三层自保护**，`self_guard` 规则禁止 Agent 修改 hook 脚本和配置本身，防止 Agent 通过改配置来解除保护。决策顺序是 self_guard → allowlist → protected → 默认放行。"

### Q4：四层隔离复用模型是怎么工作的？Agent 怎么读取经验？

> "每次算子成功后，Phase 7 会把经验按四层写入 `template/{category}.md`：**Layer 1 设计约束**（硬性边界，如'constant 模式必须拆成 fill+copy'）、**Layer 2 算法骨架**（并行策略抽象）、**Layer 3 关键代码片段**（5-15 行已验证代码）、**Layer 4 完整历史代码**（默认对 Agent 不可见）。下次生成同类算子时，Phase 2 的 designer skill 会读取该 category 的 template，Layer 1 作为硬约束、Layer 2 作参考方向、Layer 3 可参考但禁止复制结构。这样既复用了经验，又防止 Agent 直接抄历史代码导致多样性丢失。"

### Q5：性能优化是怎么迭代的？怎么保证不劣化？

> "Phase 4 用 `triton-latency-optimizer` 按 31 个优化点 + IR 分析逐步优化，每轮只试一个优化点，最多 50 轮。每轮流程是：优化 → 精度验证（必须全过）→ 基准测试 → 对比几何平均加速比。**只有优化后加速比 > 基线才采纳**，否则回退，所以底线是 `speedup_vs_baseline ≥ 1.0`，绝不劣化。优化点耗尽且没达到目标时，会转用 `triton-simulator-optimizer` 做 msprof 采集诊断瓶颈（比如 MMAD 占比 > 50% 就是硬件极限）。"

### Q6：性能数据怎么保证真实？会不会编造？

> "这是硬约束。所有性能数据**必须从 `benchmark.py` 实际产出的 `perf_result.json` 读取**，严禁编造、估算、模拟。而且 benchmark 超时或被 kill 时，必须自动降级 `--repeats`（50→20→10→5）重试，不能直接放弃或编数据。精度通过数（passed_cases）必须从 verify_result.json 读，不能从 perf_result.json 读——因为 perf 的 pass 只代表进程没崩溃，不代表精度对。"

### Q7：三种输入模式（A/B/C）是怎么判定的？

> "Phase 0 按优先级判定：**优先级 1** 是用户同时给了 PyTorch 标杆和 GPU Triton kernel，走标准算子模式，GPU kernel 作为参考实现辅助适配；**优先级 2** 是只给 GPU kernel（文件含 `@triton.jit` 或路径含 'GPU Kernel'），走 GPU Kernel 模式，自建 Model（优先返回预存 gpu_output，兜底手写 PyTorch 参考）；**优先级 3** 是普通 PyTorch 文件，走标准模式。另外单 case 会自动扩展成至少 5 种 shape 的多 case，保证泛化验证。"

### Q8：这个项目里你遇到的最大技术难点是什么？

> "我觉得是**性能优化与精度验证的平衡**。算子要快，但快的前提是精度必须 100% 通过。很多优化手段（比如向量化、多策略分派、坐标预计算）一旦做错，精度就崩。所以我设计了严格的迭代闭环：每轮优化先过精度验证、再测性能、只有提升才采纳。另一个难点是**防止 Agent 篡改基准**——因为 Agent 有文件写权限，一旦它为了'通过验证'去改基准数据，整个结果就失真了，所以我才设计了基线冻结 + Hook 自保护这套机制。"

### Q9：为什么用 6 个子 Skill 而不是一个大的 Agent？

> "因为**职责分离**。任务提取、算法设计、代码生成、精度验证、性能优化、瓶颈诊断，每个都是相对独立的专业能力，拆成独立 Skill 后：一是每个 Skill 的指令文件（SKILL.md）可以聚焦、更专业；二是职责边界清晰，便于维护和复用；三是可以单独演进。Conductor 只负责编排和决策，不负责具体专业执行，这样架构更清晰。"

---

## 三.8 不写 Dota 项目时，如何呈现 Agent 开发能力（重点）

> **场景**：简历不写 Dota 项目，只有一个 cannbot 工作流项目。此时不能靠"另一个纯 Agent 项目"证明自主 Agent 能力，只能靠 cannbot 一个项目。**好消息是：cannbot 内部蕴含的 Agent 核心能力远不止"工作流编排"，完全可以单独拿出来讲。**

### 3.8.1 核心思路：把"工作流"拆解成"Agent 通用能力"

面试官要的不是"你做过几个 Agent 项目"，而是"**你懂不懂 Agent 系统的通用能力**"。cannbot 虽然整体是工作流，但它内部几乎覆盖了 Agent 开发的所有通用能力维度。你要做的是**从工作流里把这些能力"抽出来"单独讲**，而不是只讲"我编排了一个流水线"。

### 3.8.2 从 cannbot 里能提炼出的 6 大 Agent 能力（非编排）

| # | Agent 通用能力 | cannbot 里的具体体现 | 面试话术 |
|---|--------------|---------------------|---------|
| 1 | **迭代自改进（Self-Improvement）** | Phase 3 生成→验证→Conductor 分析循环，最多 10 轮；Phase 4 优化→验证→判定循环，最多 50 轮；每轮根据上一轮错误反馈改进 | "我实现了迭代自改进闭环：系统根据验证失败信息自动分析原因、生成修复建议、重新生成，直到通过或达到上限" |
| 2 | **自主决策 / 错误处理（Decision-Making）** | A/B/C 三类错误分类，Conductor 自主决定重试 / 换策略 / 终止；PyTorch 退化 3 子类型识别 | "我设计了错误分类决策机制，让系统能区分可修复错误、环境错误和重复失败，自主决定下一步" |
| 3 | **状态与上下文管理（State Management）** | 显式维护迭代状态变量（iteration、history_attempts、previous_code、verifier_error、conductor_suggestion），跨轮传递上下文 | "我设计了显式的状态管理，把每轮迭代的代码、错误、建议都记录下来传给下一轮，保证上下文连续" |
| 4 | **安全与防越权（Safety / Guardrails）** | 基线 sha256 冻结 + PreToolUse Hook 路径保护 + 自保护（防 Agent 篡改自身配置） | "Agent 有代码执行能力，我设计了多层安全防护，防止 Agent 篡改源数据或解除自身保护" |
| 5 | **记忆 / 经验复用（Memory / Learning）** | 四层隔离复用模型，每次执行后自动提炼经验写入 template/，跨会话复用 | "我实现了跨会话记忆：..." |
| 6 | **可信度 / 防幻觉（Reliability / Anti-hallucination）** | 性能数据强制从基准测试产物读取，严禁编造；超时自动降级重试 | "我设计了防幻觉机制：强制系统从真实测试产物读取数据，严禁编造，保证结果可信" |

### 3.8.3 面试时的呈现话术（不依赖 Dota）

> **"虽然这个项目整体是一个工作流，但我在里面落地了 Agent 系统的几乎所有通用能力。第一是**迭代自改进**——系统根据验证失败自动分析、修复、重试；第二是**自主决策**——通过 A/B/C 错误分类让系统自主决定重试还是终止；第三是**状态管理**——显式维护迭代上下文，保证多轮执行连续；第四是**安全防护**——基线冻结 + Hook 自保护，防止 Agent 篡改数据；第五是**记忆与经验复用**——四层隔离模型实现跨会话学习；第六是**防幻觉**——强制从真实产物读取数据。所以虽然它是工作流形态，但我在里面完整实践了 Agent 系统的可靠性工程，这些能力是通用的，换到任何 Agent 项目都能复用。"**

### 3.8.4 如果面试官追问"你做过纯自主 Agent 吗？"

> 诚实回答 + 展示通用能力 + 表达学习意愿：
> "我目前主要做的是 **Agentic Workflow** 形态，也就是把 LLM 放进结构化流水线里。纯自主 Agent（自主规划、反思、记忆）我理解其原理，但没有在生产项目里完整落地过。不过我认为这两者底层能力是相通的——**迭代、决策、状态管理、安全、记忆、防幻觉**这些我在工作流项目里都实践过。如果给我一个自主 Agent 的任务，我能很快把工作流里的这些能力迁移过去。"

> ⚠️ **不要假装做过纯自主 Agent**。面试官深挖会穿帮。诚实 + 展示通用能力 + 表达可迁移性，是最稳妥且加分的策略。

### 3.8.5 简历措辞建议（不写 Dota 时）

在专业技能部分，把 cannbot 的能力**按 Agent 通用能力维度**写，而不是只写"工作流编排"：

- ✅ **Agent 迭代自改进**：实现生成→验证→分析迭代闭环，根据失败反馈自动修复重试
- ✅ **Agent 自主决策**：A/B/C 错误分类 + 终止策略，避免死循环
- ✅ **Agent 状态管理**：显式维护多轮迭代上下文
- ✅ **Agent 安全防护**：基线冻结 + Hook 自保护，防篡改
- ✅ **Agent 记忆复用**：四层隔离模型，跨会话经验沉淀
- ✅ **Agent 可信度**：强制真实数据，防幻觉

> 这样即使只有一个项目，也能在"专业技能"里呈现出**完整的 Agent 能力栈**，而不是只有"编排"一个点。

---

## 四、与现有简历的衔接建议

你的 `面向Agent社招面试简历.md` 中「项目一」已写了 Triton 算子生成，但定位为 **"Multi-Agent 系统"**，存在被追问穿帮的风险。建议：

1. **把定位从 "Multi-Agent 系统" 改为 "Agentic Workflow（智能体工作流）系统"**，更准确、更经得起追问。
2. **专业技能部分**的措辞微调：
   - "Multi-Agent 编排" → 保留，但补充 "工作流编排"
   - 新增 "Agentic Workflow 可靠性工程" 一条
3. **面试问题准备**部分补充 Q：工作流 vs 纯 Agent 的区别（见 3.4）。
4. 如果面试官质疑"这不是 Agent"，用 3.3 的定位话术回应。

---

## 五、风险提示

1. **不要夸大**：本项目没有自主规划/反思/记忆，不要写成"自主 Agent"。定位为工作流编排 + 可靠性工程最稳妥。
2. **性能数据**：简历中不要写具体加速比数字（如 1.38x），除非你能现场演示或解释来源。可写"以几何平均加速比为目标、优化不劣化为底线"这类定性描述。
3. **技术深度**：面试官可能追问 Triton DSL / Ascend 算子细节，建议提前准备 1-2 个算子的具体优化案例（如 Interpolate 的多策略分派、bilinear 0.5x 下采样退化为 2x2 均值池化等）。
4. **与 Dota 项目的关系**：两个项目定位要清晰区分，一个讲工作流可靠性，一个讲自主 Agent 架构，形成互补而非重复。

---

# 第二部分：华为主题云两个 Java 项目

> **用途**：作为社招 Agent 开发岗位的 **Java 后端背景** 素材。
> 本文基于 `CheckWatchResourceRightController.java`（表盘资源签名校验）与 `ColumnDetailController.java`（栏目内容分发）两个真实接口，逐层拆解其业务逻辑、技术要点，并给出可直接用于简历的项目描述、面试官可能追问的问题及标准应答。

---

## 一、项目一：表盘资源签名校验服务（AccessRight）

### 1.1 接口清单与职责

| 接口 | 路径 | 职责 |
|------|------|------|
| 表盘资源校验 | `POST /servicesupport/theme/v2/service/resource/checkright` | 校验表盘资源合法性，返回文件 hash 与合法状态，供端侧下载 |
| SDK 资源签名 | `POST /servicesupport/theme/v2/service/resource/getresourcesign` | 面向表盘 SDK 的简化版，去掉 userid 校验，参数校验更严格 |
| 会员签名 | `POST /servicesupport/theme/v2/service/member/checkright` | 下发会员权益签名（会员状态、有效期、period），供端侧离线校验 |

### 1.2 分层架构（Controller → Service → Util → DAO）

```
CheckWatchResourceRightController（接口层）
        │  @RestSchema + @RequestMapping("/servicesupport")
        ▼
ICheckWatchResourceRightService / CheckWatchResourceRightServiceImpl（业务层）
        │  权益判断 / 签名 / 健康云调用 / 缓存 / 审计
        ▼
CheckWatchResourceRightUtil（工具层：参数校验 / 签名 / 私钥加载 / 缓存）
        ▼
IThemeDaoMapper / TcsResourceService / SecretResourceService / VipUtils（数据与外部依赖）
```

### 1.3 核心业务逻辑拆解

**① 参数校验（Controller 层）**
- 从请求头解析 `RequestV2Header`（authtype、userToken、clienttraceid、appid 等）
- `passCheck()` + `RequestParameterUtils.validate()` 双重校验，不通过直接返回 `PARAMETERERROR`，并记录错误日志
- 异常分层捕获：`ThemeException`（业务异常）→ `Exception` → `Throwable`，统一映射为 `SYSTEMERROR`，保证接口不裸抛异常

**② 用户身份校验（防越权）**
- `checkUserId()`：将 ThreadLocal 中的 userId 做 SHA-256，与端侧上报的 `huid` 比对，不一致返回 `USER_AUTH_FAILD`，防止伪造身份

**③ 权益判断链（核心，策略模式思想）**
```
getWatchResourceRightResp 主流程：
1. 通过 hitopId 查 workId → 查资源模型（DCS）
2. 判断资源类型（免费/付费/会员/不存在）
3. 判断是否需要"资源回收时会员签名"
4. 逃生白名单判断 → 放通（RELEASE）
5. 设计师自测场景（特殊 hitopId）→ 校验设计师账号
6. 资源来源判断（本云 / 联盟 TCS / 双活）
7. checkStatusAndBuildResp：查资源 → 判断状态 → 取文件 hash → 组装出参
```

状态机枚举 `WatchFaceRightStatus`：
- `LEGAL` 合法、`ILLEGAL` 非法、`RELEASE` 放通、`TRAIL_LEGAL` 试用合法、`MEMBER_STATUS` 会员态、`RELEASE_MEMBER_STATUS` 会员放通

**④ 多数据源查询（本云 + 联盟 + 健康云）**
- 本云：`ResourceUtils.queryResourceItemByHitopIdIgnoreState`（含下架资源）
- 联盟 TCS：`tcsResourceService.queryResourceFromTcs`（保密资源 + 待测试资源）
- 运动健康云：`getWatchfaceRightFromHealth`，通过 HTTP 调用健康云接口查询表盘权限，解析返回码（0 合法 / 29001023 非法 / 无 hash 放通 / 无资源按开关）

**⑤ 数字签名（安全核心）**
- RSA-SHA256withPSS 对响应内容签名，返回 16 进制字符串
- 私钥管理：BouncyCastle 解析 PKCS8/PEM 加密私钥，AES-GCM（KEK）解密私钥口令
- MCU（运动表）与 AP（智能表）使用不同私钥
- 会员签名：对会员信息 JSON 签名，端侧可离线验证

**⑥ 缓存与降级（高可用）**
- 健康云查询结果缓存到 DCS（Redis），key 为请求体 SHA-256
- 健康云异常时通过配置开关 `tis.watchface.health.exception.release.switch` 决定是否放通，避免级联故障
- 逃生白名单/黑名单、资源为空放通开关等均通过配置中心（IAC）动态管理

**⑦ 审计与可追溯**
- SDS 记录每次签名结果（`t_resource_sign_record`）
- 会员签名记录（`t_member_sign_record`）
- 错误日志落库（`saveWatchfaceErrorLog`）

### 1.4 技术栈
Java 21、Spring MVC、Apache ServiceComb（微服务框架）、MyBatis、MySQL/GaussDB、DCS（Redis）、SDS、BouncyCastle、Fastjson2、OAuth2

---

## 二、项目二：栏目内容分发服务（ColumnDetail）

### 2.1 接口与职责

| 接口 | 路径 | 职责 |
|------|------|------|
| 栏目详情 | `POST /servicesupport/theme/v2/restrict/column/common/column-detail` | 查询栏目详情（含栏目内容列表），首页多栏目并行加载 |

### 2.2 分层架构

```
ColumnDetailController（接口层）
        │  @RestSchema + @RequestMapping("/servicesupport")
        ▼
ColumnDetailService / ColumnDetailServiceImpl（业务层）
        │  多线程并行 / 资源过滤 / 定投广告匹配 / 兜底
        ▼
ResourceFilterUtils / ContentResourceBuildHelper / RankingListDlMetadataService（过滤与组装）
        ▼
IHitopInterfaceDataMapper / IZoneSingleDataService（数据源）
```

### 2.3 核心业务逻辑拆解

**① 请求头校验（Controller 层）**
- 从 `ContextUtils.getInvocationContext().getContext()` 解析请求头为 `ColumnDetailHeader`
- `ValidatorUtils.validate()` 校验，失败返回 `HEAD_PARAM_ERROR`
- 个人开关（`personalSwitch`）开启时直接返回成功（快速路径）

**② 多线程并行加载（性能核心）**
- 自定义 `ThreadPoolExecutor`（核心/最大线程数、队列大小均从配置中心读取）
- 每个栏目提交一个 `ColumnDetailRespTask`（继承 `FutureTask`），在 `run()` 中重新设置 traceId，保证多线程日志可追溯
- 使用 `Future.get()` 收集结果，实现多栏目并行加载，显著降低接口响应时间
- `CallerRunsPolicy` 拒绝策略，避免任务丢失

**③ 资源过滤参数构建（buildFilterBean）**
- 根据设备信息（realDeviceType、foldProductType、harmonyApiLevel）计算 screenCode、clientType
- 折叠屏设备特殊处理（FOLD clientType）
- 语言适配（`SignSupport.getAdaptedLanguageSign`）、地区（isoCode）、机型（phoneCode）
- 从配置读取 isVipVersion、cipherVersion、supportProductType 等

**④ 栏目处理与兜底（dealWithColumn → getColumnDetailResp）**
- 根据 siteId 获取定投广告栏目列表（按优先级排序，取前 2 个）
- 从第一个栏目取内容，若内容数 < 3 个，则取第二个栏目作为兜底（`getFallbackColumnDetail`）
- 本地已下载资源去重（`localResourceIds`）

**⑤ 多维度资源过滤**
- 付费状态、设备兼容性、地区限制、系统版本、语言等多维度过滤
- 配置开关控制是否去重、是否返回空列表（现网规避问题）

### 2.4 技术栈
Java、Spring MVC、ServiceComb、MyBatis、MySQL、DCS（Redis）、Fastjson2、多线程（FutureTask/ThreadPoolExecutor）

---

## 三、接口详细流程（含中间件）

> 本节以**时序/步骤**方式完整描述两个接口从请求进入到响应返回的完整链路，并标注每一步涉及的**中间件**（DCS/Redis、SDS、MySQL/GaussDB、配置中心 IAC、消息/日志等）。

### 3.1 表盘资源校验接口完整流程

**接口**：`POST /servicesupport/theme/v2/service/resource/checkright`

```
端侧（手表/手机）
   │  ① 携带请求头(x-authType/x-userToken/x-clienttraceid/x-appid) + 请求体(hitopId/screen/version/mode/huid...)
   ▼
ServiceComb 网关 / 微服务框架
   │  ② 路由到 checkWatchResourceRightController，解析请求头为 RequestV2Header
   ▼
Controller 层
   │  ③ passCheck() 校验请求头必填项（authtype/userToken/clienttraceid/appid）
   │  ④ RequestParameterUtils.validate() 校验请求体
   │  ⑤ 校验失败 → 记录错误日志 → 返回 PARAMETERERROR
   ▼
Service 层（getWatchResourceRight）
   │  ⑥ checkUserId()：ThreadLocal 取 userId → SHA-256 → 与端侧 huid 比对（防越权）
   │     不一致 → 返回 USER_AUTH_FAILD
   ▼
getWatchResourceRightResp 主流程
   │  ⑦ 通过 hitopId 查 workId（DCS/MySQL）
   │  ⑧ 查资源模型 ResourceDcsModel（DCS 缓存 / MySQL）
   │  ⑨ 判断资源类型（免费/付费/会员/不存在）→ 判断是否需要"资源回收时会员签名"
   │  ⑩ 逃生白名单判断 → 命中则放通（RELEASE）
   │  ⑪ 设计师自测场景（特殊 hitopId）→ 校验设计师账号
   │  ⑫ 资源来源判断：本云 / 联盟 TCS / 双活
   ▼
checkStatusAndBuildResp（核心）
   │  ⑬ 本云：queryResourceItemByHitopIdIgnoreState（MySQL，含下架资源）
   │  ⑭ 若本云无资源 → 联盟 TCS 查询（保密资源 + 待测试资源）
   │  ⑮ 若均无资源 → 调用运动健康云 getWatchfaceRightFromHealth
   │        · 先查 DCS 缓存（key=请求体 SHA-256）
   │        · 未命中 → HTTP 调用健康云 → 结果写回 DCS 缓存
   │        · 健康云异常 → 按配置开关决定放通/非法
   │  ⑯ 判断表盘合法状态（状态机：LEGAL/ILLEGAL/RELEASE/MEMBER_STATUS...）
   │  ⑰ 取表盘文件 hash（MySQL 查询 watchface.bin / com.huawei.watchface）
   ▼
签名与出参
   │  ⑱ 对响应内容做 RSA-SHA256withPSS 签名（MCU/AP 不同私钥，BouncyCastle 解析）
   ▼
审计落库
   │  ⑲ SDS 记录签名结果（t_resource_sign_record）
   │  ⑳ 错误日志落库（saveWatchfaceErrorLog）
   ▼
返回 WatchfaceCheckRightResp（resultcode/resultinfo/hash/status）
```

**涉及的中间件**：
| 中间件 | 作用 | 出现环节 |
|--------|------|----------|
| **DCS（Redis）** | 分布式缓存：缓存健康云查询结果、资源模型 | ⑧⑮ |
| **MySQL / GaussDB** | 业务数据存储：资源模型、文件 hash、设计师账号 | ⑦⑧⑬⑰ |
| **SDS** | 结构化数据存储：审计打点（签名记录、会员签名记录） | ⑲ |
| **配置中心 IAC** | 动态配置：白名单/黑名单、降级开关、缓存 TTL、私钥配置 | ⑩⑮⑱ |
| **ServiceComb** | 微服务框架：路由、RPC、请求上下文 | ② |
| **OAuth2 / UP** | 鉴权与令牌获取 | 请求头校验 |
| **日志系统（CallLog/告警）** | 调用日志、告警日志、traceId 追踪 | 全程 |

---

### 3.2 栏目详情接口完整流程

**接口**：`POST /servicesupport/theme/v2/restrict/column/common/column-detail`

```
端侧（手机/折叠屏）
   │  ① 携带请求头(osType/language/appId/hc/phoneType/deviceModel...) + 请求体(columnList/siteId/mediaDeviceInfo/localResourceIds...)
   ▼
ServiceComb 网关 / 微服务框架
   │  ② 路由到 columnDetailController，从 ContextUtils 解析请求头为 ColumnDetailHeader
   ▼
Controller 层
   │  ③ ValidatorUtils.validate(columnDetailHeader) 校验请求头
   │  ④ 校验失败 → 返回 HEAD_PARAM_ERROR
   │  ⑤ 个人开关(personalSwitch)开启 → 快速路径直接返回 SUCCESS
   ▼
Service 层（getColumnDetail）
   │  ⑥ shouldReturnEmptyListBasedOnConfig：harmonyApiLevel→osVersion，命中配置则返回空列表（现网规避）
   │  ⑦ buildFilterBean：构建资源过滤参数
   │     · 设备信息→screenCode/clientType（折叠屏特殊处理 FOLD）
   │     · 语言适配、地区(isoCode)、机型(phoneCode)
   │     · 从配置读取 isVipVersion/cipherVersion/supportProductType
   ▼
dealWithColumn（多线程并行）
   │  ⑧ 遍历 columnList，每个栏目提交 ColumnDetailRespTask 到线程池（EXECUTOR）
   │     · 子线程 run() 中重设 traceId（保证日志可追溯）
   │     · 线程池参数从配置中心读取，CallerRunsPolicy 拒绝策略
   │  ⑨ Future.get() 收集各栏目结果
   ▼
getColumnDetailResp（单栏目处理）
   │  ⑩ 根据 siteId 获取定投广告栏目列表（按优先级排序取前 2 个）
   │  ⑪ 本地已下载资源去重（localResourceIds）
   │  ⑫ 从第一个栏目取内容（getColumnDetailFromColumnAd）
   │  ⑬ 内容数 < 3 → 取第二个栏目兜底（getFallbackColumnDetail）
   ▼
资源过滤与组装
   │  ⑭ ResourceFilterUtils 多维度过滤（付费/设备/地区/版本/语言）
   │  ⑮ ContentResourceBuildHelper 组装资源响应
   ▼
返回 ColumnDetailResp（data=各栏目内容列表）
```

**涉及的中间件**：
| 中间件 | 作用 | 出现环节 |
|--------|------|----------|
| **DCS（Redis）** | 分布式缓存：缓存热点栏目/资源数据 | ⑩⑭ |
| **MySQL / GaussDB** | 业务数据存储：栏目、定投广告、资源数据 | ⑩⑭ |
| **配置中心 IAC** | 动态配置：线程池参数、去重开关、空列表规避配置、isVipVersion 等 | ⑥⑦⑧ |
| **ServiceComb** | 微服务框架：路由、请求上下文（ContextUtils） | ② |
| **多线程（ThreadPoolExecutor/FutureTask）** | 并行加载、traceId 传递 | ⑧⑨ |
| **日志系统** | traceId 追踪、结构化日志 | 全程 |

---

### 3.3 两个接口的中间件对比小结

| 中间件 | 表盘签名服务 | 栏目分发服务 |
|--------|:---:|:---:|
| DCS（Redis） | ✅ 健康云结果缓存 | ✅ 热点数据缓存 |
| MySQL / GaussDB | ✅ 资源/文件 hash | ✅ 栏目/资源数据 |
| SDS | ✅ 审计打点 | — |
| 配置中心 IAC | ✅ 开关/白名单/私钥 | ✅ 线程池/过滤配置 |
| ServiceComb | ✅ | ✅ |
| 多线程 | — | ✅ 并行加载 |
| OAuth2 / UP | ✅ 鉴权 | — |
| 日志系统 | ✅ 调用/告警日志 | ✅ traceId 日志 |

---

## 四、简历项目描述（STAR 法则版，可直接使用）

> **STAR 法则**：Situation（背景/情境）→ Task（任务/目标）→ Action（行动/做法）→ Result（结果/成效）。
> 简历中建议每个项目用 STAR 结构组织，重点突出 **Action（你的具体做法）** 和 **Result（可量化的成效）**。

### 项目一：华为主题云 — 表盘资源签名校验服务

**时间**：（填写在职时间段）
**角色**：Java 后端开发工程师

#### S（Situation）背景
华为主题云（ThemeCloud）是华为终端云服务旗下的主题商店后端系统，包含约 28 个微服务模块。表盘资源签名校验服务负责对手表表盘资源进行合法性校验和数字签名，确保只有经过授权的表盘才能在华为手表上安装使用。随着手表用户规模增长，出现了**盗版表盘、越权安装、端侧数据被篡改**等安全风险，且健康云等外部依赖故障时会导致服务不可用。

#### T（Task）任务
- 设计并实现表盘资源合法性校验与数字签名接口，覆盖 MCU（运动表）与 AP（智能表）两种设备类型
- 保证权益判断的**正确性**（免费/付费/会员/试用等类型不误判）与接口的**高可用**（外部依赖故障不级联）
- 保障端到端**安全**（防篡改、防伪造、防越权）

#### A（Action）行动
1. **接口设计**：设计并实现表盘资源校验、SDK 签名、会员签名三个接口，统一走 Controller → Service → Util → DAO 分层，异常分层捕获（ThemeException → Exception → Throwable）统一返回错误码，接口不裸抛异常
2. **权益判断**：设计链式优先级判断策略（试用标记 → 联盟资源 → 资源不存在放通 → 免费/已购 → 会员资源 → 试用期 → 非法），用状态机枚举（LEGAL/ILLEGAL/RELEASE/MEMBER_STATUS 等）组织，保证每种情况有明确处理路径
3. **身份校验**：将 ThreadLocal 中的 userId 做 SHA-256 与端侧上报的 huid 比对，防止伪造身份越权
4. **数字签名**：使用 BouncyCastle 解析 PKCS8/PEM 加密私钥，AES-GCM（KEK）解密私钥口令，RSA-SHA256withPSS 对响应内容签名，MCU 与 AP 使用不同私钥
5. **多级缓存与降级**：DCS（Redis）缓存健康云查询结果（key 为请求体 SHA-256），健康云异常时通过配置开关决定是否放通，避免级联故障；逃生白名单/黑名单、资源为空放通等开关均通过配置中心（IAC）动态管理
6. **审计与可追溯**：SDS 记录每次签名结果与会员签名记录，错误日志落库，便于监控与问题定位

#### R（Result）结果
- 三个接口稳定上线，覆盖 MCU/AP 全量设备类型，权益判断正确率达标，未出现误放通/误拦截事故
- 健康云故障时通过降级放通，**服务可用性显著提升**，未因外部依赖故障导致整体不可用
- 端到端 RSA 签名保障数据防篡改、防伪造，安全风险得到有效控制
- 配置化开关实现**无需发版即可应急调整**，缩短了线上问题响应时间

**技术栈**：Java 21、Spring MVC、Apache ServiceComb、MyBatis、MySQL、DCS（Redis）、BouncyCastle、Fastjson2

**项目亮点**
- 链式策略 + 状态机实现复杂权益判断，代码清晰可维护
- 多级缓存 + 降级放通确保高可用
- RSA 数字签名 + 私钥安全管理保障端到端安全

---

### 项目二：华为主题云 — 栏目内容分发服务

**时间**：（填写在职时间段）
**角色**：Java 后端开发工程师

#### S（Situation）背景
主题商店首页需要加载多个栏目的内容（推荐、热门、新品等），每个栏目需要从不同数据源获取内容并进行广告匹配和资源过滤。**传统串行加载方式响应慢**，首页首屏体验差，且不同设备（折叠屏、不同系统版本、不同地区）需要看到适配的内容。

#### T（Task）任务
- 设计并实现栏目详情接口，返回栏目内容列表
- 降低多栏目加载的**接口响应时间**，提升首页首屏体验
- 保证不同设备看到**适配且完整**的内容（过滤 + 兜底）

#### A（Action）行动
1. **接口设计**：设计并实现栏目详情接口，请求头校验（ValidatorUtils）失败返回 `HEAD_PARAM_ERROR`，个人开关开启时走快速路径直接返回
2. **多线程并行加载**：使用自定义 ThreadPoolExecutor（核心/最大线程数、队列大小均从配置中心读取）+ FutureTask 实现多栏目并行加载；自定义 `ColumnDetailRespTask` 继承 FutureTask，在子线程 `run()` 中重设 traceId，保证多线程日志可追溯；采用 `CallerRunsPolicy` 拒绝策略避免任务丢失
3. **多维度资源过滤**：构建 `ResourceFilterBean`，综合设备信息（screen、clientType、折叠屏特殊处理）、语言、地区、机型、付费状态、系统版本等多维度过滤，保证内容适配
4. **兜底机制**：从定投广告栏目列表（按优先级取前 2 个）中先取第一个栏目，内容数少于 3 个时自动切换到备用栏目，保证页面展示完整
5. **DCS 缓存**：缓存热点数据，减少数据库查询压力

#### R（Result）结果
- 多栏目并行加载显著降低接口响应时间，**首页首屏加载速度明显提升**（如有真实数据可补充：响应时间降低 XX%）
- 多线程日志通过 traceId 可完整串联，**线上问题定位效率提升**
- 多维度过滤 + 兜底机制保证不同设备看到适配且完整的内容，**页面空白率下降**
- 线程池参数配置化，**无需发版即可按流量动态调整**

**技术栈**：Java、Spring MVC、ServiceComb、MyBatis、MySQL、DCS（Redis）、多线程（FutureTask/ThreadPoolExecutor）

---

## 五、面试官可能追问的问题与标准应答

### 5.1 关于表盘签名校验服务

**Q1：这个接口的核心难点是什么？**
> 核心难点是**权益判断的复杂性和正确性**。表盘资源有多种类型（免费、付费、会员、试用、联盟资源、健康云资源），每种类型的判断逻辑不同，且存在优先级关系。我通过链式判断 + 状态机枚举（LEGAL/ILLEGAL/RELEASE/MEMBER_STATUS 等）来组织逻辑，保证每种情况都有明确的处理路径，避免遗漏和歧义。

**Q2：为什么用 RSA 签名？签名的作用是什么？**
> 签名的作用是**防篡改和防伪造**。端侧（手表）无法直接信任服务端返回的数据，通过 RSA 私钥对响应内容签名，端侧用公钥验签，可以确认数据确实来自服务端且未被篡改。选择 RSA-SHA256withPSS 是因为 PSS 填充比 PKCS1 更安全（随机化填充，抗选择密文攻击）。MCU 和 AP 用不同私钥是为了隔离不同设备类型的风险。

**Q3：私钥是怎么安全管理的？**
> 私钥以加密形式存储在配置中心（IAC），通过 KEK（Key Encryption Key）用 AES-GCM 解密私钥口令，再用口令解密 PEM 私钥。私钥不会以明文形式出现在代码或配置中，即使配置文件泄露也无法直接使用。

**Q4：健康云调用失败时怎么处理？**
> 采用**降级策略**。健康云异常时，通过配置开关 `tis.watchface.health.exception.release.switch` 决定是放通（RELEASE）还是返回非法。默认情况下，为了避免影响用户体验，会放通请求；同时记录错误日志和调用日志（CallLog）用于监控。这样即使健康云故障，也不会导致整个服务不可用。

**Q5：缓存是怎么设计的？有什么考虑？**
> 健康云查询结果缓存到 DCS（Redis），key 是请求体的 SHA-256 哈希，避免重复查询。缓存时间通过配置控制。考虑到表盘权限可能变化，缓存时间不宜过长；同时缓存能显著降低对健康云的调用压力。另外有逃生白名单/黑名单机制，白名单内的手表型号直接放通，不查询 hash。

**Q6：如何保证接口的高可用？**
> 从几个层面：① 异常分层捕获，接口不裸抛异常，统一返回错误码；② 健康云等外部依赖异常时降级放通，避免级联故障；③ 多级缓存（DCS）降低下游压力；④ 配置中心动态调整开关，无需发版即可应急；⑤ 审计日志 + 调用日志用于监控和问题定位。

### 5.2 关于栏目内容分发服务

**Q1：为什么用多线程？怎么保证线程安全？**
> 首页有多个栏目需要并行加载，串行会显著增加响应时间。每个栏目是独立的 FutureTask 提交到线程池，各栏目之间无共享可变状态，天然线程安全。线程池的核心/最大线程数、队列大小都从配置中心读取，可动态调整。使用 `CallerRunsPolicy` 拒绝策略，队列满时由调用线程执行，避免任务丢失。

**Q2：多线程下日志怎么保证可追溯？**
> 自定义了 `ColumnDetailRespTask` 继承 `FutureTask`，在 `run()` 方法中重新设置 traceId 到 ThreadContext 和 ThreadLocal，任务结束后清理。这样每个子线程的日志都带有正确的 traceId，方便通过 traceId 串联整个请求链路定位问题。

**Q3：资源过滤是怎么做的？**
> 构建一个 `ResourceFilterBean`，包含设备信息（screen、clientType、osversion）、语言、地区、机型、付费状态、系统版本等多维度参数，然后通过 `ResourceFilterUtils` 进行统一过滤。过滤参数从请求头、设备信息、配置中心综合构建，保证不同设备看到的内容是适配的。

**Q4：栏目内容不足时怎么处理？**
> 设计了**兜底机制**。从定投广告栏目列表（按优先级排序取前 2 个）中，先取第一个栏目，如果内容数少于 3 个，则切换到第二个栏目作为兜底，保证页面展示的完整性，避免出现空白栏目。

**Q5：这个接口和表盘签名接口在架构上有什么共同点？**
> 两者都是标准的 Controller → Service → DAO 三层架构，都使用 ServiceComb 微服务框架和 `@RestSchema` 注解，都从请求头解析用户上下文，都有异常统一处理和审计日志。区别在于：签名服务更侧重安全（签名、鉴权、防越权），栏目服务更侧重性能（多线程并行、资源过滤）。

### 5.3 通用问题（结合 Agent 开发岗位）

**Q1：这两个 Java 项目对你做 Agent 开发有什么启发？**
> ① **状态机思想**：表盘权益判断的状态机（LEGAL/ILLEGAL/RELEASE 等）与 Agent 工作流的状态管理异曲同工，Agent 的每个阶段也需要明确的状态和转移条件；② **降级策略**：健康云异常时放通的降级设计，与 Agent 中 LLM 不可用时降级到规则引擎的思路一致；③ **可观测性**：traceId 贯穿多线程、审计日志落库，对应 Agent 系统的结构化日志和会话可追溯；④ **配置化**：通过配置中心动态调整开关，对应 Agent 系统的可配置化设计。

**Q2：Java 的哪些能力可以迁移到 Agent 开发？**
> ① 多线程与并发（FutureTask、线程池）→ Agent 的并行执行（SubAgent、ParallelRunner）；② 设计模式（策略、模板方法、工厂）→ Agent 的可扩展架构；③ 异常处理与降级 → Agent 的优雅降级；④ 缓存与性能优化 → Agent 的上下文管理；⑤ 日志与可观测性 → Agent 的进度推送与追踪。

---

## 六、面试表达要点（如何"讲"出亮点）

1. **先讲业务价值，再讲技术实现**：例如"这个接口保证只有授权的表盘才能安装，防止盗版和越权"，比直接讲"我用了 RSA 签名"更有说服力。
2. **突出难点和你的思考**：不要只罗列做了什么，要讲"为什么这么做"和"遇到了什么困难、怎么解决"。
3. **用数据说话**：多线程并行加载"响应时间降低 XX%"，缓存"QPS 提升 XX 倍"（如有真实数据可补充）。
4. **主动关联 Agent 岗位**：把 Java 项目中的设计思想（状态机、降级、可观测性、配置化）主动映射到 Agent 开发，体现你的迁移能力和思考深度。
5. **准备好"被挑战"的点**：例如"为什么不用 JWT 而用 RSA 签名""线程池参数怎么定的""缓存一致性怎么保证"，提前想好答案。

---

## 七、风险提示与诚实原则

- 简历中描述的项目应基于**真实参与**的工作，不要虚构不存在的功能或数据。
- 面试官可能深挖细节，务必对每个技术点（RSA 签名、线程池、缓存、降级）有深入理解，能讲清原理。
- 如果某些功能不是你独立完成的，用"参与""负责其中 XX 部分"等准确表述，避免被追问时露馅。
- 涉及公司内部信息（接口路径、配置项、密钥管理细节）时，面试中可适当抽象表述，注意保密。

---

## 八、需求背景、防范场景与性能表现（基于《表盘防黑产特性》《表盘市场黑产分析报告》）

> 本节补充表盘签名校验服务的**立项背景、要防范的黑产场景、以及上线后的性能与收益数据**，用于在面试中讲清"为什么做、防什么、效果如何"。

### 8.1 需求背景（为什么做）

**黑产现状**
- 现有表盘连接方式安全效果欠佳，出现**黑产情况**：用户可通过不正当手段**免费获取付费表盘资源**，对设计师权益造成损害。
- 黑产分析报告显示，攻击者通过**破解重签名运动健康 APP**（Xpatch 二次打包 + Xposed 插件免 Root Hook），实现：
  - 修改运动健康部分页面（绕过正版校验）
  - **试用中通过 Hook 触发购买表盘方法**（绕过付费）
  - **设计师上传表盘入口强制修改成 true**（绕过审核/权限）

**需求目标**
- 在表盘资源下载/安装时，采用新的方案**加强链路安全**。
- 方案整体逻辑：用户**安装表盘（一期）或下载表盘（二期）**时，端侧请求主题云获取"用户是否拥有该资源使用权 + 资源的文件 hash 值"等信息并进行校验；**校验不通过则删除表盘**，达到防止黑产的目的。

**三期演进**
| 期次 | 对接模块 | 端侧调用方式 | 用户 id 校验 | 调用时机 | 试用判断 |
|------|----------|--------------|--------------|----------|----------|
| 一期 | 手表侧（智能表/运动表）、运动健康 APP | 手表通过运动健康 APP 的 HttpProxy 调用主题云 | 解析 userToken 获取用户 id，与端侧上报 id 匹配 | 下载完表盘、安装时调用 | 主题云查询试用记录表 |
| 二期 | 手表侧、表盘 SDK | 手表通过表盘 SDK 调用主题云 | 端侧不上报用户 id，主题云解析 userToken | 下载表盘时调用 | 端侧上报试用标记则直接返回试用期合法 |
| 三期 | 运动健康云 + 一期/二期全部模块 | / | / | / | / |

> 三期是在前两期接口中**增加对接运动健康云的逻辑**，用于在主题云/联盟均查不到资源时，向运动健康云兜底查询表盘权限。

### 8.2 要防范的黑产场景

1. **破解重签名**：攻击者用 Xpatch 对运动健康 APP 二次打包重签名，加载 Xposed 插件免 Root Hook，篡改页面与购买逻辑
2. **绕过付费**：试用中通过 Hook 触发购买表盘方法，免费获取付费表盘
3. **绕过审核**：强制修改设计师上传表盘入口为 true，绕过权限校验
4. **越权/伪造身份**：端侧伪造用户 id（huid），冒充已购买用户
5. **数据篡改**：端侧篡改响应数据，伪造"已购买/合法"状态

**对应防护手段**：
- 端侧安装/下载时调用主题云校验资源使用权 + 文件 hash，**校验不通过删除表盘**
- 用户 id 校验（SHA-256 比对 huid，防伪造身份）
- RSA-SHA256withPSS 数字签名（防响应数据篡改，端侧可验签）
- 文件 hash 比对（防文件被替换/篡改）

### 8.3 性能与收益表现

**上线与覆盖**
- 特性于 **2025 年 4 月上线**，支持的手表型号逐步增加，截至 **2026 年 3 月已支持 25 款**手表型号。

**防黑产收益（核心数据）**
- 累计**防范可能的黑产请求次数：43023 次**
- 按表盘平均单价 **6 元**计算，**挽回经济损失约 24 万元+**
- 随着支持该功能手表型号增多，挽回损失持续增加

**接口性能（压测结果）**
- 压测配置：**并发数 80，压测时长 5 分钟**（VUM = 虚拟并发用户数 × 分钟）
- 在双框上新增用例跑的结果（见《表盘防黑产特性》压测结果附件）

**现网运行情况**
- **2 天内调用量 74.2 万**，**平均时延 28.11ms**，性能表现良好，满足高并发场景。

### 8.4 上线后的问题与解决（体现工程能力）

**① 三期众测后手表反馈大部分官方表盘下载失败**
- 原因：运动健康内网 ELB 对 https 配置的是 **ECC 类型证书**，TLS1.2 只支持 `ECDHE-ECDSA-AES256-GCM-SHA384`、`ECDHE-ECDSA-AES128-GCM-SHA256` 两个加密算法；主题云作为客户端当前配置的加密算法不在运动健康云支持范围内，导致调用健康云接口失败（`SSLHandshakeException`），主题云接口返回系统错误
- 解决：主题云通过配置项新增 http 加密算法 `ECDHE-ECDSA-AES256-GCM-SHA384`、`ECDHE-ECDSA-AES128-GCM-SHA256`

**② 预置表盘安装失败**
- 原因：手表侧误报预置表盘的 hitopId 为表盘名，主题云和运动健康云查询不到表盘信息，返回资源不合法；且"计时码表"表盘英文名超过运动健康云 hitopId 长度限制
- 规避：将 `tis.release.empty.watch.resource.switch` 改为 true，放通查不到资源时的请求（暴露黑产漏洞）；手表侧修改预置表盘上报的 hitopId，运动健康云 hitopId 参数校验逻辑与主题云保持一致

**③ AP 模式下应用会员免费表盘失败**
- 原因：应用表盘时表侧校验会员免费表盘签名里的 hitopId 与蓝牙指令中的 hitopId 不一致，导致验签失败
- 规避：短期内删除主题云侧表盘签名白名单中 watch5 的设备型号

**④ FIT4 部分官方表盘下载失败**
- 原因：部分 FIT4 官方表盘资源在运动健康云管理台更新后未同步更新主题云，导致相同表盘 id 相同版本在健康云和主题云上文件包不一致，验签失败
- 规避：主题云在现网防黑产白名单 `tis.watch.sign.whitelist` 中去除 FIT4 系列手表；设备侧在运动健康云更新官方表盘后同步更新到主题云

**需求遗留问题（体现前瞻思考）**
- 当前通过配置项（白名单 `tis.watch.sign.whitelist` / 黑名单 `tis.watch.sign.blacklist`）控制，新增手表需提交 iac 变更；希望**通过主题管理台的机型配置统一维护**，在机型配置中增加签名开关 SignFlag
- **表盘防黑产能力出海**：黑产国内上线后，海外账号 + 国内手表应用表盘会失败（海外未下发签名），需尽快排入

### 8.5 面试表达要点（结合本节数据）

1. **讲清"为什么做"**：先讲黑产现状（破解重签名、Hook 绕过付费、免费获取付费表盘损害设计师权益），再讲方案目标（校验资源使用权 + 文件 hash，不通过删除表盘）
2. **用数据量化收益**：防范黑产请求 43023 次、挽回损失约 24 万元+、支持 25 款手表、2 天调用量 74.2 万、平均时延 28.11ms
3. **讲清三期演进**：一期（安装时校验）→ 二期（下载时校验 + SDK）→ 三期（对接运动健康云兜底），体现需求迭代与架构演进能力
4. **展示问题解决能力**：上线后遇到的 SSL 证书算法不匹配、预置表盘 hitopId 误报、验签不一致、FIT4 文件包不一致等问题及解决思路，体现工程落地与现网保障能力
5. **展示前瞻思考**：机型配置化替代黑白名单、防黑产能力出海，体现对产品演进方向的思考
