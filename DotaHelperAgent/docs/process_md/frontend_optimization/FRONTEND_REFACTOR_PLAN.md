# 前端重构计划 - 基于后端接口的对话界面实现

## 一、前后端交互接口文档

### 1. 核心聊天接口

#### 1.1 流式聊天接口（主要使用）

**接口**: `POST /api/chat/stream`

**请求体**:
```json
{
  "query": "对面有帕吉和斧王，推荐什么英雄",
  "context": {
    "our_heroes": ["faceless_void"],
    "enemy_heroes": ["pudge", "axe"]
  },
  "session_id": "sess_xxx"
}
```

**响应格式**: SSE (Server-Sent Events)

**事件类型**:

| 事件名 | 数据结构 | 说明 |
|--------|----------|------|
| `start` | `{"trace_id": "xxx", "session_id": "xxx"}` | 会话开始 |
| `think` | `{"content": "思考内容"}` | 思考阶段 |
| `plan` | `{"content": "计划内容"}` | 制定计划 |
| `execute` | `{"content": "执行内容", "tool": "工具名"}` | 执行工具 |
| `observe` | `{"content": "观察结果"}` | 观察结果 |
| `goal_decomposition` | `{"status": "分解状态"}` | 目标分解 |
| `goal_decomposition_result` | `{"main_goal": "主目标", "sub_goals": []}` | 分解结果 |
| `answer` | `{"content": "最终答案"}` | 最终答案 |
| `log` | `{"level": "INFO", "message": "日志消息"}` | 日志事件 |
| `done` | `{}` | 流结束 |
| `error` | `{"message": "错误信息"}` | 错误事件 |

#### 1.2 普通聊天接口（备用）

**接口**: `POST /api/chat`

**请求体**: 同上

**响应体**:
```json
{
  "answer": "推荐答案",
  "thinking_steps": [],
  "trace_id": "xxx",
  "session_id": "xxx"
}
```

### 2. 英雄推荐接口

**接口**: `POST /api/generate_hero_query`

**响应体**:
```json
{
  "success": true,
  "query": "我方英雄有虚空假面，敌方英雄有斧王，推荐我选什么英雄",
  "our_heroes": ["虚空假面"],
  "enemy_heroes": ["斧王"]
}
```

### 3. 日志接口

**接口**: `GET /api/logs?session_id=xxx`

**响应体**:
```json
{
  "success": true,
  "logs": [
    {
      "timestamp": "2024-01-01T12:00:00",
      "level": "INFO",
      "message": "日志消息",
      "component": "组件名"
    }
  ]
}
```

### 4. 健康检查接口

**接口**: `GET /api/health`

**响应体**:
```json
{
  "status": "healthy",
  "llm_enabled": true,
  "controller_ready": true
}
```

### 5. 请求头规范

所有请求自动携带：
- `X-Trace-ID`: 追踪 ID（用于链路追踪）
- `X-Session-ID`: 会话 ID（用于会话管理）

---

## 二、重构步骤分析

### 阶段一：清理现有实现

#### 1.1 需要删除的文件

```
frontend/src/
├── components/
│   ├── chat/
│   │   ├── ChatContainer.vue     # 删除
│   │   ├── ChatInput.vue         # 删除
│   │   ├── MessageItem.vue       # 删除
│   │   ├── MessageList.vue       # 删除
│   │   └── ThinkingSteps.vue     # 删除
│   ├── sidebar/
│   │   ├── HeroSidebar.vue       # 删除
│   │   ├── LogSidebar.vue        # 删除
│   │   └── LogEntry.vue          # 删除
│   └── HelloWorld.vue            # 删除
├── composables/
│   ├── useChat.ts                # 删除
│   └── useSSE.ts                 # 删除
├── stores/
│   ├── chat.ts                   # 删除
│   ├── hero.ts                   # 删除
│   └── log.ts                    # 删除
├── types/
│   ├── chat.ts                   # 删除
│   ├── hero.ts                   # 删除
│   └── log.ts                    # 删除
└── views/
    └── HomeView.vue              # 清空重写
```

#### 1.2 保留的文件

```
frontend/src/
├── services/
│   └── api.ts                    # 保留（Axios 配置）
├── router/
│   └── index.ts                  # 保留（路由配置）
├── App.vue                       # 保留
├── main.ts                       # 保留
└── style.css                     # 保留
```

---

### 阶段二：重新实现基础对话界面

#### 2.1 新的文件结构

