import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import ReviewTimeline from '../ReviewTimeline.vue'
import type { PhaseProgress } from '@/stores/review'

describe('ReviewTimeline', () => {
  const phases: PhaseProgress[] = [
    { phase: 'laning', started: true, completed: true },
    { phase: 'teamfight', started: true, completed: false },
    { phase: 'economy', started: false, completed: false }
  ]

  it('renders phase labels in Chinese', () => {
    const wrapper = mount(ReviewTimeline, {
      props: { phases, currentPhase: 'teamfight' }
    })
    expect(wrapper.text()).toContain('对线期')
    expect(wrapper.text()).toContain('团战分析')
    expect(wrapper.text()).toContain('经济发育')
  })

  it('marks active phase', () => {
    const wrapper = mount(ReviewTimeline, {
      props: { phases, currentPhase: 'teamfight' }
    })
    const items = wrapper.findAll('.timeline-item')
    expect(items[1].classes()).toContain('active')
    expect(items[0].classes()).toContain('completed')
  })
})
