# 二十二、Claude Code 项目设计模式分析（赛后复盘 Agent 参考） — 详细设计

> 分析时间：2026-07-13
> 参考项目：`D:\trae_projects\claude-code-best_claude-code`
> 来源: ARCHITECTURE_ANALYSIS.md 第二十二章

本章分析 Claude Code 项目中可用于实现赛后复盘 Agent 的设计模式。

## 22.1 Stop Hooks 终止验证机制

**来源**: `src/query/stopHooks.ts` + `src/query/transitions.ts`

**核心设计**: 将"何时停止"和"何时继续"建模为互斥的联合类型：
- **Terminal 终态**（10 种）: `completed`, `blocking_limit`, `max_turns`, `stop_hook_prevented` 等
- **Continue 继续态**（7 种）: `next_turn`, `token_budget_continuation`, `stop_hook_blocking` 等

**可复用于赛后复盘**:

```python
# 定义复盘 Agent 的终止条件
class ReviewTerminalState(Enum):
    COMPLETED = "completed"           # 所有分析阶段完成
    MAX_TURNS = "max_turns"           # 达到最大迭代轮次
    CONFIDENCE_ADEQUATE = "confidence_adequate"  # 置信度足够
    BUDGET_EXHAUSTED = "budget_exhausted"  # Token 预算耗尽

class ReviewContinueState(Enum):
    NEXT_PHASE = "next_phase"         # 进入下一阶段分析
    LOW_CONFIDENCE = "low_confidence" # 置信度不足，需要补充分析
    TOKEN_BUDGET_OK = "token_budget_ok"  # Token 预算未耗尽，继续分析
```

## 22.2 Token 预算控制（智能终止）

**来源**: `src/query/tokenBudget.ts`

**核心设计**:
- `COMPLETION_THRESHOLD = 0.9` — 90% 预算时视为接近完成
- `DIMINISHING_THRESHOLD = 500` — 连续两次增量 < 500 token 时判定为边际收益递减
- 至少继续 3 次后才检测递减

**可复用于赛后复盘**:

```python
class TokenBudgetTracker:
    """Token 预算追踪器"""

    COMPLETION_THRESHOLD = 0.9
    DIMINISHING_THRESHOLD = 500
    MIN_CONTINUATIONS = 3

    def __init__(self, budget: int):
        self.budget = budget
        self.continuation_count = 0
        self.last_delta_tokens = 0
        self.used_tokens = 0

    def check_budget(self, current_tokens: int) -> BudgetDecision:
        """检查是否应该继续"""
        # 1. 接近预算上限
        if current_tokens >= self.budget * self.COMPLETION_THRESHOLD:
            return BudgetDecision.STOP

        # 2. 边际收益递减检测
        delta = current_tokens - self.used_tokens
        if (self.continuation_count >= self.MIN_CONTINUATIONS and
            delta < self.DIMINISHING_THRESHOLD and
            self.last_delta_tokens < self.DIMINISHING_THRESHOLD):
            return BudgetDecision.STOP_DIMINISHING

        # 3. 继续执行
        self.continuation_count += 1
        self.last_delta_tokens = delta
        self.used_tokens = current_tokens
        return BudgetDecision.CONTINUE
```

## 22.3 Dream/Recap 记忆整合模式

**来源**: `src/skills/bundled/dream.ts`

**核心设计**:
1. 读取所有会话记录（transcript）
2. 使用 `buildConsolidationPrompt()` 构建反思提示
3. 模型 review、组织、修剪记忆条目
4. 生成持久化、结构化的记忆

**可复用于赛后复盘**:

```python
def build_review_prompt(match_data: Dict) -> str:
    """构建复盘提示词"""
    return f"""
# 赛后复盘分析

## 比赛基本信息
- 比赛 ID: {match_data['match_id']}
- 时长: {match_data['duration']} 秒
- 结果: {'胜利' if match_data['radiant_win'] else '失败'}

## 对线期数据（0-10分钟）
{format_laning_data(match_data)}

## 团战数据
{format_teamfight_data(match_data)}

## 经济曲线
{format_economy_data(match_data)}

## 请分析：
1. 对线期的关键决策点
2. 团战的执行质量
3. 经济效率评估
4. 改进建议

输出格式：Markdown 结构化报告
"""
```

## 22.4 Batch 并行子代理模式

**来源**: `src/skills/bundled/batch.ts`

**核心设计**:
- **Phase 1**: 研究和规划（分解任务）
- **Phase 2**: 并行执行（每个工作单元独立子代理）
- **Phase 3**: 追踪进度（状态表实时更新）
- **最终汇总**

**可复用于赛后复盘**:

```python
class ParallelReviewExecutor:
    """并行复盘分析执行器"""

    def __init__(self, agent_pool: List[Agent]):
        self.agent_pool = agent_pool

    async def execute_parallel_review(self, match_data: Dict) -> ReviewReport:
        """并行执行复盘分析"""

        # Phase 1: 任务分解
        tasks = [
            ReviewTask("laning_analysis", self._analyze_laning, match_data),
            ReviewTask("teamfight_analysis", self._analyze_teamfights, match_data),
            ReviewTask("economy_analysis", self._analyze_economy, match_data),
            ReviewTask("decision_analysis", self._analyze_decisions, match_data),
        ]

        # Phase 2: 并行执行
        results = await asyncio.gather(*[
            self._execute_task(task) for task in tasks
        ])

        # Phase 3: 聚合结果
        return self._aggregate_results(results)
```

## 22.5 QueryEngine 生命周期管理

