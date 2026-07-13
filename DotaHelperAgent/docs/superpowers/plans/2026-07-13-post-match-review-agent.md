# 二十三、赛后复盘 Agent 综合设计方案 — 详细设计

> 分析时间：2026-07-13
> 参考项目：
> - Claude Code: `D:\trae_projects\claude-code-best_claude-code`
> - Hermes Agent: `D:\trae_projects\hermes-agent`
> - 当前项目: `D:\trae_projects\first-agent\DotaHelperAgent`
> 来源: ARCHITECTURE_ANALYSIS.md 第二十三章

本章综合两个参考项目的设计模式，结合当前项目架构，给出赛后复盘 Agent 的具体迁移方案。

## 23.1 赛后复盘 Agent 核心流程

```
用户输入 match_id
  │
  ▼
┌─────────────────────────────────────────────────┐
│  Phase 0: 数据获取                               │
│  ├─ 调用 OpenDota API 获取比赛详情               │
│  └─ 解析并结构化比赛数据                         │
├─────────────────────────────────────────────────┤
│  Phase 1: 多阶段分析（Loop Agent 模式）          │
│  ├─ 对线期分析（0-10 分钟）                      │
│  ├─ 团战执行分析                                 │
│  ├─ 经济效率分析                                 │
│  └─ 关键决策点分析                               │
│  [每阶段受迭代预算控制 + 边际收益递减检测]        │
├─────────────────────────────────────────────────┤
│  Phase 2: 验证停止检查                           │
│  ├─ 每个结论是否有数据支撑？                     │
│  ├─ 所有必要分析阶段是否完成？                   │
│  └─ 置信度是否达标？                             │
│  [不通过 → 返回 Phase 1 补充分析]                │
├─────────────────────────────────────────────────┤
│  Phase 3: 报告生成                               │
│  ├─ 聚合各阶段分析结果                           │
│  ├─ 生成 Markdown 结构化报告                     │
│  └─ 导出到文件                                   │
├─────────────────────────────────────────────────┤
│  Phase 4: 后台自我审查（异步）                   │
│  ├─ 审查分析质量                                 │
│  └─ 改进记忆和技能                               │
└─────────────────────────────────────────────────┘
```

## 23.2 设计模式来源映射

| 赛后复盘需求 | Claude Code 来源 | Hermes Agent 来源 | 当前项目对应 | 迁移策略 |
|------------|-----------------|------------------|------------|---------|
| **多阶段循环分析** | Loop Agent（时间驱动周期执行） | `conversation_loop.py`（状态机 + 重试 + 中断） | `AgentController.solve()` ReAct 循环 | 采用 Hermes 的状态机模式，支持阶段间跳转和中断恢复 |
| **迭代预算控制** | Token 预算（`COMPLETION_THRESHOLD=0.9` + 边际递减检测） | `IterationBudget`（令牌桶 + 退还机制） | `turn_count` 简单计数 | **融合两者**: Hermes 的令牌桶 + Claude Code 的边际递减检测 |
| **终止条件验证** | Stop Hooks（10 种终态 + 7 种继续态） | `verification_stop` + `verify_hooks`（代码验证 + 可配置钩子） | `_should_finalize()` 质量评分 | **融合两者**: Claude Code 的类型化终态 + Hermes 的验证钩子 |
| **上下文压缩** | 无直接对应 | `ContextCompressor`（有损压缩: 修剪工具结果 + 保护头尾 + LLM 摘要中间） | `ConversationManager.compress_context()` 分层压缩 | 采用 Hermes 的有损压缩，适配复盘数据特点 |
| **复盘提示词构建** | Dream/Recap（`buildConsolidationPrompt`） | `prompt_builder` + `system_prompt`（三层分离） | `PromptManager` | 采用 Claude Code 的整合模式 + Hermes 的三层分离 |
| **并行分析阶段** | Batch 并行子代理（Phase 1-2-3） | `moa_loop.py`（多模型聚合） | `ParallelExecutor` | 采用 Claude Code 的 Batch 模式，各分析阶段并行 |
| **中断恢复** | QueryEngine 生命周期（`interrupt()` + 部分结果提取） | `conversation_loop.py` 中断模式 | 无 | 采用 Claude Code 的中断 + 部分结果提取 |
| **后台自我审查** | 无直接对应 | `background_review.py`（fork agent 自我审查） | 无 | 新增，采用 Hermes 的后台审查模式 |
| **轨迹持久化** | 无直接对应 | `trajectory.py` + `trajectory_compressor.py` | Langfuse trace | 采用 Hermes 的轨迹格式，用于复盘分析存档 |
| **Skill 配置** | 条件激活（`paths` + frontmatter） | `skill_bundles.py`（YAML 配置 + 平台过滤） | `SkillRegistry` | 采用 Hermes 的 YAML 配置，支持复盘 Skill 声明式定义 |

