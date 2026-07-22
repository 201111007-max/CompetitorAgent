import { describe, it, expect, beforeEach } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useReviewStore } from '@/stores/review'
import type { ProgressEvent, ReviewReport } from '@/types/review'

const mockReport: ReviewReport = {
  match_id: '12345',
  match_summary: {
    match_id: '12345',
    duration: 1800,
    radiant_win: true,
    radiant_score: 30,
    dire_score: 20,
    user_hero: 'Anti-Mage',
    user_team_win: true,
    key_events: []
  },
  phase_results: [],
  overall_score: 7.5,
  overall_confidence: 0.75,
  key_findings: ['对线稳定'],
  improvement_areas: ['团战站位'],
  markdown_report: '# 报告',
  terminal_state: 'completed',
  created_at: new Date().toISOString()
}

describe('useReviewStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('should have idle initial state', () => {
    const store = useReviewStore()
    expect(store.status).toBe('idle')
    expect(store.progress).toBe(0)
    expect(store.report).toBeUndefined()
  })

  it('should start a review', () => {
    const store = useReviewStore()
    store.startReview('12345')
    expect(store.matchId).toBe('12345')
    expect(store.status).toBe('analyzing')
    expect(store.progress).toBe(0)
    expect(store.report).toBeUndefined()
  })

  it('should track phase progress events', () => {
    const store = useReviewStore()
    store.startReview('12345')

    const startEvent: ProgressEvent = {
      event: 'phase_start',
      phase: 'laning',
      progress: 0.2,
      message: '开始分析阶段: laning',
      payload: {}
    }
    store.handleProgressEvent(startEvent)
    expect(store.currentPhase).toBe('laning')
    expect(store.phaseProgress.laning.started).toBe(true)
    expect(store.phaseProgress.laning.completed).toBe(false)

    const completeEvent: ProgressEvent = {
      event: 'phase_complete',
      phase: 'laning',
      progress: 0.5,
      message: '阶段完成',
      payload: {}
    }
    store.handleProgressEvent(completeEvent)
    expect(store.phaseProgress.laning.completed).toBe(true)
  })

  it('should set report on report event', () => {
    const store = useReviewStore()
    store.startReview('12345')

    const reportEvent: ProgressEvent = {
      event: 'report',
      progress: 1,
      message: '完成',
      payload: { report: mockReport as unknown as Record<string, unknown> }
    }
    store.handleProgressEvent(reportEvent)
    expect(store.status).toBe('completed')
    expect(store.report).toEqual(mockReport)
    expect(store.progress).toBe(1)
  })

  it('should handle error events', () => {
    const store = useReviewStore()
    store.startReview('12345')

    const errorEvent: ProgressEvent = {
      event: 'error',
      progress: 0,
      message: '复盘失败',
      payload: {}
    }
    store.handleProgressEvent(errorEvent)
    expect(store.status).toBe('error')
    expect(store.errorMessage).toBe('复盘失败')
  })
})
