# DotaHelperAgent 前端样式优化设计文档

> **版本**: v1.0  
> **日期**: 2026-06-14  
> **状态**: 待审核  
> **设计风格**: Dota 2 官方风格 + 现代融合

---

## 一、设计概述

### 1.1 目标

将 DotaHelperAgent 前端从当前的通用暗色主题，重新设计为 **Dota 2 官方风格 + 现代融合** 的视觉体验，同时保留所有现有功能（英雄查询、日志展示、流式聊天）。

### 1.2 设计决策

| 决策项 | 选择 | 说明 |
|--------|------|------|
| 视觉风格 | Dota 2 风格 + 现代融合 | 暗红+金色+深黑，适度圆角，流畅动画 |
| 布局结构 | 左侧面板 + 聊天主区 | 类似 ChatGPT 布局，可收起侧边栏 |
| 消息展示 | 折叠式思考过程 + Markdown 渲染 | 工具调用步骤默认折叠，最终回答 Markdown 渲染 |
| 消息操作 | 复制/重新生成/反馈评分 | 每条助手消息支持操作按钮 |
| 侧边栏 | 可收起 | 默认收起，点击汉堡按钮展开 |
| 英雄/日志面板 | 右侧抽屉 | 可同时打开，不互斥 |
| 英雄功能 | 保留 | 随机生成查询、我方/敌方标签、发送到聊天、历史记录 |
| 日志功能 | 保留 | 实时日志流、级别过滤、连接状态 |

---

## 二、配色系统

### 2.1 品牌色

| 色值 | 用途 | 示例 |
|------|------|------|
| `#BF2E1A` | 品牌主色/强调色 | 按钮、用户消息气泡、活跃状态 |
| `#c6a44e` | 装饰色/金色 | 标题、分割线、图标高亮、重要标签 |
| `#8b1a0e` | 主色暗色变体 | 渐变终点、hover 状态 |

### 2.2 背景层级

| 色值 | 层级 | 用途 |
|------|------|------|
| `#0d0d0d` | 最深层 | 页面背景、主区域底色 |
| `#0a0a0a` | 侧边栏底 | 收起状态侧边栏背景 |
| `#111111` | 面板背景 | 展开侧边栏、抽屉面板 |
| `#141414` | 卡片/区块 | 思考步骤折叠区、区块背景 |
| `#1a1a1a` | 输入/卡片 | 输入框、消息卡片 |
| `#1e1e1e` | 消息气泡 | 助手消息气泡 |

### 2.3 状态色

| 色值 | 用途 |
|------|------|
| `#4ade80` | 成功/就绪/我方英雄 |
| `#fbbf24` | 警告/思考中 |
| `#f87171` | 错误/敌方英雄 |
| `#60a5fa` | 信息/组件标签 |

### 2.4 文字色

| 色值 | 用途 |
|------|------|
| `#e0e0e0` | 主文字 |
| `#cccccc` | 次要文字 |
| `#888888` | 辅助文字/时间戳 |
| `#555555` | 禁用/占位符 |

### 2.5 边框色

| 色值 | 用途 |
|------|------|
| `#2a2a2a` | 主要边框/分割线 |
| `#333333` | 输入框/卡片边框 |

---

## 三、布局结构

### 3.1 整体布局

```
┌──────────────────────────────────────────────────────────┐
│ [侧边栏(可收起)]  │  [主聊天区域]  │  [右侧抽屉(可选)]  │
│                   │               │  英雄面板 / 日志面板 │
│  ☰ 汉堡菜单       │  顶部状态栏    │                     │
│  + 新建对话        │  消息列表      │                     │
│  💬 对话1         │  ...          │                     │
│  💬 对话2         │  输入区域      │                     │
│  ...              │               │                     │
│  ⚔ 英雄面板       │               │                     │
│  📋 日志面板       │               │                     │
└──────────────────────────────────────────────────────────┘
```

### 3.2 侧边栏

**收起状态** (52px 宽):
- ☰ 汉堡按钮（展开侧边栏）
- + 新建对话按钮
- 对话图标列表（仅图标，当前对话高亮）
- 底部：⚔ 英雄面板 / 📋 日志面板 快捷按钮

**展开状态** (260px 宽):
- ☰ 汉堡按钮（收起侧边栏）
- 搜索框
- + 新建对话按钮
- 对话列表（显示标题 + 时间，当前对话高亮左边框 #BF2E1A）
- 底部：⚔ 英雄面板 / 📋 日志面板 快捷按钮

**过渡动画**: `transition: width 0.3s ease`