**来源**: `src/QueryEngine.ts`

**核心设计**:
- `submitMessage()` 管理完整查询生命周期（9 个阶段）
- 支持中断（`interrupt()`）和恢复（`resetAbortController()`）
- 部分结果提取（即使被中断也能保留已有分析）

**可复用于赛后复盘**:

```python
class ReviewAgentLifecycle:
    """复盘 Agent 生命周期管理"""

    def __init__(self):
        self.abort_controller = AbortController()
        self.progress_tracker = ProgressTracker()
        self.partial_results = []

    async def submit_review(self, match_id: str) -> ReviewResult:
        """提交复盘分析"""

        # 阶段 1: 初始化
        self._initialize(match_id)

        # 阶段 2: 获取比赛数据
        match_data = await self._fetch_match_data(match_id)

        # 阶段 3: 多阶段分析（支持中断）
        try:
            for phase in self._get_analysis_phases():
                if self.abort_controller.is_aborted():
                    break
                result = await self._execute_phase(phase, match_data)
                self.partial_results.append(result)
                self.progress_tracker.update(phase, result)
        except Exception as e:
            # 阶段 4: 部分结果提取
            return self._extract_partial_result()

        # 阶段 5: 生成最终报告
        return self._generate_final_report()

    def interrupt(self):
        """中断分析"""
        self.abort_controller.abort()

    def get_partial_result(self) -> PartialReviewReport:
        """获取部分结果"""
        return self._extract_partial_result()
```

## 22.6 条件激活的技能系统

**来源**: `src/skills/loadSkillsDir.ts`

**核心设计**:
- 技能支持 `paths` 条件激活（当文件路径匹配时才激活）
- 支持 frontmatter 配置（模型、权限、隔离模式、最大轮次等）

**可复用于赛后复盘**:

```yaml
# skills/post_match_review/SKILL.md
---
name: post_match_review
description: 赛后复盘分析
when_to_use: 当用户提供比赛 ID 并要求复盘时
allowed-tools:
  - get_match_details
  - get_player_matches
  - analyze_laning
  - analyze_teamfight
  - analyze_economy
model: opus  # 复盘需要强推理能力
maxTurns: 10  # 限制最大分析轮次
effort: high  # 高努力程度
---

# 赛后复盘 Skill

## 输入
- match_id: 比赛 ID

## 执行步骤
1. 获取比赛详情
2. 分析对线期（0-10分钟）
3. 分析团战执行
4. 分析经济效率
5. 分析关键决策点
6. 生成结构化报告

## 输出
- Markdown 格式的复盘报告
```

## 22.7 统一任务队列（结果回注）

**来源**: 后台子代理通过 `<task-notification>` 回注结果

**核心设计**:
- 后台子代理完成后，通过统一队列回注结果
- 主循环在空闲时消费队列消息
- 支持同步和异步两种模式

**可复用于赛后复盘**:

```python
class ReviewResultAggregator:
    """复盘结果聚合器"""

    def __init__(self):
        self.task_queue = asyncio.Queue()
        self.completed_tasks = {}

    async def submit_task(self, task: ReviewTask):
        """提交分析任务"""
        await self.task_queue.put(task)

    async def process_results(self):
        """处理结果"""
        while not self.task_queue.empty():
            task = await self.task_queue.get()
            result = await task.execute()
            self.completed_tasks[task.name] = result

            # 回注结果到主循环
            await self._notify_result(task.name, result)

    async def _notify_result(self, task_name: str, result: Any):
        """通知结果"""
        notification = {
            "type": "task-notification",
            "task-id": task_name,
            "status": "completed",
            "result": result
        }
        # 发送到统一队列
        await self.main_queue.put(notification)
```

## 22.8 总结：推荐实施方案

| 设计模式 | 来源文件 | 复盘 Agent 应用 | 优先级 |
|---------|---------|----------------|--------|
| **Stop Hooks** | `stopHooks.ts` | 定义复盘终止条件（分析完成/置信度足够/预算耗尽） | P0 |
| **Token 预算控制** | `tokenBudget.ts` | 防止过度分析，检测边际收益递减 | P0 |
| **Dream 整合模式** | `dream.ts` | 构建复盘提示词，整合比赛数据为结构化报告 | P0 |
| **Batch 并行子代理** | `batch.ts` | 并行分析对线/团战/经济/决策点 | P1 |
| **QueryEngine 生命周期** | `QueryEngine.ts` | 支持中断恢复、部分结果提取 | P1 |
| **条件激活技能** | `loadSkillsDir.ts` | 复盘 Skill 配置（模型、工具、轮次限制） | P1 |
| **统一任务队列** | 子代理通知机制 | 聚合并行分析结果 | P2 |

## 22.9 实施路线图

```
第 1 周：基础架构
- 实现 Stop Hooks 终止验证
- 实现 Token 预算控制
- 实现 Dream 整合模式（复盘提示词构建）

第 2 周：核心功能
- 实现赛后复盘 Agent（单阶段）
- 集成 OpenDota API（比赛历史 + 比赛详情）
- 实现 Markdown 导出

第 3 周：并行优化
- 实现 Batch 并行子代理模式
- 实现统一任务队列
- 优化复盘分析性能

第 4 周：生命周期管理
- 实现 QueryEngine 生命周期管理
- 支持中断恢复
- 实现部分结果提取

第 5 周：技能系统
- 实现条件激活技能系统
- 配置复盘 Skill（模型、工具、轮次限制）
- 集成到现有 Skill 注册表
```
