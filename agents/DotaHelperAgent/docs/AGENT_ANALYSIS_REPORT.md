

---

## 八、Web 界面架构设计

### 8.1 设计目标

为 ReAct Agent 提供一个可视化交互界面，让用户能够：
- 直观地输入查询并获取推荐
- 实时观察 Agent 的推理过程
- 查看工具调用和执行结果
- 管理对话历史

### 8.2 系统架构

```
┌─────────────────────────────────────────────────────────────┐
│                        用户浏览器                            │
│  ┌───────────────────────────────────────────────────────┐  │
│  │                   前端界面 (Web UI)                    │  │
│  │  ┌─────────────┐  ┌─────────────┐  ┌───────────────┐ │  │
│  │  │  查询输入框  │  │  对话历史   │  │  推理过程展示  │ │  │
│  │  │  (Input)    │  │  (Chat)     │  │  (Reasoning)  │ │  │
│  │  └─────────────┘  └─────────────┘  └───────────────┘ │  │
│  │  ┌─────────────┐  ┌─────────────┐  ┌───────────────┐ │  │
│  │  │  推荐结果   │  │  工具调用   │  │  实时状态     │ │  │
│  │  │ (Results)   │  │  (Tools)    │  │  (Status)     │ │  │
│  │  └─────────────┘  └─────────────┘  └───────────────┘ │  │
│  └───────────────────────────────────────────────────────┘  │
│                         ↑↓ HTTP/WebSocket                   │
└─────────────────────────┬───────────────────────────────────┘
                          │
┌─────────────────────────┼───────────────────────────────────┐
│                         ↓                                   │
│  ┌───────────────────────────────────────────────────────┐  │
│  │              Backend API (Flask/FastAPI)               │  │
│  │  ┌─────────────┐  ┌─────────────┐  ┌───────────────┐ │  │
│  │  │ /api/chat   │  │ /api/stream │  │  /api/tools   │ │  │
│  │  │  普通对话   │  │  流式响应   │  │  工具列表     │ │  │
│  │  └─────────────┘  └─────────────┘  └───────────────┘ │  │
│  └───────────────────────────────────────────────────────┘  │
│                         ↓                                   │
│  ┌───────────────────────────────────────────────────────┐  │
│  │              ReAct Agent Core                          │  │
│  │  ┌─────────────┐  ┌─────────────┐  ┌───────────────┐ │  │
│  │  │   Think     │  │    Plan     │  │   Execute     │ │  │
│  │  │   理解意图   │  │   制定计划  │  │   执行工具    │ │  │
│  │  └─────────────┘  └─────────────┘  └───────────────┘ │  │
│  │  ┌─────────────┐  ┌─────────────┐                     │  │
│  │  │   Reflect   │  │  Synthesize │                     │  │
│  │  │   反思调整   │  │   综合输出  │                     │  │
│  │  └─────────────┘  └─────────────┘                     │  │
│  └───────────────────────────────────────────────────────┘  │
│                         ↓                                   │
│  ┌───────────────────────────────────────────────────────┐  │
│  │              Tool Registry & Memory                    │  │
│  │         (工具注册表 + 记忆系统)                         │  │
│  └───────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

### 8.3 API 接口设计

#### 8.3.1 核心接口

| 接口 | 方法 | 描述 | 请求体 | 响应 |
|------|------|------|--------|------|
| `/api/chat` | POST | 普通对话 | `{query: string, session_id?: string}` | 完整响应 |
| `/api/chat/stream` | POST | 流式对话（SSE） | `{query: string, session_id?: string}` | Server-Sent Events |
| `/api/sessions` | GET | 获取会话列表 | - | `[{id, title, created_at}]` |
| `/api/sessions/{id}` | GET | 获取会话历史 | - | `{messages: [], metadata: {}}` |
| `/api/tools` | GET | 获取可用工具列表 | - | `[{name, description, category}]` |
| `/api/health` | GET | 健康检查 | - | `{status: "ok"}` |

#### 8.3.2 请求/响应格式

**请求示例：**
```json
POST /api/chat
{
  "query": "推荐一个英雄来克制敌方阵容",
  "session_id": "sess_123456",
  "context": {
    "our_heroes": ["pudge"],
    "enemy_heroes": ["anti-mage", "invoker"]
  }
}
```

**响应示例：**
```json
{
  "success": true,
  "data": {
    "session_id": "sess_123456",
    "message_id": "msg_789",
    "query": "推荐一个英雄来克制敌方阵容",
    "reasoning": [
      "用户查询: 推荐一个英雄来克制敌方阵容",
      "这是一个英雄推荐请求，需要分析克制关系"
    ],
    "actions": [
      "调用 analyze_counter_picks: 分析克制关系，推荐英雄"
    ],
    "observations": [
      "analyze_counter_picks 执行成功, 获得 3 条推荐"
    ],
    "recommendations": {
      "analyze_counter_picks": {
        "recommendations": [
          {"hero": "Anti-Mage", "reason": "克制法师", "score": 0.85}
        ]
      }
    },
    "final_answer": "根据分析，推荐选择 Anti-Mage...",
    "tools_used": ["analyze_counter_picks"],
    "execution_time": 1.23,
    "turns": 1
  }
}
```

### 8.4 流式响应设计（SSE）

适合展示 ReAct 的实时思考过程：

```
event: start
data: {"timestamp": 1234567890}