## 23.3 核心组件详细设计

### 23.3.1 迭代预算控制

**融合策略**: Hermes 令牌桶 + Claude Code 边际递减检测

```python
from enum import Enum
from threading import Lock

class BudgetDecision(Enum):
    """预算决策"""
    CONTINUE = "continue"               # 继续执行
    STOP_BUDGET_EXHAUSTED = "stop_budget_exhausted"  # 预算耗尽
    STOP_DIMINISHING = "stop_diminishing"  # 边际收益递减
    STOP_COMPLETION = "stop_completion"  # 接近完成阈值

class ReviewIterationBudget:
    """复盘迭代预算控制器

    融合来源:
    - Hermes Agent: IterationBudget（令牌桶 + 退还机制）
    - Claude Code: TokenBudget（边际递减检测 + 完成阈值）
    """

    # Claude Code 常量
    COMPLETION_THRESHOLD = 0.9       # 90% 预算时视为接近完成
    DIMINISHING_THRESHOLD = 500      # 连续两次增量 < 500 token 判定递减
    MIN_CONTINUATIONS = 3            # 至少继续 3 次后才检测递减

    def __init__(self, max_iterations: int, max_tokens: int = 100_000):
        # Hermes: 令牌桶
        self._max_iterations = max_iterations
        self._used_iterations = 0
        self._lock = Lock()

        # Claude Code: Token 追踪
        self._max_tokens = max_tokens
        self._used_tokens = 0
        self._continuation_count = 0
        self._last_delta_tokens = 0

    def consume(self, delta_tokens: int = 0) -> BudgetDecision:
        """消费一个迭代配额

        Args:
            delta_tokens: 本轮消耗的 token 数

        Returns:
            BudgetDecision: 是否继续
        """
        with self._lock:
            # 1. 检查迭代次数上限（Hermes）
            if self._used_iterations >= self._max_iterations:
                return BudgetDecision.STOP_BUDGET_EXHAUSTED

            # 2. 检查 Token 完成阈值（Claude Code）
            self._used_tokens += delta_tokens
            if self._used_tokens >= self._max_tokens * self.COMPLETION_THRESHOLD:
                return BudgetDecision.STOP_COMPLETION

            # 3. 边际收益递减检测（Claude Code）
            if (self._continuation_count >= self.MIN_CONTINUATIONS and
                delta_tokens < self.DIMINISHING_THRESHOLD and
                self._last_delta_tokens < self.DIMINISHING_THRESHOLD):
                return BudgetDecision.STOP_DIMINISHING

            # 4. 通过，记录状态
            self._used_iterations += 1
            self._continuation_count += 1
            self._last_delta_tokens = delta_tokens
            return BudgetDecision.CONTINUE

    def refund(self) -> None:
        """退还一个迭代配额（Hermes 特性）

        应用场景: 某分析阶段一次就得到高质量结论，
        无需额外迭代，退还配额给其他阶段使用。
        """
        with self._lock:
            self._used_iterations = max(0, self._used_iterations - 1)

    @property
    def remaining_iterations(self) -> int:
        return self._max_iterations - self._used_iterations

    @property
    def remaining_tokens(self) -> int:
        return self._max_tokens - self._used_tokens
```

