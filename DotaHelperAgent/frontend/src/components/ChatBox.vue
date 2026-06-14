<template>
  <div class="chat-box">
    <div class="messages" ref="messagesContainer">
      <div
        v-for="msg in chatStore.messages"
        :key="msg.id"
        class="message"
        :class="msg.role"
      >
        <!-- 用户消息 -->
        <template v-if="msg.role === 'user'">
          <div class="user-bubble">
            <div class="bubble-content">{{ msg.content }}</div>
            <span class="bubble-time">{{ formatTime(msg.timestamp) }}</span>
          </div>
        </template>

        <!-- 助手消息 -->
        <template v-else>
          <div class="assistant-bubble">
            <div class="assistant-avatar">D</div>
            <div class="assistant-content">
              <!-- 思考步骤（折叠） -->
              <ThinkingSteps
                v-if="msg.thinkingSteps && msg.thinkingSteps.length > 0"
                :steps="msg.thinkingSteps"
                :collapsed="true"
              />
              <!-- Markdown 回答 -->
              <div v-if="msg.answerContent" class="answer-content">
                <MarkdownRenderer :content="msg.answerContent" />
              </div>
              <!-- 向后兼容：无 answerContent 时显示 content -->
              <div v-else-if="msg.content && !msg.thinkingSteps?.length" class="answer-content">
                <MarkdownRenderer :content="msg.content" />
              </div>
              <!-- 思考中占位 -->
              <div v-else-if="chatStore.isStreaming && !msg.content && !msg.answerContent" class="thinking-placeholder">
                <span class="typing-dots">
                  <span class="dot"></span>
                  <span class="dot"></span>
                  <span class="dot"></span>
                </span>
                <span class="thinking-text">思考中...</span>
              </div>
              <!-- 消息操作按钮 -->
              <MessageActions
                v-if="msg.content || msg.answerContent"
                :message-id="msg.id"
                :role="msg.role"
                @copy="handleCopy"
                @regenerate="handleRegenerate"
                @feedback="handleFeedback"
              />
            </div>
          </div>
        </template>
      </div>
    </div>

    <div class="input-area">
      <input
        v-model="inputText"
        type="text"
        class="dota-input chat-input"
        placeholder="输入消息，如：对面有帕吉和斧王，推荐什么英雄"
        :disabled="chatStore.isStreaming"
        @keyup.enter="sendMessage"
      />
      <button
        class="dota-btn send-btn"
        @click="sendMessage()"
        :disabled="!inputText.trim() || chatStore.isStreaming"
      >
        {{ chatStore.isStreaming ? '发送中...' : '发送' }}
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, nextTick, watch } from 'vue'
import { useChatStore } from '@/stores/chat'
import { useChatStream } from '@/composables/useChatStream'
import ThinkingSteps from './ThinkingSteps.vue'
import MarkdownRenderer from './MarkdownRenderer.vue'
import MessageActions from './MessageActions.vue'

const chatStore = useChatStore()
const { connect } = useChatStream()

const inputText = ref('')
const messagesContainer = ref<HTMLElement | null>(null)

const formatTime = (timestamp: Date) => {
  return new Date(timestamp).toLocaleTimeString('zh-CN', {
    hour: '2-digit',
    minute: '2-digit'
  })
}

const scrollToBottom = () => {
  nextTick(() => {
    if (messagesContainer.value) {
      messagesContainer.value.scrollTop = messagesContainer.value.scrollHeight
    }
  })
}

watch(
  () => chatStore.messages.length,
  () => scrollToBottom()
)

watch(
  () => chatStore.lastMessage?.content,
  () => scrollToBottom()
)

watch(
  () => chatStore.lastMessage?.answerContent,
  () => scrollToBottom()
)

const sendMessage = async (externalQuery?: string | KeyboardEvent) => {
  const query = typeof externalQuery === 'string'
    ? externalQuery
    : inputText.value.trim()

  if (!query || chatStore.isStreaming) {
    return
  }

  if (typeof externalQuery !== 'string') {
    inputText.value = ''
  }

  chatStore.addMessage({
    id: Date.now().toString(),
    role: 'user',
    content: query,
    thinkingSteps: [],
    answerContent: '',
    timestamp: new Date()
  })

  chatStore.addMessage({
    id: (Date.now() + 1).toString(),
    role: 'assistant',
    content: '',
    thinkingSteps: [],
    answerContent: '',
    timestamp: new Date()
  })

  await connect(query)
}

