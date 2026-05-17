export interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  timestamp: Date
}

export interface ChatState {
  messages: Message[]
  isStreaming: boolean
  sessionId: string
  traceId: string
}

export interface SSEEvent {
  event: string
  data: any
}

export interface ChatRequest {
  query: string
  context?: {
    our_heroes?: string[]
    enemy_heroes?: string[]
  }
  session_id?: string
}