**复盘应用场景**:

| 分析阶段 | 预算分配 | 退还场景 |
|---------|---------|---------|
| 对线期分析 | 3 次迭代 | 一次 LLM 调用就得到完整分析 → 退还 2 次 |
| 团战分析 | 5 次迭代 | 团战数据复杂，可能需要全部 5 次 |
| 经济分析 | 2 次迭代 | 数据驱动为主，1 次即可 → 退还 1 次 |
| 决策点分析 | 3 次迭代 | 需要结合前几阶段结论，可能需要全部 |

### 23.3.2 验证停止机制

**融合策略**: Claude Code 类型化终态 + Hermes 验证钩子

```python
from enum import Enum
from dataclasses import dataclass, field
from typing import List, Optional

class ReviewTerminalState(Enum):
    """复盘终态（来源: Claude Code transitions.ts）"""
    COMPLETED = "completed"                    # 所有分析阶段完成
    MAX_ITERATIONS = "max_iterations"          # 达到最大迭代
    BUDGET_EXHAUSTED = "budget_exhausted"      # Token 预算耗尽
    VERIFICATION_BLOCKED = "verification_blocked"  # 验证阻止继续
    INTERRUPTED = "interrupted"                # 用户中断

class ReviewContinueState(Enum):
    """复盘继续态（来源: Claude Code transitions.ts）"""
    NEXT_PHASE = "next_phase"                  # 进入下一阶段
    LOW_CONFIDENCE = "low_confidence"          # 置信度不足，补充分析
    VERIFICATION_RETRY = "verification_retry"  # 验证未通过，重新分析
    TOKEN_BUDGET_OK = "token_budget_ok"        # 预算充足，继续

@dataclass
class VerificationResult:
    """验证结果"""
    passed: bool
    blocking_reasons: List[str] = field(default_factory=list)
    suggestions: List[str] = field(default_factory=list)

class ReviewStopVerifier:
    """复盘停止验证器

    融合来源:
    - Claude Code: Stop Hooks（类型化终态/继续态）
    - Hermes Agent: verification_stop（数据支撑验证）
    """

    # 必须完成的分析阶段
    REQUIRED_PHASES = ["laning", "teamfight", "economy", "decisions"]

    # 最低置信度阈值
    MIN_CONFIDENCE = 0.6

    def verify(self, state: 'ReviewAgentState') -> VerificationResult:
        """验证是否满足终止条件

        在 Agent 尝试停止前调用，检查:
        1. 所有必要分析阶段是否完成（Hermes 验证停止）
        2. 每个结论是否有数据支撑（Hermes verification_stop）
        3. 置信度是否达标（Claude Code stop hook）
        """
        blocking = []
        suggestions = []

        # 检查 1: 必要分析阶段是否完成
        missing_phases = [
            p for p in self.REQUIRED_PHASES
            if p not in state.completed_phases
        ]
        if missing_phases:
            blocking.append(f"缺少分析阶段: {missing_phases}")
            suggestions.append(f"请补充分析: {', '.join(missing_phases)}")

        # 检查 2: 结论是否有数据支撑
        for conclusion in state.conclusions:
            if not conclusion.has_evidence:
                blocking.append(f"结论 '{conclusion.title}' 缺少数据支撑")
                suggestions.append(f"请为 '{conclusion.title}' 提供具体数据引用")

        # 检查 3: 置信度是否达标
        if state.confidence < self.MIN_CONFIDENCE:
            blocking.append(f"整体置信度 {state.confidence:.2f} 低于阈值 {self.MIN_CONFIDENCE}")
            suggestions.append("请补充关键数据或降低分析粒度")

        return VerificationResult(
            passed=len(blocking) == 0,
            blocking_reasons=blocking,
            suggestions=suggestions
        )
```

### 23.3.3 有损上下文压缩

**来源**: Hermes Agent `ContextCompressor`

