export interface ThinkingStep {
  type: 'think' | 'plan' | 'action' | 'observation' | 'goal'
  content: string
  tool?: string
  result?: string
  status: 'running' | 'done' | 'error'
}

export interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  thinkingSteps: ThinkingStep[]
  answerContent: string
  timestamp: Date
}

export interface Conversation {
  id: string
  title: string
  messages: Message[]
  sessionId: string
  traceId: string
  createdAt: number
  updatedAt: number
}

export interface ChatState {
  messages: Message[]
  isStreaming: boolean
  sessionId: string
  traceId: string
  conversations: Conversation[]
  currentConversationId: string
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
