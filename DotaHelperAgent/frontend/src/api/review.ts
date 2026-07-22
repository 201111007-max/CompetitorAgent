import type {
  ReviewReport,
  ProgressEvent,
  ReviewStatusResponse,
  ReviewReportResponse,
  ReviewHistoryResponse,
  InterruptReviewResponse
} from '@/types/review'

const baseURL = import.meta.env.VITE_API_BASE_URL || ''

/**
 * 启动复盘 SSE 流
 *
 * @param matchId 比赛 ID
 * @param onEvent 事件回调
 * @returns EventSource 实例，调用方负责关闭
 */
export function startReviewStream(
  matchId: string,
  onEvent: (event: ProgressEvent) => void,
  options?: {
    onError?: (error: MessageEvent | Event) => void
    onOpen?: () => void
  }
): EventSource {
  const es = new EventSource(`${baseURL}/api/review?match_id=${encodeURIComponent(matchId)}`, {
    withCredentials: false
  })

  es.onopen = () => {
    options?.onOpen?.()
  }

  es.onmessage = (msg) => {
    try {
      const data = JSON.parse(msg.data) as ProgressEvent
      onEvent(data)
    } catch (e) {
      console.error('解析复盘 SSE 数据失败:', msg.data, e)
    }
  }

  es.onerror = (error) => {
    console.error('复盘 SSE 连接错误:', error)
    options?.onError?.(error)
  }

  return es
}

/**
 * 获取复盘任务状态
 *
 * @param matchId 比赛 ID
 * @returns 状态响应
 */
export async function getReviewStatus(matchId: string): Promise<ReviewStatusResponse> {
  const res = await fetch(`${baseURL}/api/review/${encodeURIComponent(matchId)}/status`)
  return res.json()
}

/**
 * 获取复盘报告
 *
 * @param matchId 比赛 ID
 * @returns 报告响应
 */
export async function getReviewReport(matchId: string): Promise<ReviewReportResponse> {
  const res = await fetch(`${baseURL}/api/review/${encodeURIComponent(matchId)}/report`)
  return res.json()
}

/**
 * 中断复盘任务
 *
 * @param matchId 比赛 ID
 * @returns 中断结果
 */
export async function interruptReview(matchId: string): Promise<InterruptReviewResponse> {
  const res = await fetch(`${baseURL}/api/review/${encodeURIComponent(matchId)}/interrupt`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' }
  })
  return res.json()
}

/**
 * 获取复盘历史列表
 *
 * @returns 历史列表响应
 */
export async function listReviewHistory(): Promise<ReviewHistoryResponse> {
  const res = await fetch(`${baseURL}/api/review/history`)
  return res.json()
}

/**
 * 启动复盘（非流式，直接等待报告）
 *
 * @param matchId 比赛 ID
 * @returns 报告
 */
export async function startReview(matchId: string): Promise<ReviewReport> {
  const res = await fetch(`${baseURL}/api/review?match_id=${encodeURIComponent(matchId)}`, {
    method: 'POST'
  })

  if (!res.ok) {
    throw new Error(`启动复盘失败: ${res.status}`)
  }

  // 读取 SSE 流直到 report 事件
  const reader = res.body?.getReader()
  const decoder = new TextDecoder()
  if (!reader) {
    throw new Error('响应体为空')
  }

  let buffer = ''
  while (true) {
    const { done, value } = await reader.read()
    if (done) break

    buffer += decoder.decode(value, { stream: true })
    const lines = buffer.split('\n')
    buffer = lines.pop() || ''

    for (const line of lines) {
      if (line.startsWith('data: ')) {
        const data = line.slice(6)
        if (!data.trim()) continue
        try {
          const event = JSON.parse(data) as ProgressEvent
          if (event.event === 'report' && event.payload.report) {
            return event.payload.report as ReviewReport
          }
          if (event.event === 'error') {
            throw new Error(event.message || '复盘执行失败')
          }
        } catch (e) {
          if (e instanceof Error && e.message.includes('复盘')) {
            throw e
          }
          console.error('解析 SSE 数据失败:', data, e)
        }
      }
    }
  }

  throw new Error('复盘流提前结束，未收到报告')
}
