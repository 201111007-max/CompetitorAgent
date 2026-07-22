import { defineStore } from 'pinia'
import type {
  ReviewReport,
  ProgressEvent,
  ReviewHistoryItem,
  ReviewStatus
} from '@/types/review'

export interface PhaseProgress {
  phase: string
  started: boolean
  completed: boolean
}

export const useReviewStore = defineStore('review', {
  state: () => ({
    status: 'idle' as ReviewStatus,
    progress: 0,
    currentPhase: undefined as string | undefined,
    matchId: '',
    errorMessage: '',
    report: undefined as ReviewReport | undefined,
    phaseProgress: {} as Record<string, PhaseProgress>,
    history: [] as ReviewHistoryItem[]
  }),

  getters: {
    isAnalyzing: (state) => state.status === 'analyzing',
    isCompleted: (state) => state.status === 'completed',
    isError: (state) => state.status === 'error',
    hasReport: (state) => state.report !== undefined,
    phaseList: (state) => Object.values(state.phaseProgress)
  },

  actions: {
    startReview(matchId: string) {
      this.matchId = matchId
      this.status = 'analyzing'
      this.progress = 0
      this.currentPhase = undefined
      this.errorMessage = ''
      this.report = undefined
      this.phaseProgress = {}
    },

    handleProgressEvent(event: ProgressEvent) {
      this.progress = event.progress

      if (event.message) {
        // 使用事件消息作为当前阶段提示
      }

      switch (event.event) {
        case 'phase_start':
          if (event.phase) {
            this.currentPhase = event.phase
            if (!this.phaseProgress[event.phase]) {
              this.phaseProgress[event.phase] = {
                phase: event.phase,
                started: true,
                completed: false
              }
            } else {
              this.phaseProgress[event.phase].started = true
            }
          }
          break

        case 'phase_complete':
          if (event.phase) {
            this.currentPhase = event.phase
            if (!this.phaseProgress[event.phase]) {
              this.phaseProgress[event.phase] = {
                phase: event.phase,
                started: true,
                completed: true
              }
            } else {
              this.phaseProgress[event.phase].completed = true
            }
          }
          break

        case 'report':
          this.status = 'completed'
          this.currentPhase = undefined
          this.progress = 1
          if (event.payload.report) {
            this.report = event.payload.report as ReviewReport
          }
          break

        case 'error':
          this.status = 'error'
          this.errorMessage = event.message || '复盘执行失败'
          this.currentPhase = undefined
          break

        default:
          break
      }
    },

    setReport(report: ReviewReport) {
      this.report = report
      this.status = 'completed'
      this.progress = 1
      this.currentPhase = undefined
    },

    setError(message: string) {
      this.status = 'error'
      this.errorMessage = message
      this.currentPhase = undefined
    },

    setInterrupted() {
      this.status = 'interrupted'
      this.currentPhase = undefined
    },

    setHistory(history: ReviewHistoryItem[]) {
      this.history = history
    },

    reset() {
      this.status = 'idle'
      this.progress = 0
      this.currentPhase = undefined
      this.matchId = ''
      this.errorMessage = ''
      this.report = undefined
      this.phaseProgress = {}
    }
  }
})
