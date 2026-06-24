import { ref, onUnmounted } from 'vue'
import type { Recommendation } from '@/types/gsi'

const baseURL = import.meta.env.VITE_API_BASE_URL || ''

export function useRecommendationStream() {
  const connected = ref(false)
  const recommendations = ref<Recommendation[]>([])
  const recommendationStatus = ref<any>(null)
  let eventSource: EventSource | null = null

  const connect = () => {
    if (eventSource) {
      disconnect()
    }

    eventSource = new EventSource(`${baseURL}/api/gsi/recommendations`)

    eventSource.onopen = () => {
      connected.value = true
    }

    // 监听推荐事件
    eventSource.addEventListener('recommendation', (e: MessageEvent) => {
      try {
        const data = JSON.parse(e.data) as Recommendation
        recommendations.value.push(data)
        // 保留最近 50 条推荐
        if (recommendations.value.length > 50) {
          recommendations.value = recommendations.value.slice(-50)
        }
      } catch {
        // ignore parse errors
      }
    })

    // 监听心跳
    eventSource.addEventListener('heartbeat', () => {
      // 心跳包，保持连接
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

  const fetchStatus = async () => {
    try {
      const response = await fetch(`${baseURL}/api/gsi/recommendation/status`)
      const data = await response.json()
      recommendationStatus.value = data
    } catch {
      recommendationStatus.value = null
    }
  }

  const clearRecommendations = () => {
    recommendations.value = []
  }

  onUnmounted(() => {
    disconnect()
  })

  return {
    connected,
    recommendations,
    recommendationStatus,
    connect,
    disconnect,
    fetchStatus,
    clearRecommendations,
  }
}