```python
class ReviewContextCompressor:
    """复盘上下文压缩器

    来源: Hermes Agent context_compressor.py

    压缩算法:
    1. 修剪旧工具结果（无 LLM 调用，低成本）
    2. 保护头部消息（系统提示 + 比赛基本信息）
    3. 按 token 预算保护尾部消息（最近约 20K tokens）
    4. 使用 LLM 摘要中间轮次
    5. 迭代更新之前的摘要
    """

    # 保护区域配置
    HEAD_PROTECT_COUNT = 2       # 保护头部 2 条消息（系统提示 + 比赛数据）
    TAIL_TOKEN_BUDGET = 20_000   # 尾部保护 20K tokens
    TARGET_MAX_TOKENS = 15_250   # 压缩后目标 token 数
    SUMMARY_TOKEN_BUDGET = 750   # 摘要消息的 token 预算

    def compress(self, messages: List[Dict], current_tokens: int) -> List[Dict]:
        """执行有损压缩"""

        # 不需要压缩
        if current_tokens <= self.TARGET_MAX_TOKENS:
            return messages

        # Phase 1: 修剪旧工具结果（最低成本）
        messages = self._prune_tool_results(messages)

        # Phase 2: 划分保护区域
        head = messages[:self.HEAD_PROTECT_COUNT]
        tail = self._protect_tail(messages, self.TAIL_TOKEN_BUDGET)
        middle = self._extract_middle(messages, head, tail)

        # Phase 3: 摘要中间内容
        if middle:
            summary = self._summarize_middle(middle)
            summary_msg = {
                "role": "system",
                "content": f"[之前分析阶段的摘要] {summary}"
            }
            return head + [summary_msg] + tail

        return head + tail

    def _prune_tool_results(self, messages: List[Dict]) -> List[Dict]:
        """修剪旧的工具调用结果（无 LLM 调用）

        复盘场景: OpenDota API 返回的原始比赛数据在分析完成后
        可以安全修剪，只保留分析结论。
        """
        pruned = []
        for msg in messages:
            if msg.get("role") == "tool" and len(msg.get("content", "")) > 2000:
                # 截断过长的工具结果
                pruned.append({
                    **msg,
                    "content": msg["content"][:500] + "\n[...已截断...]"
                })
            else:
                pruned.append(msg)
        return pruned

    def _protect_tail(self, messages: List[Dict],
                      token_budget: int) -> List[Dict]:
        """从尾部开始保护消息，直到 token 预算耗尽"""
        protected = []
        remaining = token_budget
        for msg in reversed(messages):
            msg_tokens = self._estimate_tokens(msg)
            if msg_tokens > remaining:
                break
            protected.insert(0, msg)
            remaining -= msg_tokens
        return protected

    def _summarize_middle(self, middle: List[Dict]) -> str:
        """使用 LLM 摘要中间内容"""
        # 复用当前项目的 LLMClient
        content = "\n".join(m.get("content", "") for m in middle)
        prompt = f"请用 3-5 句话总结以下 Dota 2 比赛分析内容:\n{content}"
        # ... LLM 调用
        return prompt  # 简化示意
```

**复盘场景适配**:

| 消息类型 | 压缩策略 | 原因 |
|---------|---------|------|
| 系统提示 | 完整保留 | 分析指令不可丢失 |
| 比赛原始数据（API 返回） | 分析完成后修剪 | 数据量大，分析结论已提取关键信息 |
| 对线期分析结论 | 摘要保留 | 后续阶段可能需要引用 |
| 最近 20K tokens | 完整保留 | 当前分析上下文不可丢失 |

### 23.3.4 后台自我审查

**来源**: Hermes Agent `background_review.py`

