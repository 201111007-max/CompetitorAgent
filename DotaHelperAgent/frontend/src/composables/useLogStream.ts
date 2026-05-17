import { ref, onUnmounted } from 'vue'
import { useLogStore } from '@/stores/log'
import type { LogEntry } from '@/types/log'

const baseURL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:5000'

export function useLogStream() {
  const logStore = useLogStore()
  const isConnected = ref(false)
  const error = ref<string | null>(null)
  let eventSource: EventSource | null = null

  const connect = (sessionId?: string) => {
    if (eventSource) {
      disconnect()
    }

    const url = sessionId
      ? `${baseURL}/api/logs/stream?session_id=${sessionId}`
      : `${baseURL}/api/logs/stream`

    eventSource = new EventSource(url)
    isConnected.value = true
    error.value = null

    eventSource.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data)
        
        if (data.type === 'heartbeat') {
          return
        }
        
        if (data.level && data.message) {
          logStore.addEntry(data as LogEntry)
        }
      } catch (e) {
        console.error('Failed to parse log:', event.data)
      }
    }

    eventSource.onerror = () => {
      error.value = 'Connection lost'
      isConnected.value = false
    }
  }

  const disconnect = () => {
    if (eventSource) {
      eventSource.close()
      eventSource = null
    }
    isConnected.value = false
  }

  onUnmounted(() => {
    disconnect()
  })

  return {
    connect,
    disconnect,
    isConnected,
    error
  }
}

export async function fetchLogs(sessionId?: string): Promise<LogEntry[]> {
  const url = sessionId
    ? `${baseURL}/api/logs?session_id=${sessionId}`
    : `${baseURL}/api/logs`

  const response = await fetch(url)
  const data = await response.json()
  return data.logs || []
}

export async function clearLogs(): Promise<void> {
  await fetch(`${baseURL}/api/logs/clear`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({})
  })
}
