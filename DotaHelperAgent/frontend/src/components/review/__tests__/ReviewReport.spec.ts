import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import ReviewReport from '../ReviewReport.vue'
import type { ReviewReport as ReportType } from '@/types/review'

const mockReport: ReportType = {
  match_id: '12345',
  match_summary: {
    match_id: '12345',
    duration: 1850,
    radiant_win: true,
    radiant_score: 40,
    dire_score: 25,
    user_hero: 'Anti-Mage',
    user_team_win: true,
    key_events: []
  },
  phase_results: [],
  overall_score: 8.0,
  overall_confidence: 0.8,
  key_findings: ['发育良好'],
  improvement_areas: ['参团时机'],
  markdown_report: '# 复盘报告\n\n内容',
  terminal_state: 'completed',
  created_at: new Date().toISOString()
}

describe('ReviewReport', () => {
  it('renders summary and markdown report', () => {
    const wrapper = mount(ReviewReport, {
      props: { report: mockReport }
    })
    expect(wrapper.text()).toContain('12345')
    expect(wrapper.text()).toContain('Anti-Mage')
    expect(wrapper.text()).toContain('8.0')
    expect(wrapper.text()).toContain('80%')
    expect(wrapper.find('.markdown-renderer').exists()).toBe(true)
  })
})
