import { describe, it, expect, vi } from 'vitest'
import { mount } from '@vue/test-utils'

// SkeletonRow traduit son aria-label : on stubbe `t` faute de plugin i18n ici.
vi.mock('vue-i18n', () => ({ useI18n: () => ({ t: (k) => k }) }))

const SkeletonBox = (await import('../src/components/shared/SkeletonBox.vue')).default
const SkeletonRow = (await import('../src/components/shared/SkeletonRow.vue')).default

describe('SkeletonBox', () => {
  it('renders with .skeleton class and aria-busy', () => {
    const w = mount(SkeletonBox)
    const root = w.find('.skeleton')
    expect(root.exists()).toBe(true)
    expect(root.attributes('aria-busy')).toBe('true')
    expect(root.attributes('role')).toBe('status')
  })

  it('applies width and height as inline styles', () => {
    const w = mount(SkeletonBox, { props: { width: '12rem', height: '2rem' } })
    const style = w.attributes('style') || ''
    expect(style).toContain('width: 12rem')
    expect(style).toContain('height: 2rem')
  })

  it('coerces numeric width/height to px', () => {
    const w = mount(SkeletonBox, { props: { width: 200, height: 40 } })
    const style = w.attributes('style') || ''
    expect(style).toContain('width: 200px')
    expect(style).toContain('height: 40px')
  })

  it('renders as circle when prop is set', () => {
    const w = mount(SkeletonBox, { props: { circle: true, height: '2rem' } })
    expect(w.classes()).toContain('skeleton-circle')
    const style = w.attributes('style') || ''
    expect(style).toContain('border-radius: 50%')
  })

  it('uses provided rounded variant', () => {
    const w = mount(SkeletonBox, { props: { rounded: 'full' } })
    expect(w.attributes('style')).toContain('border-radius: 9999px')
  })

  it('uses ariaLabel prop', () => {
    const w = mount(SkeletonBox, { props: { ariaLabel: 'Loading chart' } })
    expect(w.attributes('aria-label')).toBe('Loading chart')
  })
})

describe('SkeletonRow', () => {
  it('renders circle by default plus 2 lines plus trailing block', () => {
    const w = mount(SkeletonRow)
    const boxes = w.findAllComponents(SkeletonBox)
    expect(boxes).toHaveLength(4)
    expect(boxes[0].props('circle')).toBe(true)
    expect(boxes[3].props('width')).toBe('4rem')
  })

  it('drops the circle when circle=false', () => {
    const w = mount(SkeletonRow, { props: { circle: false } })
    const boxes = w.findAllComponents(SkeletonBox)
    expect(boxes).toHaveLength(3)
  })

  it('drops the trailing block when trailing=false', () => {
    const w = mount(SkeletonRow, { props: { trailing: false } })
    const boxes = w.findAllComponents(SkeletonBox)
    expect(boxes).toHaveLength(3)
  })
})