```
frontend/src/
├── components/
│   └── ChatBox.vue               # 主对话组件
├── composables/
│   └── useChatStream.ts          # SSE 流式处理逻辑
├── stores/
│   └── chat.ts                   # 简化的聊天状态
├── types/
│   └── chat.ts                   # 简化的类型定义
└── views/
    └── HomeView.vue              # 简单的页面容器
```

#### 2.2 实现步骤

**Step 1: 定义类型 (types/chat.ts)**

```typescript
export interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  timestamp: Date
}

export interface ChatState {
  messages: Message[]
  isStreaming: boolean
  sessionId: string
  traceId: string
}
```

**Step 2: 创建状态管理 (stores/chat.ts)**

使用 Pinia 管理消息列表和流式状态。

**Step 3: 实现 SSE 处理 (composables/useChatStream.ts)**

核心逻辑：
1. 使用 `fetch` API 建立 SSE 连接
2. 解析 `event:` 和 `data:` 行
3. 根据事件类型更新状态
4. 处理 `answer` 事件时追加内容到消息

**Step 4: 创建 ChatBox 组件 (components/ChatBox.vue)**

功能：
1. 消息列表展示（用户消息 + AI 回复）
2. 输入框 + 发送按钮
3. 流式输出效果（逐字显示）
4. 状态指示（思考中/就绪）

**Step 5: 简化 HomeView (views/HomeView.vue)**

只保留一个简单的容器，引入 ChatBox 组件。

---

### 阶段三：核心代码实现要点

#### 3.1 SSE 流式处理核心代码

```typescript
async function connectStream(query: string) {
  const response = await fetch(`${baseURL}/api/chat/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query, session_id: sessionId })
  })

  const reader = response.body?.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let currentEvent = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break

    buffer += decoder.decode(value, { stream: true })
    const lines = buffer.split('\n')
    buffer = lines.pop() || ''

    for (const line of lines) {
      if (line.startsWith('event: ')) {
        currentEvent = line.slice(7).trim()
      } else if (line.startsWith('data: ')) {
        const data = JSON.parse(line.slice(6))
        handleEvent(currentEvent, data)
        currentEvent = ''
      }
    }
  }
}

function handleEvent(event: string, data: any) {
  switch (event) {
    case 'start':
      sessionId = data.session_id
      traceId = data.trace_id
      break
    case 'answer':
      appendToLastMessage(data.content)
      break
    case 'done':
      isStreaming = false
      break
  }
}
```

#### 3.2 消息列表渲染

```vue
<template>
  <div class="chat-box">
    <div class="messages">
      <div v-for="msg in messages" :key="msg.id" :class="msg.role">
        {{ msg.content }}
      </div>
    </div>
    <div class="input-area">
      <input v-model="inputText" @keyup.enter="sendMessage" />
      <button @click="sendMessage" :disabled="isStreaming">发送</button>
    </div>
  </div>
</template>
```

---

## 三、执行计划

### 步骤 1: 删除现有组件
- 删除 `components/chat/` 目录下所有文件
- 删除 `components/sidebar/` 目录下所有文件
- 删除 `composables/` 目录下所有文件
- 删除 `stores/` 目录下所有文件
- 删除 `types/` 目录下所有文件

### 步骤 2: 创建新的类型定义
- 创建 `types/chat.ts`，定义 Message 和 ChatState

### 步骤 3: 创建新的状态管理
- 创建 `stores/chat.ts`，实现简单的消息管理

### 步骤 4: 创建 SSE 处理逻辑
- 创建 `composables/useChatStream.ts`，实现流式连接

### 步骤 5: 创建 ChatBox 组件
- 创建 `components/ChatBox.vue`，实现基础对话界面

### 步骤 6: 重写 HomeView
- 清空 `views/HomeView.vue`，只保留 ChatBox 引用

### 步骤 7: 测试验证
- 启动前端开发服务器
- 启动后端服务
- 测试对话功能

---

## 四、预期效果

重构后的前端将具备：

1. **简洁的对话界面**
   - 消息列表展示
   - 输入框 + 发送按钮
   - 流式输出效果

2. **最小化依赖**
   - 只依赖 Naive UI 的基础组件
   - 简化的状态管理

3. **清晰的代码结构**
   - 单一职责的组件
   - 可复用的 composable

4. **易于扩展**
   - 后续可逐步添加思考步骤展示
   - 可添加日志侧边栏等功能
