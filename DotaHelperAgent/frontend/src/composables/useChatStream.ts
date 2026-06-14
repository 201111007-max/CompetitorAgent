import { ref } from 'vue'
import { useChatStore } from '@/stores/chat'
import type { ChatRequest } from '@/types/chat'

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

    // 获取当前助手消息 ID，用于后续事件路由
    const assistantMsgId = chatStore.lastMessage?.id || ''

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
                handleEvent(currentEvent, parsedData, assistantMsgId)
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
   * 事件路由策略：
   * - think/plan/action/observation/goal → thinkingSteps（折叠展示）
   * - answer/synthesize → answerContent（Markdown 渲染）
   * - start → 设置 trace_id 和 session_id
   * - complete/done → 结束流式
   * - error → 错误处理
   */
  const handleEvent = (eventType: string, data: any, msgId: string) => {
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
      case 'merge_results': {
        const statusMsg = data.status || `目标: ${data.main_goal || ''}`
        chatStore.addThinkingStep(msgId, {
          type: 'goal',
          content: statusMsg,
          status: 'done'
        })
        // 向后兼容：同时追加到 content
        chatStore.appendToLastMessage(`\n📍 ${statusMsg}\n`)
        break
      }

      case 'think':
        if (data.content) {
          chatStore.addThinkingStep(msgId, {
            type: 'think',
            content: data.content,
            status: 'done'
          })
          chatStore.appendToLastMessage(`\n💭 思考: ${data.content}\n`)
        }
        break

      case 'plan':
        if (data.actions) {
          const tools = data.actions.map((a: any) => a.tool).join(', ')
          chatStore.addThinkingStep(msgId, {
            type: 'plan',
            content: `计划执行: ${tools}`,
            status: 'done'
          })
          chatStore.appendToLastMessage(`\n📋 计划执行: ${tools}\n`)
        }
        break

      case 'action':
        if (data.tool) {
          chatStore.addThinkingStep(msgId, {
            type: 'action',
            content: `执行工具: ${data.tool}`,
            tool: data.tool,
            status: 'running'
          })
          chatStore.appendToLastMessage(`\n🔧 执行工具: ${data.tool}\n`)
        }
        break

      case 'observation': {
        // 更新最后一个 action 步骤为完成状态
        const lastMsg = chatStore.lastMessage
        if (lastMsg && lastMsg.role === 'assistant') {
          const steps = lastMsg.thinkingSteps
          for (let i = steps.length - 1; i >= 0; i--) {
            if (steps[i].type === 'action' && steps[i].status === 'running') {
              const resultPreview = data.result
                ? (typeof data.result === 'string'
                    ? data.result.substring(0, 150)
                    : JSON.stringify(data.result).substring(0, 150))
                : ''
              chatStore.updateThinkingStep(lastMsg.id, i, {
                status: 'done',
                result: resultPreview
              })
              break
            }
          }
        }
        if (data.result) {
          const resultPreview = typeof data.result === 'string'
            ? data.result.substring(0, 150)
            : JSON.stringify(data.result).substring(0, 150)
          chatStore.appendToLastMessage(`\n👀 观察结果: ${resultPreview}${resultPreview.length >= 150 ? '...' : ''}\n`)
        }
        break
      }

      case 'answer':
        if (data.content) {
          chatStore.appendToAnswer(msgId, data.content)
          chatStore.appendToLastMessage(data.content)
        }
        break

      case 'synthesize':
        if (data.answer) {
          chatStore.appendToAnswer(msgId, data.answer)
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