```python
import threading
from typing import Optional

class BackgroundReviewSpawner:
    """后台自我审查

    来源: Hermes Agent background_review.py

    在复盘分析完成后，fork 一个 Agent 实例进行自我审查:
    - 评估分析质量
    - 提取可复用的分析模式
    - 改进记忆和技能
    """

    def __init__(self, llm_client, memory_manager):
        self.llm_client = llm_client
        self.memory_manager = memory_manager

    def spawn(self, match_data: Dict, review_report: str) -> None:
        """启动后台审查线程（不阻塞主流程）"""
        thread = threading.Thread(
            target=self._review_worker,
            args=(match_data, review_report),
            daemon=True
        )
        thread.start()

    def _review_worker(self, match_data: Dict, review_report: str) -> None:
        """审查工作线程"""
        try:
            # 1. 评估分析质量
            quality_assessment = self._assess_quality(review_report)

            # 2. 提取可复用的分析模式
            patterns = self._extract_patterns(match_data, review_report)

            # 3. 保存到记忆
            self.memory_manager.save_experience(
                experience_type="review_self_assessment",
                content={
                    "match_id": match_data.get("match_id"),
                    "quality": quality_assessment,
                    "patterns": patterns,
                    "improvements": quality_assessment.get("suggestions", [])
                }
            )
        except Exception as e:
            logger.warning(f"后台审查失败: {e}")

    def _assess_quality(self, report: str) -> Dict:
        """评估复盘报告质量"""
        prompt = f"""请评估以下 Dota 2 赛后复盘报告的质量:

{report}

评估维度:
1. 数据支撑度: 结论是否有具体数据引用？
2. 分析深度: 是否只停留在表面描述？
3. 可操作性: 改进建议是否具体可执行？
4. 完整性: 是否覆盖了对线/团战/经济/决策？

输出 JSON 格式:
{{"score": 0-1, "strengths": [...], "weaknesses": [...], "suggestions": [...]}}
"""
        # LLM 调用...
        return {}

    def _extract_patterns(self, match_data: Dict, report: str) -> List[str]:
        """提取可复用的分析模式"""
        # 例如: "逆风局翻盘的关键是视野控制" 这类通用模式
        return []
```

### 23.3.5 复盘提示词构建（三层分离）

**融合策略**: Claude Code Dream 整合模式 + Hermes 三层分离

```python
class ReviewPromptBuilder:
    """复盘提示词构建器

    融合来源:
    - Claude Code: Dream/Recap 的 buildConsolidationPrompt
    - Hermes Agent: system_prompt.py 的三层分离（stable/context/volatile）
    """

    def build(self, match_data: Dict,
              phase_results: List[Dict] = None) -> List[Dict]:
        """构建复盘提示词（三层结构）"""

        messages = []

        # Layer 1: Stable（稳定层 — 分析指令，不变）
        messages.append({
            "role": "system",
            "content": self._build_stable_layer()
        })

        # Layer 2: Context（上下文层 — 比赛数据）
        messages.append({
            "role": "user",
            "content": self._build_context_layer(match_data, phase_results)
        })

        return messages

    def _build_stable_layer(self) -> str:
        """稳定层: 分析角色和指令"""
        return """你是一位专业的 Dota 2 赛后复盘分析师。

## 分析框架
1. **对线期分析**（0-10 分钟）
   - 补刀效率评估（last_hits/denies vs 理论值）
   - 消耗换血质量
   - 神符利用率

2. **团战执行分析**（10-25 分钟）
   - 团战参与率
   - 技能释放时机评估
   - 走位和站位分析

3. **经济效率分析**
   - GPM/XPM 曲线 vs 分段位均值
   - 装备购买效率（空闲时间占比）
   - 关键装备时间节点

4. **关键决策点分析**
   - Roshan 时机选择
   - 推塔节奏
   - 团战发起/撤退决策

## 输出要求
- 每个结论必须引用具体数据
- 改进建议必须具体可执行
- 使用 Markdown 格式
- 包含评分（1-10）和置信度
"""

    def _build_context_layer(self, match_data: Dict,
                             phase_results: List[Dict] = None) -> str:
        """上下文层: 比赛数据 + 已有分析结果"""
        parts = []

        # 比赛基本信息
        parts.append(f"# 比赛基本信息\n"
                     f"- 比赛 ID: {match_data.get('match_id')}\n"
                     f"- 时长: {match_data.get('duration', 0) // 60} 分钟\n"
                     f"- 结果: {'胜利' if match_data.get('radiant_win') else '失败'}\n"
                     f"- 英雄: {match_data.get('hero_name', '未知')}")

        # 各阶段数据
        if match_data.get('laning_data'):
            parts.append(f"\n# 对线期数据\n{self._format_laning(match_data)}")
        if match_data.get('teamfight_data'):
            parts.append(f"\n# 团战数据\n{self._format_teamfights(match_data)}")
        if match_data.get('economy_data'):
            parts.append(f"\n# 经济数据\n{self._format_economy(match_data)}")

        # 已有分析结果（多轮迭代时）
        if phase_results:
            parts.append("\n# 已完成的分析\n")
            for pr in phase_results:
                parts.append(f"## {pr['phase']}\n{pr['analysis']}")

        return "\n".join(parts)
```