event: think
data: {"step": "think", "content": "用户查询: 推荐一个英雄来克制敌方阵容"}

event: plan
data: {"step": "plan", "actions": [{"tool": "analyze_counter_picks", "purpose": "分析克制关系"}]}

event: action
data: {"step": "action", "tool": "analyze_counter_picks", "status": "started"}

event: observation
data: {"step": "observation", "tool": "analyze_counter_picks", "result": {...}}

event: reflect
data: {"step": "reflect", "is_complete": true}

event: synthesize
data: {"step": "synthesize", "final_answer": "..."}

event: complete
data: {"timestamp": 1234567895, "total_time": 5.0}
```

### 8.5 前端组件架构

```
src/
├── components/
│   ├── Chat/                    # 对话组件
│   │   ├── ChatContainer.tsx    # 对话容器
│   │   ├── ChatMessage.tsx      # 单条消息
│   │   ├── ChatInput.tsx        # 输入框
│   │   └── ChatHistory.tsx      # 历史记录
│   ├── Reasoning/               # 推理过程展示
│   │   ├── ReasoningChain.tsx   # 推理链
│   │   ├── ThinkStep.tsx        # 思考步骤
│   │   ├── ActionStep.tsx       # 行动步骤
│   │   └── ObservationStep.tsx  # 观察步骤
│   ├── Tools/                   # 工具相关
│   │   ├── ToolCard.tsx         # 工具卡片
│   │   ├── ToolList.tsx         # 工具列表
│   │   └── ToolExecution.tsx    # 工具执行状态
│   └── Common/                  # 通用组件
│       ├── Loading.tsx
│       ├── ErrorBoundary.tsx
│       └── MarkdownRenderer.tsx
├── hooks/
│   ├── useChat.ts               # 对话逻辑
│   ├── useStreaming.ts          # 流式响应
│   └── useAgent.ts              # Agent 交互
├── services/
│   └── api.ts                   # API 封装
├── types/
│   └── index.ts                 # TypeScript 类型
└── store/
    └── chatStore.ts             # 状态管理
```

### 8.6 状态管理设计

```typescript
// 核心状态
interface ChatState {
  // 会话
  currentSession: Session | null;
  sessions: Session[];
  
  // 消息
  messages: Message[];
  isLoading: boolean;
  error: Error | null;
  
  // ReAct 过程
  currentReasoning: ReasoningStep[] | null;
  currentActions: Action[] | null;
  currentObservations: Observation[] | null;
  
  // 流式响应
  isStreaming: boolean;
  streamBuffer: string;
}

// 消息类型
interface Message {
  id: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  reasoning?: ReasoningStep[];
  toolsUsed?: string[];
  timestamp: number;
}

// ReAct 步骤
type ReasoningStep = 
  | { type: 'think'; content: string }
  | { type: 'plan'; actions: Action[] }
  | { type: 'action'; tool: string; params: any }
  | { type: 'observation'; tool: string; result: any }
  | { type: 'reflect'; isComplete: boolean };
```

### 8.7 交互流程

```
用户输入查询
    ↓
前端发送 POST /api/chat/stream
    ↓
后端创建 ReAct Agent 实例
    ↓
开始 ReAct 循环：
    ├─→ Think: 发送 event: think
    ├─→ Plan: 发送 event: plan  
    ├─→ Execute: 发送 event: action
    ├─→ Observe: 发送 event: observation
    ├─→ Reflect: 发送 event: reflect
    └─→ Synthesize: 发送 event: synthesize
    ↓
发送 event: complete
    ↓
前端实时更新 UI，展示推理过程
```

### 8.8 技术选型建议

| 层面 | 选项 A (简单) | 选项 B (现代) | 选项 C (极简) |
|------|--------------|---------------|---------------|
| 前端框架 | Vanilla JS + HTML | React + TypeScript | Vue 3 |
| UI 组件 | 原生 CSS | Ant Design / Chakra UI | Element Plus |
| 状态管理 | 无 | Zustand / Redux | Pinia |
| 实时通信 | SSE (Server-Sent Events) | WebSocket | SSE |
| 构建工具 | 无 | Vite | Vite |
| 后端框架 | Flask | FastAPI | Flask |

### 8.9 最小可行方案（MVP）

如果希望快速验证，可以采用：

1. **后端**: Flask + SSE 流式响应
2. **前端**: 单个 HTML 文件 + Vanilla JS
3. **部署**: 本地运行，浏览器直接访问

这个方案可以在 1-2 小时内完成，验证交互流程后再考虑升级。

---

**文档版本**: 1.2  
**最后更新**: 2026-04-23