### 3.3 主聊天区域

**顶部状态栏** (44px 高):
- 左侧：D 品牌图标 + "DOTA HELPER AGENT" 金色标题 + 连接状态指示灯
- 右侧：Trace ID（可点击复制，等宽字体）

**消息列表** (flex: 1):
- 用户消息：右对齐，#BF2E1A 背景，白色文字，圆角 12px 12px 4px 12px
- 助手消息：左对齐，含头像（D 品牌图标），消息卡片 + 折叠思考步骤

**输入区域**:
- 圆角输入框（10px），#1a1a1a 背景，#333 边框
- 发送按钮：#BF2E1A 背景，圆角 10px

### 3.4 右侧抽屉面板

**英雄面板** (360px 宽):
- 头部：⚔ 图标 + "英雄查询助手" + 关闭按钮
- 随机生成查询按钮（#BF2E1A 渐变背景 + 阴影）
- 查询结果卡片（查询文本 + 我方/敌方英雄标签 + 操作按钮）
- 历史记录列表

**日志面板** (400px 宽):
- 头部：📋 图标 + "实时日志" + 级别过滤下拉 + 清空按钮 + 关闭按钮
- 日志内容（等宽字体，级别颜色区分）
- 底部状态栏：连接状态 + 日志条数

**同时打开**: 英雄面板和日志面板可同时打开，水平排列在右侧

---

## 3.5 响应式适配

### 3.5.1 断点定义

| 断点 | 范围 | 侧边栏 | 面板布局 |
|------|------|--------|----------|
| 桌面端 | ≥1280px | 可收起（52px/260px） | 右侧水平并列 |
| 平板端 | 768px-1279px | 默认收起（52px） | 右侧垂直堆叠 |
| 移动端 | <768px | 隐藏 | 底部抽屉 + Tab 切换 |

### 3.5.2 桌面端 (≥1280px)

```
┌─────────────────────────────────────────────────────────────────────┐
│ [侧边栏] │  [主聊天区域]  │  [英雄面板 360px] │ [日志面板 400px] │
│  52/260px │               │                   │                  │
└─────────────────────────────────────────────────────────────────────┘
```

- 英雄和日志面板水平并列在右侧
- 侧边栏可收起/展开
- 主聊天区自适应剩余宽度

### 3.5.3 平板端 (768px-1279px)

```
┌──────────────────────────────────────────────┐
│ [侧边栏] │  [主聊天区域]  │  [英雄面板]     │
│  52px    │               │  [─────分割线──] │
│          │               │  [日志面板]      │
└──────────────────────────────────────────────┘
```

- 侧边栏默认收起（仅图标）
- 英雄和日志面板垂直堆叠，各占右侧全宽
- 面板间用分割线分隔，各自独立滚动
- 面板总宽度 = min(360px, 40vw)

### 3.5.4 移动端 (<768px)

```
┌────────────────────────┐
│  [主聊天区域 - 全宽]    │
│                        │
│  顶部状态栏（含 ☰ 和 ⚔📋）│
│  消息列表               │
│  输入区域               │
├────────────────────────┤
│  [底部抽屉 - 70%屏幕高] │
│  [英雄] [日志]  ← Tab  │
│  ─────────────────     │
│  面板内容               │
└────────────────────────┘
```

- 侧边栏完全隐藏，顶部状态栏增加 ☰ 按钮
- 面板改为底部抽屉，从底部滑出，占屏幕 70% 高度
- 英雄/日志用 Tab 切换，不可同时显示
- 抽屉可下拉关闭
- 顶部状态栏增加 ⚔ 和 📋 图标按钮，点击打开对应面板的底部抽屉

---

## 四、组件设计

### 4.1 新增组件

#### 4.1.1 `SidePanel.vue` — 可收起左侧面板

**Props**:
```typescript
interface SidePanelProps {
  collapsed: boolean        // 是否收起
}
```

**Emits**:
```typescript
interface SidePanelEmits {
  toggle: []               // 切换收起/展开
  newChat: []              // 新建对话
  selectChat: [id: string] // 选择对话
  openHeroPanel: []        // 打开英雄面板
  openLogPanel: []         // 打开日志面板
}
```

**功能**:
- 收起状态显示图标列表
- 展开状态显示搜索框 + 对话列表
- 当前对话高亮（左边框 #BF2E1A）
- 底部快捷按钮区域

#### 4.1.2 `ThinkingSteps.vue` — 折叠思考过程