### 23.3.6 复盘 Agent 主循环

**融合所有设计模式的完整实现**:

```python
class PostMatchReviewAgent:
    """赛后复盘 Agent

    设计来源:
    - 主循环结构: Hermes conversation_loop.py
    - 迭代预算: Hermes IterationBudget + Claude Code TokenBudget
    - 停止验证: Claude Code Stop Hooks + Hermes verification_stop
    - 上下文压缩: Hermes ContextCompressor
    - 后台审查: Hermes background_review
    - 提示词构建: Claude Code Dream + Hermes 三层分离
    """

    # 分析阶段定义
    ANALYSIS_PHASES = [
        {"name": "laning", "label": "对线期分析", "max_iterations": 3},
        {"name": "teamfight", "label": "团战分析", "max_iterations": 5},
        {"name": "economy", "label": "经济分析", "max_iterations": 2},
        {"name": "decisions", "label": "决策点分析", "max_iterations": 3},
    ]

    def __init__(self, llm_client, api_client, memory_manager, config):
        self.llm_client = llm_client
        self.api_client = api_client
        self.memory_manager = memory_manager

        # 核心组件（融合两个项目）
        self.budget = ReviewIterationBudget(
            max_iterations=config.get("max_total_iterations", 15),
            max_tokens=config.get("max_tokens", 100_000)
        )
        self.verifier = ReviewStopVerifier()
        self.compressor = ReviewContextCompressor()
        self.prompt_builder = ReviewPromptBuilder()
        self.background_reviewer = BackgroundReviewSpawner(
            llm_client, memory_manager
        )

        # 状态
        self.state = ReviewAgentState()

    async def review(self, match_id: str) -> ReviewReport:
        """执行赛后复盘分析"""

        # Phase 0: 数据获取
        match_data = await self._fetch_match_data(match_id)
        if not match_data:
            raise ReviewError(f"无法获取比赛数据: {match_id}")

        # Phase 1: 多阶段分析（Loop 模式）
        for phase in self.ANALYSIS_PHASES:
            phase_result = await self._run_phase(phase, match_data)
            self.state.add_phase_result(phase_result)

            # 检查是否被中断
            if self.state.is_interrupted:
                break

        # Phase 2: 验证停止检查
        verification = self.verifier.verify(self.state)
        if not verification.passed:
            # 验证未通过 → 补充分析
            for reason in verification.blocking_reasons:
                logger.warning(f"验证未通过: {reason}")
            # 可选择重新进入某些阶段补充分析

        # Phase 3: 生成报告
        report = self._generate_report(match_data)

        # Phase 4: 后台自我审查（异步，不阻塞）
        self.background_reviewer.spawn(match_data, report.to_markdown())

        return report

    async def _run_phase(self, phase: Dict,
                         match_data: Dict) -> PhaseResult:
        """运行单个分析阶段"""
        phase_name = phase["name"]
        phase_budget = ReviewIterationBudget(
            max_iterations=phase["max_iterations"]
        )

        messages = self.prompt_builder.build(
            match_data,
            self.state.get_completed_results()
        )

        while True:
            # 检查总预算
            total_decision = self.budget.consume()
            if total_decision != BudgetDecision.CONTINUE:
                break

            # 检查阶段预算
            phase_decision = phase_budget.consume()
            if phase_decision != BudgetDecision.CONTINUE:
                break

            # 检查上下文是否需要压缩
            current_tokens = self._estimate_tokens(messages)
            if self.compressor.should_compress(current_tokens):
                messages = self.compressor.compress(messages, current_tokens)

            # LLM 调用
            response = await self.llm_client.chat(messages)
            messages.append({"role": "assistant", "content": response})

            # 评估本轮分析质量
            quality = self._evaluate_phase_quality(response, match_data)

            if quality >= 0.75:
                # 质量达标，退还剩余配额
                phase_budget.refund()
                break

        return PhaseResult(
            phase=phase_name,
            analysis=messages[-1]["content"],
            iterations_used=phase_budget._used_iterations
        )
```

