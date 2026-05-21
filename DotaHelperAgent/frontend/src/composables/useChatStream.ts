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

  /**
   * 处理SSE事件流中的各种事件类型
   * 
   * 支持的事件类型：
   * - start: 会话开始，设置trace_id和session_id
   * - goal_decomposition*: 目标分解相关事件
   * - think: Agent思考过程（包含工具选择理由）
   * - plan: 执行计划（要执行的工具列表）
   * - action: 执行动作（正在执行的工具）
   * - observation: 观察结果（工具执行结果）
   * - answer: 中间答案
   * - synthesize: 最终综合答案
   * - complete/done: 流式输出完成
   * - error: 错误信息
   */
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

      case 'goal_decomposition':
      case 'goal_decomposition_result':
      case 'goal_execution':
      case 'sub_goal_start':
      case 'sub_goal_complete':
      case 'merge_results':
        if (data.status || data.main_goal) {
          const statusMsg = data.status || `目标: ${data.main_goal}`
          chatStore.appendToLastMessage(`\n📍 ${statusMsg}\n`)
        }
        break

      case 'think':
        if (data.content) {
          chatStore.appendToLastMessage(`\n💭 思考: ${data.content}\n`)
        }
        break

      case 'plan':
        if (data.actions) {
          const tools = data.actions.map((a: any) => a.tool).join(', ')
          chatStore.appendToLastMessage(`\n📋 计划执行: ${tools}\n`)
        }
        break

      case 'action':
        if (data.tool) {
          chatStore.appendToLastMessage(`\n🔧 执行工具: ${data.tool}\n`)
        }
        break

      case 'observation':
        if (data.result) {
          const resultPreview = typeof data.result === 'string' 
            ? data.result.substring(0, 150) 
            : JSON.stringify(data.result).substring(0, 150)
          chatStore.appendToLastMessage(`\n👀 观察结果: ${resultPreview}${resultPreview.length >= 150 ? '...' : ''}\n`)
        }
        break

      case 'answer':
        if (data.content) {
          chatStore.appendToLastMessage(data.content)
        }
        break

      case 'synthesize':
        if (data.answer) {
          chatStore.appendToLastMessage(data.answer)
        }
        break

      case 'complete':
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