**Props**:
```typescript
interface ThinkingStep {
  type: 'think' | 'plan' | 'action' | 'observation' | 'goal'
  content: string
  tool?: string
  result?: string
  status: 'running' | 'done' | 'error'
}

interface ThinkingStepsProps {
  steps: ThinkingStep[]
  collapsed: boolean       // 默认 true
  duration?: string        // 总耗时
}
```

**功能**:
- 默认折叠，显示步骤数量和耗时
- 点击展开显示详细步骤
- 每个步骤有状态图标（运行中/完成/错误）
- 工具名称高亮显示（#c6a44e）

#### 4.1.3 `MarkdownRenderer.vue` — Markdown 渲染

**Props**:
```typescript
interface MarkdownRendererProps {
  content: string          // Markdown 文本
}
```

**功能**:
- 支持标题（h1-h4，#c6a44e 颜色）
- 支持列表（有序/无序）
- 支持代码块（语法高亮，暗色背景）
- 支持行内代码（#BF2E1A 背景）
- 支持加粗/斜体
- 支持引用块（左边框 #BF2E1A）
- 支持表格
- 支持链接（#c6a44e 颜色）
- 支持提示框（💡 信息框，金色边框背景）

**依赖**: `marked` + `highlight.js`

#### 4.1.4 `MessageActions.vue` — 消息操作按钮

**Props**:
```typescript
interface MessageActionsProps {
  messageId: string
  role: 'user' | 'assistant'
}
```

**Emits**:
```typescript
interface MessageActionsEmits {
  copy: [messageId: string]
  regenerate: [messageId: string]
  feedback: [messageId: string, score: 'up' | 'down']
}
```

**功能**:
- 助手消息：复制、重新生成、👍、👎
- 用户消息：仅复制
- hover 时显示，平时半透明

#### 4.1.5 `RightDrawer.vue` — 右侧抽屉容器

**Props**:
```typescript
interface RightDrawerProps {
  showHero: boolean        // 显示英雄面板
  showLog: boolean         // 显示日志面板
}
```

**Emits**:
```typescript
interface RightDrawerEmits {
  closeHero: []
  closeLog: []
  sendQuery: [query: string]
}
```

**功能**:
- 支持同时显示英雄和日志面板
- 每个面板独立关闭
- 面板间有分割线
- 滑入/滑出动画

### 4.2 改造组件

#### 4.2.1 `ChatBox.vue` 改造

**当前问题**:
- 纯文本渲染，无 Markdown 支持
- 思考/计划/观察等中间步骤混在回复中
- 头部区域浪费空间
- 无消息操作按钮

**改造内容**:

1. **移除顶部 header** — 标题信息移到 HomeView 顶部状态栏
2. **消息渲染改造**:
   - 用户消息：保持气泡样式，改为 #BF2E1A 背景
   - 助手消息：拆分为 ThinkingSteps + MarkdownRenderer
3. **SSE 事件处理改造**:
   - `think`/`plan`/`action`/`observation` 等事件 → 存入 `thinkingSteps` 数组
   - `answer`/`synthesize` 事件 → 存入 `answerContent` 字符串
   - 消息结构从 `{ content }` 改为 `{ thinkingSteps, answerContent }`
4. **添加 MessageActions** — 每条助手消息下方
5. **添加助手头像** — D 品牌图标（渐变 #BF2E1A → #8b1a0e）

**新的消息数据结构**:
```typescript
interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string                    // 原始文本（兼容）
  thinkingSteps?: ThinkingStep[]     // 思考步骤
  answerContent?: string             // Markdown 回答内容
  timestamp: Date
}
```

#### 4.2.2 `HeroPanel.vue` 改造

**改造内容**:
1. **配色替换**: 渐变紫蓝 → #BF2E1A 渐变
2. **生成按钮**: 改为 Dota 2 风格（渐变 + 阴影 + ⚡ 图标）
3. **英雄标签**: 我方绿色 → 保留 #4ade80，敌方红色 → 保留 #f87171
4. **发送按钮**: 改为 #BF2E1A 背景
5. **历史记录**: 添加 "使用" 按钮高亮（#c6a44e）
6. **关闭按钮**: 移除独立关闭按钮，由 RightDrawer 统一管理

#### 4.2.3 `LogPanel.vue` 改造

**改造内容**:
1. **配色替换**: 背景改为 #111，边框改为 #2a2a2a
2. **级别过滤**: 改为 Dota 2 风格下拉框
3. **清空按钮**: 改为 #BF2E1A 背景
4. **日志条目**: 保持等宽字体，级别颜色保留
5. **关闭按钮**: 移除独立关闭按钮，由 RightDrawer 统一管理
6. **底部状态栏**: 改为 #0a0a0a 背景

