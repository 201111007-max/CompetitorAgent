import { ref } from 'vue'
import { useChatStore } from '@/stores/chat'
import type { ChatRequest, SSEEvent } from '@/types/chat'

const baseURL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:5000'

export function useChatStream() {
  const chatStore = useChatStore()
  const error = ref<string | null>(null)

  const connect = async (query: string, context?: ChatRequest['context']) => {
    error.value = null
    chatStore.setStreaming(true)

    const request: ChatRequest = {
      query,
      context,
      session_id: chatStore.sessionId || undefined
    }

    try {
      const response = await fetch(`${baseURL}/api/chat/stream`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(request)
      })

      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`)
      }

      const reader = response.body?.getReader()
      const decoder = new TextDecoder()

      if (!reader) {
        throw new Error('Response body is null')
      }

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
            const data = line.slice(6)
            if (data.trim() && currentEvent) {
              try {
                const parsedData = JSON.parse(data)
                handleEvent(currentEvent, parsedData)
              } catch (e) {
                console.error('Failed to parse SSE data:', data)
              }
              currentEvent = ''
            }
          }
        }
      }
    } catch (e) {
      error.value = e instanceof Error ? e.message : 'Unknown error'
      console.error('SSE Error:', e)
    } finally {
      chatStore.setStreaming(false)
    }
  }

  const handleEvent = (eventType: string, data: any) => {
    switch (eventType) {
      case 'start':
        if (data.trace_id) {
          chatStore.setTraceId(data.trace_id)
        }
        if (data.session_id) {
          chatStore.setSessionId(data.session_id)
        }
        break

      case 'answer':
        if (data.content) {
          chatStore.appendToLastMessage(data.content)
        }
        break

      case 'done':
        chatStore.setStreaming(false)
        break

      case 'error':
        error.value = data.message || 'Unknown error'
        console.error('Stream error:', data.message)
        break

      default:
        break
    }
  }

  return {
    connect,
    error
  }
}
