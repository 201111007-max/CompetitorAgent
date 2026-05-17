<template>
  <div class="chat-box">
    <div class="header">
      <h1>DotaHelperAgent</h1>
      <p>Dota 2 智能助手</p>
    </div>

    <div class="messages" ref="messagesContainer">
      <div
        v-for="msg in chatStore.messages"
        :key="msg.id"
        class="message"
        :class="msg.role"
      >
        <div class="meta">
          <span class="role">{{ msg.role === 'user' ? '你' : '助手' }}</span>
          <span class="time">{{ formatTime(msg.timestamp) }}</span>
        </div>
        <div class="content">{{ msg.content }}</div>
      </div>
      <div v-if="chatStore.isStreaming && !hasAssistantMessage" class="message assistant thinking">
        <div class="content">思考中...</div>
      </div>
    </div>

    <div class="input-area">
      <input
        v-model="inputText"
        type="text"
        placeholder="输入消息，如：对面有帕吉和斧王，推荐什么英雄"
        :disabled="chatStore.isStreaming"
        @keyup.enter="sendMessage"
      />
      <button @click="sendMessage" :disabled="!inputText.trim() || chatStore.isStreaming">
        {{ chatStore.isStreaming ? '发送中...' : '发送' }}
      </button>
    </div>

    <div class="status-bar">
      <span :class="chatStore.isStreaming ? 'streaming' : 'ready'">
        {{ chatStore.isStreaming ? '正在思考...' : '就绪' }}
      </span>
      <span v-if="chatStore.traceId" class="trace-id" @click="copyTraceId" title="点击复制">
        Trace: {{ chatStore.traceId }}
        <span class="copy-hint">📋</span>
      </span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, nextTick, watch } from 'vue'
import { message } from '@/utils/message'
import { useChatStore } from '@/stores/chat'
import { useChatStream } from '@/composables/useChatStream'

const chatStore = useChatStore()
const { connect } = useChatStream()

const inputText = ref('')
const messagesContainer = ref<HTMLElement | null>(null)

const hasAssistantMessage = computed(() => {
  const lastMsg = chatStore.lastMessage
  return lastMsg && lastMsg.role === 'assistant' && lastMsg.content.length > 0
})

const formatTime = (timestamp: Date) => {
  return new Date(timestamp).toLocaleTimeString('zh-CN', {
    hour: '2-digit',
    minute: '2-digit'
  })
}

const copyTraceId = async () => {
  if (chatStore.traceId) {
    try {
      await navigator.clipboard.writeText(chatStore.traceId)
      message.success('Trace ID 已复制到剪贴板')
    } catch (e) {
      console.error('Copy failed:', e)
      message.error('复制失败')
    }
  }
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

const sendMessage = async (externalQuery?: string) => {
  const query = externalQuery || inputText.value.trim()
  
  if (!query || chatStore.isStreaming) {
    return
  }

  if (!externalQuery) {
    inputText.value = ''
  }

  chatStore.addMessage({
    id: Date.now().toString(),
    role: 'user',
    content: query,
    timestamp: new Date()
  })

  chatStore.addMessage({
    id: (Date.now() + 1).toString(),
    role: 'assistant',
    content: '',
    timestamp: new Date()
  })

  await connect(query)
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
  max-width: 800px;
  margin: 0 auto;
  background: rgba(0, 0, 0, 0.3);
  border-radius: 16px;
  overflow: hidden;
}

.header {
  background: linear-gradient(90deg, #e94560 0%, #ff6b6b 100%);
  padding: 16px 20px;
  text-align: center;
}

.header h1 {
  font-size: 20px;
  font-weight: 600;
  color: white;
  margin: 0;
}

.header p {
  color: rgba(255, 255, 255, 0.8);
  font-size: 12px;
  margin: 4px 0 0 0;
}

.messages {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.message {
  max-width: 80%;
  padding: 12px 16px;
  border-radius: 16px;
  line-height: 1.6;
}

.message.user {
  align-self: flex-end;
  background: linear-gradient(135deg, #e94560 0%, #ff6b6b 100%);
  color: white;
  border-bottom-right-radius: 4px;
}

.message.assistant {
  align-self: flex-start;
  background: rgba(255, 255, 255, 0.1);
  color: white;
  border-bottom-left-radius: 4px;
}

.message.thinking {
  opacity: 0.7;
}

.meta {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 6px;
  font-size: 11px;
  opacity: 0.7;
}

.role {
  font-weight: 500;
}

.time {
  margin-left: 8px;
}

.content {
  font-size: 14px;
  white-space: pre-wrap;
  word-break: break-word;
}

.input-area {
  display: flex;
  gap: 12px;
  padding: 16px;
  background: rgba(0, 0, 0, 0.2);
  border-top: 1px solid rgba(255, 255, 255, 0.1);
}

.input-area input {
  flex: 1;
  padding: 12px 16px;
  border: 1px solid rgba(255, 255, 255, 0.2);
  border-radius: 24px;
  background: rgba(255, 255, 255, 0.1);
  color: white;
  font-size: 14px;
  outline: none;
  transition: border-color 0.2s;
}

.input-area input:focus {
  border-color: #e94560;
}

.input-area input::placeholder {
  color: rgba(255, 255, 255, 0.5);
}

.input-area button {
  padding: 12px 24px;
  background: linear-gradient(135deg, #e94560 0%, #ff6b6b 100%);
  color: white;
  border: none;
  border-radius: 24px;
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
  transition: opacity 0.2s;
}

.input-area button:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.status-bar {
  padding: 10px 16px;
  background: rgba(0, 0, 0, 0.2);
  font-size: 12px;
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.status-bar .streaming {
  color: #ffe66d;
}

.status-bar .ready {
  color: #4ade80;
}

.trace-id {
  font-size: 10px;
  color: rgba(255, 255, 255, 0.4);
  font-family: 'Courier New', monospace;
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 4px 8px;
  border-radius: 4px;
  transition: background 0.2s, color 0.2s;
}

.trace-id:hover {
  background: rgba(255, 255, 255, 0.1);
  color: rgba(255, 255, 255, 0.7);
}

.copy-hint {
  opacity: 0;
  transition: opacity 0.2s;
}

.trace-id:hover .copy-hint {
  opacity: 1;
}
</style>