#### 4.2.4 `HomeView.vue` 改造

**改造内容**:
1. **布局重构**: 从 `flex + 侧边栏` 改为 `SidePanel + 主区域 + RightDrawer`
2. **移除浮动按钮**: toggle-buttons 替换为侧边栏底部快捷按钮
3. **添加顶部状态栏**: 品牌标识 + 连接状态 + Trace ID
4. **状态管理**: 新增 `sidePanelCollapsed`、`showHeroPanel`、`showLogPanel` 状态

**新模板结构**:
```vue
<template>
  <div class="home-view">
    <SidePanel 
      :collapsed="sidePanelCollapsed"
      @toggle="sidePanelCollapsed = !sidePanelCollapsed"
      @newChat="handleNewChat"
      @selectChat="handleSelectChat"
      @openHeroPanel="showHeroPanel = !showHeroPanel"
      @openLogPanel="showLogPanel = !showLogPanel"
    />
    <div class="main-area">
      <TopStatusBar />
      <ChatBox ref="chatBoxRef" />
    </div>
    <RightDrawer
      :showHero="showHeroPanel"
      :showLog="showLogPanel"
      @closeHero="showHeroPanel = false"
      @closeLog="showLogPanel = false"
      @sendQuery="handleSendQuery"
    />
  </div>
</template>
```

#### 4.2.5 `App.vue` 改造

**改造内容**:
1. **背景色**: `linear-gradient(135deg, #1a1a2e, #16213e)` → `#0d0d0d`
2. **Naive UI 主题覆盖**: 配置 Dota 2 风格的主题变量

---

## 五、样式规范

### 5.1 圆角

| 元素 | 圆角 |
|------|------|
| 消息气泡 | 12px（收角 4px） |
| 卡片/区块 | 8px |
| 输入框 | 10px |
| 按钮 | 8px（大按钮）/ 6px（小按钮） |
| 标签 | 12px（胶囊形） |
| 头像 | 8px |
| 侧边栏图标 | 6px |

### 5.2 阴影

| 元素 | 阴影 |
|------|------|
| 品牌按钮 | `0 2px 8px rgba(191,46,26,0.3)` |
| 卡片 hover | `0 4px 12px rgba(0,0,0,0.3)` |
| 抽屉面板 | `-4px 0 16px rgba(0,0,0,0.3)` |

### 5.3 过渡动画

| 元素 | 过渡 |
|------|------|
| 侧边栏展开/收起 | `width 0.3s ease` |
| 抽屉面板滑入/滑出 | `transform 0.3s ease, opacity 0.3s ease` |
| 按钮 hover | `transform 0.2s, box-shadow 0.2s` |
| 消息出现 | `fadeIn 0.3s ease` |
| 思考步骤展开/折叠 | `max-height 0.3s ease` |

### 5.4 字体

| 用途 | 字体 |
|------|------|
| 正文 | `-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif` |
| 代码/日志 | `'Consolas', 'Monaco', 'Courier New', monospace` |
| 标题 | 正文字体 + `font-weight: 600` + `letter-spacing: 0.5px` |

### 5.5 间距

| 用途 | 间距 |
|------|------|
| 消息之间 | 16px |
| 卡片内边距 | 14-16px |
| 输入区域内边距 | 16px 20px |
| 侧边栏图标间距 | 8px |
| 标签间距 | 6px |

---

## 六、SSE 事件处理改造

### 6.1 当前问题

当前 `useChatStream.ts` 将所有事件（think、plan、action、observation、answer、synthesize）统一追加到 `content` 字段，导致：
- 思考步骤和最终回答混在一起
- 无法区分哪些是中间过程，哪些是最终结果
- 无法实现折叠展示

### 6.2 改造方案

**Message 类型扩展**:
```typescript
interface ThinkingStep {
  type: 'think' | 'plan' | 'action' | 'observation' | 'goal'
  content: string
  tool?: string
  result?: string
  status: 'running' | 'done' | 'error'
}

interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string                    // 原始文本（向后兼容）
  thinkingSteps: ThinkingStep[]      // 思考步骤
  answerContent: string              // Markdown 回答内容
  timestamp: Date
}
```

