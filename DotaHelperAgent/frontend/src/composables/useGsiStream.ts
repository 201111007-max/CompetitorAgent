import { ref, onUnmounted } from 'vue'
import type { GSIEvent, GSIGameState, GSIStateResponse } from '@/types/gsi'

const baseURL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:5000'

export function useGsiStream() {
  const connected = ref(false)
  const currentState = ref<GSIGameState | null>(null)
  const events = ref<GSIEvent[]>([])
  let eventSource: EventSource | null = null

  const connect = () => {
    if (eventSource) {
      disconnect()
    }

    eventSource = new EventSource(`${baseURL}/api/gsi/events`)

    eventSource.onopen = () => {
      connected.value = true
    }

    // 监听所有 GSI 事件类型
    const eventTypes = [
      'stack', 'rune', 'neutral', 'roshan', 'daytime',
      'kill', 'death', 'item', 'level_up', 'game_start', 'game_end',
    ]

    eventTypes.forEach((type) => {
      eventSource!.addEventListener(type, (e: MessageEvent) => {
        try {
          const data = JSON.parse(e.data) as GSIEvent
          events.value.push(data)
          // 保留最近 100 条
          if (events.value.length > 100) {
            events.value = events.value.slice(-100)
          }
        } catch {
          // ignore parse errors
        }
      })
    })

    eventSource.onerror = () => {
      connected.value = false
    }
  }

  const disconnect = () => {
    if (eventSource) {
      eventSource.close()
      eventSource = null
    }
    connected.value = false
  }

  const fetchState = async () => {
    try {
      const response = await fetch(`${baseURL}/api/gsi/state`)
      const data: GSIStateResponse = await response.json()
      if (data.available && data.state) {
        currentState.value = data.state
        connected.value = data.connected
      } else {
        currentState.value = null
        connected.value = false
      }
    } catch {
      currentState.value = null
      connected.value = false
    }
  }

  onUnmounted(() => {
    disconnect()
  })

  return {
    connected,
    currentState,
    events,
    connect,
    disconnect,
    fetchState,
  }
}
