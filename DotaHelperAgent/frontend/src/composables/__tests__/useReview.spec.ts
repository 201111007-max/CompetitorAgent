import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { defineComponent, nextTick } from 'vue'
import { useReview } from '@/composables/useReview'
import type { ProgressEvent } from '@/types/review'

const createMockEventSource = (events: ProgressEvent[]) => {
  return class MockEventSource {
    onopen?: () => void
    onmessage?: (msg: MessageEvent) => void
    onerror?: (err: Event) => void
    closed = false

    constructor() {
      setTimeout(() => {
        if (this.onopen) this.onopen()
        events.forEach((evt, idx) => {
          setTimeout(() => {
            if (this.onmessage) {
              this.onmessage({ data: JSON.stringify(evt) } as MessageEvent)
            }
            if (idx === events.length - 1 && this.closed) {
              // stream finished
            }
          }, 10)
        })
      }, 10)
    }

    close() {
      this.closed = true
    }
  }
}

describe('useReview', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.stubGlobal('fetch', vi.fn(() => Promise.resolve({
      ok: true,
      json: () => Promise.resolve({ success: true, history: [] })
    } as Response)))
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('starts review and handles progress events', async () => {
    const events: ProgressEvent[] = [
      { event: 'phase_start', phase: 'laning', progress: 0.2, message: '开始', payload: {} },
      { event: 'phase_complete', phase: 'laning', progress: 0.5, message: '完成', payload: {} },
      {
        event: 'report',
        progress: 1,
        message: '报告',
        payload: {
          report: {
            match_id: '12345',
            match_summary: {},
            phase_results: [],
            overall_score: 5,
            overall_confidence: 0.5,
            key_findings: [],
            improvement_areas: [],
            markdown_report: '',
            terminal_state: 'completed',
            created_at: new Date().toISOString()
          }
        }
      }
    ]
    vi.stubGlobal('EventSource', createMockEventSource(events))

    const TestComp = defineComponent({
      setup() {
        const { reviewStore, startReview } = useReview()
        return { reviewStore, startReview }
      },
      template: '<div></div>'
    })

    const wrapper = mount(TestComp)
    wrapper.vm.startReview('12345')

    await new Promise((r) => setTimeout(r, 100))
    await nextTick()

    expect(wrapper.vm.reviewStore.matchId).toBe('12345')
    expect(wrapper.vm.reviewStore.phaseProgress.laning.completed).toBe(true)
    expect(wrapper.vm.reviewStore.status).toBe('completed')
  })
})