const handleCopy = async (messageId: string) => {
  const msg = chatStore.messages.find(m => m.id === messageId)
  if (msg) {
    const text = msg.answerContent || msg.content
    try {
      await navigator.clipboard.writeText(text)
    } catch {
      const ta = document.createElement('textarea')
      ta.value = text
      document.body.appendChild(ta)
      ta.select()
      document.execCommand('copy')
      document.body.removeChild(ta)
    }
  }
}

const handleRegenerate = (messageId: string) => {
  // 找到该助手消息前一条用户消息
  const idx = chatStore.messages.findIndex(m => m.id === messageId)
  if (idx > 0) {
    const userMsg = chatStore.messages[idx - 1]
    if (userMsg.role === 'user') {
      // 删除当前助手消息
      chatStore.messages.splice(idx, 1)
      // 重新发送
      sendMessage(userMsg.content)
    }
  }
}

const handleFeedback = (messageId: string, score: 'up' | 'down') => {
  console.log(`Feedback for ${messageId}: ${score}`)
  // TODO: 接入 Langfuse 评分 API
}

defineExpose({
  sendMessage
})
</script>

<style scoped>
.chat-box {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: var(--bg-deepest);
}

.messages {
  flex: 1;
  overflow-y: auto;
  padding: var(--gap-xl) var(--gap-2xl);
  display: flex;
  flex-direction: column;
  gap: var(--gap-xl);
}

/* 用户消息 */
.user-bubble {
  align-self: flex-end;
  max-width: 70%;
  background: var(--dota-red);
  color: white;
  padding: 10px 16px;
  border-radius: var(--radius-bubble) var(--radius-bubble) var(--radius-bubble-tail) var(--radius-bubble);
  animation: fadeIn 0.3s ease;
}

.bubble-content {
  font-size: 14px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
}

.bubble-time {
  display: block;
  text-align: right;
  font-size: 11px;
  opacity: 0.7;
  margin-top: 4px;
}

/* 助手消息 */
.assistant-bubble {
  display: flex;
  gap: var(--gap-md);
  max-width: 85%;
  align-self: flex-start;
  animation: fadeIn 0.3s ease;
}

.assistant-avatar {
  width: 32px;
  height: 32px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, var(--dota-red), var(--dota-red-dark));
  border-radius: var(--radius-lg);
  font-weight: 700;
  font-size: 14px;
  color: white;
  flex-shrink: 0;
}

.assistant-content {
  flex: 1;
  min-width: 0;
}

.answer-content {
  background: var(--bg-bubble);
  border: 1px solid var(--border-primary);
  border-radius: var(--radius-bubble) var(--radius-bubble) var(--radius-bubble) var(--radius-bubble-tail);
  padding: 12px 16px;
}

/* 思考中占位 */
.thinking-placeholder {
  display: flex;
  align-items: center;
  gap: var(--gap-sm);
  padding: 12px 16px;
  background: var(--bg-bubble);
  border: 1px solid var(--border-primary);
  border-radius: var(--radius-lg);
}

.typing-dots {
  display: flex;
  gap: 3px;
}

.dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--dota-gold);
  animation: typing 1.4s infinite;
}

.dot:nth-child(2) {
  animation-delay: 0.2s;
}

.dot:nth-child(3) {
  animation-delay: 0.4s;
}

.thinking-text {
  font-size: 13px;
  color: var(--text-tertiary);
}

/* 输入区域 */
.input-area {
  display: flex;
  gap: var(--gap-md);
  padding: var(--gap-xl) var(--gap-2xl);
  border-top: 1px solid var(--border-primary);
  background: var(--bg-deepest);
}

.chat-input {
  flex: 1;
  border-radius: var(--radius-xl);
  padding: 12px 18px;
  font-size: 14px;
}

.send-btn {
  padding: 12px 24px;
  border-radius: var(--radius-xl);
  white-space: nowrap;
}

/* 移动端 */
@media (max-width: 767px) {
  .messages {
    padding: var(--gap-md);
  }

  .user-bubble {
    max-width: 85%;
  }

  .assistant-bubble {
    max-width: 95%;
  }

  .input-area {
    padding: var(--gap-md);
  }
}
</style>