## 23.4 与当前项目架构的集成点

| 集成点 | 当前项目组件 | 集成方式 |
|-------|------------|---------|
| **LLM 调用** | `utils/llm_client.py` | 直接复用，无需修改 |
| **API 客户端** | `utils/api_client.py` | 新增 `get_player_matches()` 和 `get_match_details()` |
| **记忆系统** | `core/agent.py` 中的 `AgentMemory` | 后台审查结果保存到记忆 |
| **工具注册** | `core/tool_registry.py` | 注册复盘相关工具（获取比赛数据等） |
| **Skill 注册** | `skills/registry.py` | 注册 `PostMatchReviewSkill` |
| **会话管理** | `core/conversation_manager.py` | 复盘对话作为独立会话 |
| **前端展示** | `web/app.py` | 新增 `/api/review` 端点 |
| **Langfuse** | `utils/trace_context.py` | 复盘分析过程接入 trace |

## 23.5 新增文件清单

```
DotaHelperAgent/
├── core/
│   └── review/                          # 新增: 复盘 Agent 模块
│       ├── __init__.py
│       ├── agent.py                     # PostMatchReviewAgent 主类
│       ├── budget.py                    # ReviewIterationBudget
│       ├── verifier.py                  # ReviewStopVerifier
│       ├── compressor.py                # ReviewContextCompressor
│       ├── prompt_builder.py            # ReviewPromptBuilder
│       ├── background_review.py         # BackgroundReviewSpawner
│       ├── report.py                    # ReviewReport 数据模型
│       └── types.py                     # ReviewTerminalState 等枚举
├── tools/
│   └── review_tools.py                  # 新增: 复盘相关工具
│       ├── get_match_details            # 获取比赛详情
│       ├── get_player_matches           # 获取玩家比赛历史
│       └── export_review_markdown       # 导出复盘报告
├── skills/
│   └── post_match_review/               # 新增: 复盘 Skill
│       ├── __init__.py
│       └── skill.py                     # PostMatchReviewSkill
└── config/
    └── review_config.yaml               # 新增: 复盘配置
```

## 23.6 实施路线图

```
第 1 步: 数据层（基础）
├─ api_client.py 新增 get_player_matches() / get_match_details()
├─ 定义 ReviewReport / PhaseResult 数据模型
└─ 验证 OpenDota API 数据完整性

第 2 步: 核心控制（骨架）
├─ 实现 ReviewIterationBudget（迭代预算）
├─ 实现 ReviewStopVerifier（验证停止）
├─ 实现 ReviewPromptBuilder（提示词构建）
└─ 单元测试

第 3 步: 主 Agent（集成）
├─ 实现 PostMatchReviewAgent 主循环
├─ 集成到 AgentController 或作为独立入口
├─ 注册工具和 Skill
└─ 集成测试

第 4 步: 增强功能（优化）
├─ 实现 ReviewContextCompressor（上下文压缩）
├─ 实现 BackgroundReviewSpawner（后台审查）
├─ 实现 Markdown 导出
└─ 前端适配

第 5 步: 轨迹与记忆（长期）
├─ 实现复盘轨迹持久化
├─ 后台审查结果写入记忆
└─ 分析模式自动沉淀
```
