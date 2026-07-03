/**
 * C4 (bilan 2026-07) — sort persistence for MonitorsView.
 *
 * sortKey/sortDir used to be plain refs (reset on every reload). They now
 * live inside the same `useFilterPreset('monitors', …)` preset as the other
 * filters, so a reload / re-navigation restores the last sort too.
 *
 * Migration safety: presets saved before this change only contain
 * q/status/type/group — no sortKey/sortDir keys. useFilterPreset must fall
 * back to the current defaults ('status'/'asc') for those, not crash or
 * coerce to undefined.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { ref } from 'vue'
import { useMonitorFilters } from '../src/composables/useMonitorFilters'

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

vi.mock('vue-i18n', () => ({
  useI18n: () => ({ t: (k) => k }),
}))

const waitDebounce = () => new Promise((r) => setTimeout(r, 300))

beforeEach(() => {
  localStorage.clear()
  routeState.query = {}
  routerState.replace.mockClear()
})

function monitors() {
  return ref([
    { id: '1', name: 'b-svc', check_type: 'http', enabled: true, _lastStatus: 'down', _uptime24h: 90, _lastResponseTimeMs: 100 },
    { id: '2', name: 'a-svc', check_type: 'http', enabled: true, _lastStatus: 'up', _uptime24h: 99, _lastResponseTimeMs: 50 },
  ])
}

describe('useMonitorFilters — sort persistence', () => {
  it('defaults to status/asc when nothing stored', () => {
    const { isSorted, sortIcon } = useMonitorFilters(monitors())
    expect(isSorted('status')).toBe(true)
    expect(sortIcon('status')).not.toBeNull()
  })

  it('restores a previously persisted sort from localStorage', () => {
    localStorage.setItem(
      'whatisup_filter:monitors',
      JSON.stringify({ q: '', status: '', type: '', group: '', sortKey: 'name', sortDir: 'desc' }),
    )
    const { isSorted } = useMonitorFilters(monitors())
    expect(isSorted('name')).toBe(true)
  })

  it('legacy preset without sortKey/sortDir falls back to defaults (soft migration)', () => {
    // Preset saved by a pre-C4 build — only the original filter keys exist.
    localStorage.setItem(
      'whatisup_filter:monitors',
      JSON.stringify({ q: '', status: 'down', type: '', group: '' }),
    )
    const { isSorted, filterStatus } = useMonitorFilters(monitors())
    expect(filterStatus.value).toBe('down')
    expect(isSorted('status')).toBe(true) // default sortKey, not crashed/undefined
  })

  it('setSortKey persists to localStorage and survives a fresh composable instance', async () => {
    const list = monitors()
    const { setSortKey } = useMonitorFilters(list)
    setSortKey('name')
    await waitDebounce()
    const stored = JSON.parse(localStorage.getItem('whatisup_filter:monitors'))
    expect(stored.sortKey).toBe('name')
    expect(stored.sortDir).toBe('asc')

    // Simulate reload: new composable instance reads the persisted state back.
    const { isSorted: isSorted2 } = useMonitorFilters(monitors())
    expect(isSorted2('name')).toBe(true)
  })

  it('clicking the same sort key twice flips direction and persists it', async () => {
    const { setSortKey, isSorted, sortIcon } = useMonitorFilters(monitors())
    setSortKey('uptime')
    expect(isSorted('uptime')).toBe(true)
    const firstIcon = sortIcon('uptime')
    setSortKey('uptime')
    const secondIcon = sortIcon('uptime')
    expect(secondIcon).not.toBe(firstIcon)
    await waitDebounce()
    const stored = JSON.parse(localStorage.getItem('whatisup_filter:monitors'))
    expect(stored.sortKey).toBe('uptime')
  })

  it('clearFilters resets the filters but preserves the sort order (review C4)', async () => {
    const { setSortKey, isSorted, sortIcon, filterStatus, search, searchInput_, clearFilters } =
      useMonitorFilters(monitors())

    setSortKey('name')
    setSortKey('name') // flip asc → desc
    const iconBefore = sortIcon('name')
    filterStatus.value = 'down'
    search.value = 'svc'

    clearFilters()

    // Filters are gone…
    expect(filterStatus.value).toBe('')
    expect(search.value).toBe('')
    expect(searchInput_.value).toBe('')
    // …but the sort (key AND direction) survives — sorting is not a filter.
    expect(isSorted('name')).toBe(true)
    expect(sortIcon('name')).toBe(iconBefore)

    // The preserved sort is re-persisted for the next reload.
    await waitDebounce()
    const stored = JSON.parse(localStorage.getItem('whatisup_filter:monitors'))
    expect(stored.sortKey).toBe('name')
    expect(stored.sortDir).toBe('desc')
  })

  it('filteredMonitors reflects the persisted sort order', () => {
    localStorage.setItem(
      'whatisup_filter:monitors',
      JSON.stringify({ q: '', status: '', type: '', group: '', sortKey: 'name', sortDir: 'asc' }),
    )
    const { filteredMonitors } = useMonitorFilters(monitors())
    expect(filteredMonitors.value.map(m => m.name)).toEqual(['a-svc', 'b-svc'])
  })
})
