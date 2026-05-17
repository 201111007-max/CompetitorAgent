import { defineStore } from 'pinia'
import type { Message } from '@/types/chat'

export const useChatStore = defineStore('chat', {
  state: () => ({
    messages: [] as Message[],
    isStreaming: false,
    sessionId: '',
    traceId: ''
  }),

  getters: {
    messageCount: (state) => state.messages.length,
    lastMessage: (state) => state.messages[state.messages.length - 1]
  },

  actions: {
    addMessage(message: Message) {
      this.messages.push(message)
    },

    appendToLastMessage(content: string) {
      const lastMsg = this.messages[this.messages.length - 1]
      if (lastMsg && lastMsg.role === 'assistant') {
        lastMsg.content += content
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

    clearMessages() {
      this.messages = []
      this.traceId = ''
    }
  }
})
