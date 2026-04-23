import { describe, it, expect, beforeEach, vi } from 'vitest'
import { nextTick } from 'vue'
import { useFilterPreset } from '../src/composables/useFilterPreset'

// Mock vue-router's useRoute / useRouter — we only need a reactive-ish
// query bag and a replace() that mutates it.
const routeState = { query: {} }
const routerState = {
  replace: vi.fn(({ query } = {}) => {
    routeState.query = { ...(query || {}) }
    return Promise.resolve()
  }),
}

vi.mock('vue-router', () => ({
  useRoute: () => routeState,
  useRouter: () => routerState,
}))

beforeEach(() => {
  localStorage.clear()
  routeState.query = {}
  routerState.replace.mockClear()
})

// Helper — waits past the internal 120ms debounce, with margin for jsdom.
const waitDebounce = () => new Promise((r) => setTimeout(r, 300))

describe('useFilterPreset', () => {
  it('defaults apply when no query / storage present', () => {
    const { state } = useFilterPreset('v', { status: 'all', days: 30 })
    expect(state.status).toBe('all')
    expect(state.days).toBe(30)
  })

  it('URL query overrides defaults', () => {
    routeState.query = { status: 'open', days: '7' }
    const { state } = useFilterPreset('v', { status: 'all', days: 30 })
    expect(state.status).toBe('open')
    expect(state.days).toBe(7)
  })

  it('localStorage overrides defaults when no query', () => {
    localStorage.setItem(
      'whatisup_filter:v',
      JSON.stringify({ status: 'resolved', days: 90 }),
    )
    const { state } = useFilterPreset('v', { status: 'all', days: 30 })
    expect(state.status).toBe('resolved')
    expect(state.days).toBe(90)
  })

  it('URL query takes priority over localStorage', () => {
    localStorage.setItem('whatisup_filter:v', JSON.stringify({ status: 'resolved' }))
    routeState.query = { status: 'open' }
    const { state } = useFilterPreset('v', { status: 'all' })
    expect(state.status).toBe('open')
  })

  it('mutations persist to both localStorage and router', async () => {
    const { state } = useFilterPreset('v', { status: 'all', days: 30 })
    state.status = 'open'
    state.days = 7
    await nextTick()
    await waitDebounce()
    expect(routerState.replace).toHaveBeenCalled()
    const stored = JSON.parse(localStorage.getItem('whatisup_filter:v'))
    expect(stored.status).toBe('open')
    expect(stored.days).toBe(7)
    // Default values are stripped from the URL
    expect(routeState.query.status).toBe('open')
    expect(routeState.query.days).toBe('7')
  })

  it('array values serialize as CSV', async () => {
    const { state } = useFilterPreset('v', { tags: [] })
    // Assigning a new array is more reliable than mutating in place under
    // reactive proxies + deep-watch coalescing in jsdom tests.
    state.tags = ['prod', 'api']
    await nextTick()
    await waitDebounce()
    expect(routeState.query.tags).toBe('prod,api')
    const stored = JSON.parse(localStorage.getItem('whatisup_filter:v'))
    expect(stored.tags).toEqual(['prod', 'api'])
  })

  it('reset wipes storage, query and restores defaults', async () => {
    const { state, reset } = useFilterPreset('v', { status: 'all', days: 30 })
    state.status = 'open'
    await nextTick()
    await waitDebounce()
    reset()
    expect(state.status).toBe('all')
    expect(state.days).toBe(30)
    expect(localStorage.getItem('whatisup_filter:v')).toBe(null)
    expect(routeState.query.status).toBeUndefined()
  })

  it('prefix avoids query-param collisions between groups', async () => {
    const { state } = useFilterPreset('v', { status: 'all' }, { prefix: 'inc' })
    state.status = 'open'
    await nextTick()
    await waitDebounce()
    expect(routeState.query.inc_status).toBe('open')
    expect(routeState.query.status).toBeUndefined()
  })
})