**事件路由**:
- `think` → `thinkingSteps.push({ type: 'think', content, status: 'done' })`
- `plan` → `thinkingSteps.push({ type: 'plan', content: tools, status: 'done' })`
- `action` → `thinkingSteps.push({ type: 'action', tool, status: 'running' })`
- `observation` → 更新最后一个 action 步骤为 `status: 'done'`，追加 result
- `goal_decomposition*` → `thinkingSteps.push({ type: 'goal', content, status: 'done' })`
- `answer` → `answerContent += data.content`
- `synthesize` → `answerContent += data.answer`
- `complete`/`done` → 标记所有 running 步骤为 done，设置 streaming = false

**chatStore 改造**:
```typescript
// 新增 actions
addThinkingStep(messageId: string, step: ThinkingStep) { ... }
updateThinkingStep(messageId: string, index: number, update: Partial<ThinkingStep>) { ... }
appendToAnswer(messageId: string, content: string) { ... }
```

---

## 七、文件变更清单

### 7.1 新增文件

| 文件路径 | 说明 |
|----------|------|
| `src/components/SidePanel.vue` | 可收起左侧面板 |
| `src/components/ThinkingSteps.vue` | 折叠思考过程 |
| `src/components/MarkdownRenderer.vue` | Markdown 渲染器 |
| `src/components/MessageActions.vue` | 消息操作按钮 |
| `src/components/RightDrawer.vue` | 右侧抽屉容器 |
| `src/components/TopStatusBar.vue` | 顶部状态栏 |
| `src/styles/dota-theme.css` | Dota 2 主题 CSS 变量和全局样式 |

### 7.2 修改文件

| 文件路径 | 改动范围 | 说明 |
|----------|----------|------|
| `src/App.vue` | 样式 | 背景色改为 #0d0d0d，配置 Naive UI 主题 |
| `src/views/HomeView.vue` | 模板+脚本+样式 | 布局重构，集成新组件 |
| `src/components/ChatBox.vue` | 模板+脚本+样式 | 消息渲染改造，集成 ThinkingSteps/MarkdownRenderer/MessageActions |
| `src/components/HeroPanel.vue` | 样式 | Dota 2 配色替换，移除独立关闭按钮 |
| `src/components/LogPanel.vue` | 样式 | Dota 2 配色替换，移除独立关闭按钮 |
| `src/stores/chat.ts` | 逻辑 | 扩展 Message 类型，新增 thinkingSteps/answerContent 管理 |
| `src/types/chat.ts` | 类型 | 扩展 Message 接口，新增 ThinkingStep 类型 |
| `src/composables/useChatStream.ts` | 逻辑 | 事件路由改造，分离思考步骤和回答内容 |
| `src/styles/main.css` | 样式 | Dota 2 主题滚动条、动画 |

### 7.3 新增依赖

| 包名 | 用途 |
|------|------|
| `marked` | Markdown 解析 |
| `highlight.js` | 代码语法高亮 |

---

## 八、实施顺序

### Phase 1: 基础设施 (无功能变化)
1. 创建 `dota-theme.css`，定义 CSS 变量和全局样式
2. 修改 `App.vue` 和 `main.css`，应用新背景色和滚动条
3. 安装 `marked` + `highlight.js`

### Phase 2: 数据层改造 (无 UI 变化)
4. 扩展 `types/chat.ts`，新增 ThinkingStep 类型
5. 改造 `stores/chat.ts`，新增 thinkingSteps/answerContent 管理
6. 改造 `useChatStream.ts`，实现事件路由分离

### Phase 3: 新组件开发
7. 开发 `MarkdownRenderer.vue`
8. 开发 `ThinkingSteps.vue`
9. 开发 `MessageActions.vue`
10. 开发 `TopStatusBar.vue`
11. 开发 `SidePanel.vue`
12. 开发 `RightDrawer.vue`

### Phase 4: 组件改造
13. 改造 `ChatBox.vue` — 集成新消息渲染
14. 改造 `HeroPanel.vue` — Dota 2 配色
15. 改造 `LogPanel.vue` — Dota 2 配色

### Phase 5: 布局集成
16. 重构 `HomeView.vue` — 新布局结构
17. 整体联调测试

---

## 九、风险和注意事项

1. **向后兼容**: Message.content 字段保留，确保旧数据不丢失。thinkingSteps 和 answerContent 为可选字段
2. **SSE 事件兼容**: 事件路由改造需确保所有现有事件类型正确处理，未知事件类型忽略
3. **性能**: MarkdownRenderer 对长文本的渲染性能，考虑虚拟滚动
4. **移动端适配**: 已设计三断点响应式方案（桌面水平并列/平板垂直堆叠/移动底部抽屉），移动端面板用 Tab 切换不可同时显示
5. **Naive UI 主题**: 需确认 Naive UI 组件（如 NSelect）的主题覆盖方式
