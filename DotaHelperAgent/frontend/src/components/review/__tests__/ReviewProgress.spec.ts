import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import ReviewProgress from '../ReviewProgress.vue'

describe('ReviewProgress', () => {
  it('renders percentage from progress prop', () => {
    const wrapper = mount(ReviewProgress, {
      props: { progress: 0.456, currentPhase: 'laning' }
    })
    expect(wrapper.text()).toContain('46%')
    expect(wrapper.text()).toContain('laning')
  })

  it('clamps progress between 0 and 100', () => {
    const wrapper = mount(ReviewProgress, {
      props: { progress: 1.5 }
    })
    expect(wrapper.text()).toContain('100%')

    const wrapper2 = mount(ReviewProgress, {
      props: { progress: -0.2 }
    })
    expect(wrapper2.text()).toContain('0%')
  })
})
