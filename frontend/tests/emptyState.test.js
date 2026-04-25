import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import EmptyState from '../src/components/shared/EmptyState.vue'

let mockRoute = { query: {}, path: '/' }
const mockRouter = { push: vi.fn(), replace: vi.fn() }

vi.mock('vue-router', () => ({
  useRoute: () => mockRoute,
  useRouter: () => mockRouter,
}))

const stubs = { 'lucide-vue-next': true }

const i18n = {
  global: {
    mocks: {
      $t: (k) => k,
    },
  },
}

beforeEach(() => {
  mockRoute = { query: {}, path: '/' }
  mockRouter.push.mockReset()
  mockRouter.replace.mockReset()
  try { window.localStorage.clear() } catch { /* ignore */ }
})

describe('EmptyState', () => {
  it('renders title and text', () => {
    const w = mount(EmptyState, {
      props: { title: 'No data', text: 'Nothing here yet.' },
      global: i18n.global,
    })
    expect(w.find('.empty-state__title').text()).toBe('No data')
    expect(w.find('.empty-state__text').text()).toBe('Nothing here yet.')
  })

  it('hides text paragraph when text prop missing', () => {
    const w = mount(EmptyState, {
      props: { title: 'No data' },
      global: i18n.global,
    })
    expect(w.find('.empty-state__text').exists()).toBe(false)
  })

  it('emits cta event when CTA button clicked', async () => {
    const w = mount(EmptyState, {
      props: { title: 'No data', ctaLabel: 'Add' },
      global: i18n.global,
    })
    await w.find('button.btn-primary').trigger('click')
    expect(w.emitted('cta')).toHaveLength(1)
  })

  it('renders doc link with target=_blank', () => {
    const w = mount(EmptyState, {
      props: { title: 'X', docHref: 'https://example.com/docs' },
      global: i18n.global,
    })
    const link = w.find('a.empty-state__link')
    expect(link.exists()).toBe(true)
    expect(link.attributes('href')).toBe('https://example.com/docs')
    expect(link.attributes('target')).toBe('_blank')
    expect(link.attributes('rel')).toBe('noopener noreferrer')
  })

  it('shows replay tour button when prop set, requests tour on click', async () => {
    const w = mount(EmptyState, {
      props: { title: 'X', replayTour: true },
      global: i18n.global,
    })
    const btns = w.findAll('button')
    const replay = btns.find(b => b.classes().includes('empty-state__link'))
    expect(replay).toBeDefined()
    await replay.trigger('click')
    expect(mockRouter.push).toHaveBeenCalledWith({ path: '/', query: { tour: '1' } })
  })

  it('renders inline modifier class', () => {
    const w = mount(EmptyState, {
      props: { title: 'X', inline: true },
      global: i18n.global,
    })
    expect(w.classes()).toContain('empty-state--inline')
  })

  it('hides actions block when no cta/doc/tour props', () => {
    const w = mount(EmptyState, {
      props: { title: 'X' },
      global: i18n.global,
    })
    expect(w.find('.empty-state__actions').exists()).toBe(false)
  })
})
