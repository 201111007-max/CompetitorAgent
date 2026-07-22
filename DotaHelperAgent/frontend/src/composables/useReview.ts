import { ref, onUnmounted } from 'vue'
import { useReviewStore } from '@/stores/review'
import {
  startReviewStream,
  interruptReview,
  listReviewHistory,
  getReviewReport
} from '@/api/review'
import type { ProgressEvent } from '@/types/review'

export function useReview() {
  const reviewStore = useReviewStore()
  const eventSource = ref<EventSource | null>(null)
  const isLoadingHistory = ref(false)

  /**
   * 启动复盘 SSE 流
   *
   * @param matchId 比赛 ID
   */
  const startReview = (matchId: string) => {
    cleanup()
    reviewStore.startReview(matchId)

    eventSource.value = startReviewStream(
      matchId,
      (event: ProgressEvent) => {
        reviewStore.handleProgressEvent(event)
      },
      {
        onError: () => {
          if (reviewStore.status !== 'completed') {
            reviewStore.setError('SSE 连接异常中断')
          }
        }
      }
    )
  }

  /**
   * 中断当前复盘
   */
  const interrupt = async () => {
    if (!reviewStore.matchId) return

    try {
      await interruptReview(reviewStore.matchId)
      reviewStore.setInterrupted()
    } catch (e) {
      reviewStore.setError(e instanceof Error ? e.message : '中断复盘失败')
    } finally {
      cleanup()
    }
  }

  /**
   * 获取历史列表
   */
  const loadHistory = async () => {
    isLoadingHistory.value = true
    try {
      const res = await listReviewHistory()
      if (res.success) {
        reviewStore.setHistory(res.history)
      }
    } catch (e) {
      console.error('加载复盘历史失败:', e)
    } finally {
      isLoadingHistory.value = false
    }
  }

  /**
   * 根据 match_id 获取报告（用于历史列表点击）
   *
   * @param matchId 比赛 ID
   */
  const loadReport = async (matchId: string) => {
    try {
      const res = await getReviewReport(matchId)
      if (res.success && res.report) {
        reviewStore.setReport(res.report)
      } else if (res.error) {
        reviewStore.setError(res.error)
      }
    } catch (e) {
      reviewStore.setError(e instanceof Error ? e.message : '加载报告失败')
    }
  }

  /**
   * 清理 EventSource
   */
  const cleanup = () => {
    if (eventSource.value) {
      eventSource.value.close()
      eventSource.value = null
    }
  }

  /**
   * 重置状态
   */
  const reset = () => {
    cleanup()
    reviewStore.reset()
  }

  onUnmounted(() => {
    cleanup()
  })

  return {
    reviewStore,
    eventSource,
    isLoadingHistory,
    startReview,
    interrupt,
    loadHistory,
    loadReport,
    cleanup,
    reset
  }
}
