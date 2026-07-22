import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import ReviewHistory from '../ReviewHistory.vue'
import type { ReviewHistoryItem } from '@/types/review'

const history: ReviewHistoryItem[] = [
  {
    match_id: '12345',
    status: 'completed',
    overall_score: 7.5,
    overall_confidence: 0.75,
    terminal_state: 'completed',
    created_at: new Date().toISOString()
  }
]

describe('ReviewHistory', () => {
  it('renders history items', () => {
    const wrapper = mount(ReviewHistory, {
      props: { history, loading: false }
    })
    expect(wrapper.text()).toContain('12345')
    expect(wrapper.text()).toContain('已完成')
    expect(wrapper.text()).toContain('评分 7.5')
  })

  it('emits select event on item click', () => {
    const wrapper = mount(ReviewHistory, {
      props: { history, loading: false }
    })
    wrapper.find('.history-item').trigger('click')
    expect(wrapper.emitted('select')).toBeTruthy()
    expect(wrapper.emitted('select')![0]).toEqual(['12345'])
  })
})
