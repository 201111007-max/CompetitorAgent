import { defineStore } from 'pinia'
import type { Message, ThinkingStep, Conversation } from '@/types/chat'

function generateId(): string {
  return Date.now().toString(36) + Math.random().toString(36).slice(2, 8)
}

function extractTitle(messages: Message[]): string {
  const first = messages.find(m => m.role === 'user')
  if (first) {
    const text = first.content.trim()
    return text.length > 20 ? text.slice(0, 20) + '...' : text
  }
  return '新对话'
}

export const useChatStore = defineStore('chat', {
  state: () => ({
    messages: [] as Message[],
    isStreaming: false,
    sessionId: '',
    traceId: '',
    conversations: [] as Conversation[],
    currentConversationId: ''
  }),

  getters: {
    messageCount: (state) => state.messages.length,
    lastMessage: (state) => state.messages[state.messages.length - 1],
    sortedConversations: (state) =>
      [...state.conversations].sort((a, b) => b.updatedAt - a.updatedAt)
  },

  actions: {
    addMessage(message: Message) {
      this.messages.push(message)
      this._autoSaveCurrent()
    },

    appendToLastMessage(content: string) {
      const lastMsg = this.messages[this.messages.length - 1]
      if (lastMsg && lastMsg.role === 'assistant') {
        lastMsg.content += content
      }
    },

    addThinkingStep(messageId: string, step: ThinkingStep) {
      const msg = this.messages.find(m => m.id === messageId)
      if (msg && msg.role === 'assistant') {
        msg.thinkingSteps.push(step)
      }
    },

    updateThinkingStep(messageId: string, index: number, update: Partial<ThinkingStep>) {
      const msg = this.messages.find(m => m.id === messageId)
      if (msg && msg.role === 'assistant' && msg.thinkingSteps[index]) {
        Object.assign(msg.thinkingSteps[index], update)
      }
    },

    appendToAnswer(messageId: string, content: string) {
      const msg = this.messages.find(m => m.id === messageId)
      if (msg && msg.role === 'assistant') {
        msg.answerContent += content
      }
    },

    setStreaming(status: boolean) {
      this.isStreaming = status
    },

    setSessionId(sessionId: string) {
      this.sessionId = sessionId
    },

    setTraceId(traceId: string) {
      this.traceId = traceId
    },

    _autoSaveCurrent() {
      if (!this.currentConversationId || this.messages.length === 0) return
      const conv = this.conversations.find(c => c.id === this.currentConversationId)
      if (conv) {
        conv.messages = JSON.parse(JSON.stringify(this.messages))
        conv.title = extractTitle(conv.messages)
        conv.updatedAt = Date.now()
        conv.sessionId = this.sessionId
        conv.traceId = this.traceId
      }
    },

    saveCurrentConversation() {
      if (this.messages.length === 0) return

      if (this.currentConversationId) {
        this._autoSaveCurrent()
      } else {
        const conv: Conversation = {
          id: generateId(),
          title: extractTitle(this.messages),
          messages: JSON.parse(JSON.stringify(this.messages)),
          sessionId: this.sessionId,
          traceId: this.traceId,
          createdAt: Date.now(),
          updatedAt: Date.now()
        }
        this.conversations.push(conv)
        this.currentConversationId = conv.id
      }
    },

    newChat() {
      // 保存当前对话
      this.saveCurrentConversation()
      // 清空当前状态
      this.messages = []
      this.sessionId = ''
      this.traceId = ''
      this.currentConversationId = ''
    },

    selectConversation(id: string) {
      // 先保存当前对话
      this.saveCurrentConversation()

      const conv = this.conversations.find(c => c.id === id)
      if (conv) {
        this.currentConversationId = conv.id
        this.messages = JSON.parse(JSON.stringify(conv.messages))
        this.sessionId = conv.sessionId
        this.traceId = conv.traceId
      }
    },

    deleteConversation(id: string) {
      const idx = this.conversations.findIndex(c => c.id === id)
      if (idx !== -1) {
        this.conversations.splice(idx, 1)
        if (this.currentConversationId === id) {
          this.messages = []
          this.sessionId = ''
          this.traceId = ''
          this.currentConversationId = ''
        }
      }
    },

    clearMessages() {
      this.messages = []
      this.traceId = ''
    }
  }
})
