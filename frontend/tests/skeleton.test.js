import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import SkeletonBox from '../src/components/shared/SkeletonBox.vue'
import SkeletonText from '../src/components/shared/SkeletonText.vue'
import SkeletonRow from '../src/components/shared/SkeletonRow.vue'

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

describe('SkeletonText', () => {
  it('renders the requested number of lines', () => {
    const w = mount(SkeletonText, { props: { lines: 4 } })
    expect(w.findAllComponents(SkeletonBox)).toHaveLength(4)
  })

  it('shortens the last line when more than one line', () => {
    const w = mount(SkeletonText, { props: { lines: 3 } })
    const boxes = w.findAllComponents(SkeletonBox)
    expect(boxes[2].props('width')).toBe('60%')
    expect(boxes[0].props('width')).toBe('100%')
  })

  it('does not shorten when only one line', () => {
    const w = mount(SkeletonText, { props: { lines: 1 } })
    const boxes = w.findAllComponents(SkeletonBox)
    expect(boxes).toHaveLength(1)
    expect(boxes[0].props('width')).toBe('100%')
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
