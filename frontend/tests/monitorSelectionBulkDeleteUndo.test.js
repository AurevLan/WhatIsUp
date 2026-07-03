/**
 * C4 (bilan 2026-07) — bulk delete "Undo" toast in useMonitorSelection.js.
 *
 * The real delete API call is deferred until the toast expires (~6s):
 *   - clicking Undo restores the monitors locally and NEVER calls the API.
 *   - letting the toast run its course fires the deferred bulkAction('delete').
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { computed } from 'vue'

vi.mock('vue-i18n', () => ({
  useI18n: () => ({ t: (k, params) => (params ? `${k}:${JSON.stringify(params)}` : k) }),
}))

const confirmMock = vi.fn()
vi.mock('../src/composables/useConfirm', () => ({
  useConfirm: () => ({ confirm: confirmMock }),
}))

vi.mock('../src/api/monitors', () => ({
  monitorsApi: {
    list: vi.fn().mockResolvedValue({ data: [] }),
    bulkAction: vi.fn().mockResolvedValue({ data: {} }),
  },
  groupsApi: { list: vi.fn().mockResolvedValue({ data: [] }) },
}))

vi.mock('../src/api/client', () => ({
  default: { get: vi.fn().mockResolvedValue({ data: [] }) },
}))

// Namespace import so this file also runs against pre-fix sources (where
// clearPendingDeletes does not exist yet) — see the review M1 tests below.
import * as monitorsStoreModule from '../src/stores/monitors'
import { monitorsApi } from '../src/api/monitors'

const { useMonitorStore } = monitorsStoreModule
import { useMonitorSelection } from '../src/composables/useMonitorSelection'
import { useToast } from '../src/composables/useToast'

function makeMonitor(id, name) {
  return { id, name, url: 'https://x', check_type: 'http', enabled: true, _lastStatus: 'up' }
}

function setup(monitorList) {
  const store = useMonitorStore()
  store.monitors = monitorList
  const monitors = computed(() => store.monitors)
  const filteredMonitors = computed(() => store.monitors)
  const sel = useMonitorSelection(monitors, filteredMonitors)
  return { store, sel }
}

describe('useMonitorSelection — bulk delete undo toast', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.useFakeTimers()
    confirmMock.mockReset()
    monitorsApi.bulkAction.mockClear()
    monitorsApi.list.mockClear()
    monitorsApi.list.mockResolvedValue({ data: [] })
    // The pending-delete registry is module-level — reset it between cases.
    monitorsStoreModule.clearPendingDeletes?.()
    const { toasts, remove } = useToast()
    for (const t of [...toasts]) remove(t.id)
  })

  afterEach(() => {
    vi.clearAllTimers()
    vi.useRealTimers()
  })

  it('does nothing if the confirm dialog is dismissed', async () => {
    confirmMock.mockResolvedValue(false)
    const { store, sel } = setup([makeMonitor('1', 'a'), makeMonitor('2', 'b')])
    sel.selectedIds.value = new Set(['1'])
    await sel.confirmBulkDelete()
    expect(store.monitors.length).toBe(2)
    expect(monitorsApi.bulkAction).not.toHaveBeenCalled()
  })

  it('optimistically removes selected monitors and shows an Undo toast, without calling the API yet', async () => {
    confirmMock.mockResolvedValue(true)
    const { store, sel } = setup([makeMonitor('1', 'a'), makeMonitor('2', 'b'), makeMonitor('3', 'c')])
    sel.selectedIds.value = new Set(['2'])
    await sel.confirmBulkDelete()

    expect(store.monitors.map(m => m.id)).toEqual(['1', '3'])
    expect(monitorsApi.bulkAction).not.toHaveBeenCalled()

    const { toasts } = useToast()
    expect(toasts.length).toBe(1)
    expect(toasts[0].action.label).toBe('common.undo')
  })

  it('clicking Undo restores the monitor and never calls the delete API, even after the window elapses', async () => {
    confirmMock.mockResolvedValue(true)
    const { store, sel } = setup([makeMonitor('1', 'a'), makeMonitor('2', 'b')])
    sel.selectedIds.value = new Set(['1'])
    await sel.confirmBulkDelete()

    const { toasts } = useToast()
    expect(toasts.length).toBe(1)
    toasts[0].action.run()

    expect(store.monitors.map(m => m.id).sort()).toEqual(['1', '2'])

    vi.advanceTimersByTime(10000)
    expect(monitorsApi.bulkAction).not.toHaveBeenCalled()
  })

  it('letting the toast expire fires the deferred delete call with the selected ids', async () => {
    confirmMock.mockResolvedValue(true)
    const { sel } = setup([makeMonitor('1', 'a'), makeMonitor('2', 'b')])
    sel.selectedIds.value = new Set(['1'])
    await sel.confirmBulkDelete()

    expect(monitorsApi.bulkAction).not.toHaveBeenCalled()
    await vi.advanceTimersByTimeAsync(6000)

    expect(monitorsApi.bulkAction).toHaveBeenCalledTimes(1)
    expect(monitorsApi.bulkAction).toHaveBeenCalledWith(
      { ids: ['1'], action: 'delete' },
      { skipErrorToast: true },
    )
    // A refresh from the server is triggered after the deferred delete settles.
    expect(monitorsApi.list).toHaveBeenCalled()
  })

  // ── Review M1 — interleaved fetchAll during the undo window ──────────────
  // A fetchAll (Dashboard navigation, Monitors re-mount…) fired inside the 6s
  // window used to resurrect the optimistically-removed monitors; clicking
  // Undo then re-spliced them → duplicated ids (Vue :key warnings, double rows).

  it('fetchAll during the undo window does not resurrect pending-delete monitors', async () => {
    confirmMock.mockResolvedValue(true)
    const { store, sel } = setup([makeMonitor('1', 'a'), makeMonitor('2', 'b')])
    sel.selectedIds.value = new Set(['1'])
    await sel.confirmBulkDelete()
    expect(store.monitors.map(m => m.id)).toEqual(['2'])

    // The deferred delete has not fired yet — the server still returns '1'.
    monitorsApi.list.mockResolvedValue({ data: [makeMonitor('1', 'a'), makeMonitor('2', 'b')] })
    await store.fetchAll()

    expect(store.monitors.map(m => m.id)).toEqual(['2'])
  })

  it('clicking Undo after the monitor reappeared in the store does not duplicate it', async () => {
    confirmMock.mockResolvedValue(true)
    const { store, sel } = setup([makeMonitor('1', 'a'), makeMonitor('2', 'b')])
    sel.selectedIds.value = new Set(['1'])
    await sel.confirmBulkDelete()

    // Simulate any path that brings the monitor back mid-window (a refresh
    // that bypassed the registry, a WS-driven repopulation…).
    store.monitors = [makeMonitor('1', 'a'), makeMonitor('2', 'b')]

    const { toasts } = useToast()
    toasts[0].action.run()

    const ids = store.monitors.map(m => m.id)
    expect(new Set(ids).size).toBe(ids.length) // no duplicated :key ids
    expect([...ids].sort()).toEqual(['1', '2'])
  })

  it('Undo releases the registry — a later fetchAll includes the restored monitor again', async () => {
    confirmMock.mockResolvedValue(true)
    const { store, sel } = setup([makeMonitor('1', 'a'), makeMonitor('2', 'b')])
    sel.selectedIds.value = new Set(['1'])
    await sel.confirmBulkDelete()

    const { toasts } = useToast()
    toasts[0].action.run()

    monitorsApi.list.mockResolvedValue({ data: [makeMonitor('1', 'a'), makeMonitor('2', 'b')] })
    await store.fetchAll()
    expect(store.monitors.map(m => m.id).sort()).toEqual(['1', '2'])
  })

  it('expiry releases the registry before the post-delete refresh (server state wins)', async () => {
    confirmMock.mockResolvedValue(true)
    const { store, sel } = setup([makeMonitor('1', 'a'), makeMonitor('2', 'b')])
    sel.selectedIds.value = new Set(['1'])
    await sel.confirmBulkDelete()

    // If the server still returns the id after the window (failed delete,
    // recreation…), the refresh must show it — the registry no longer hides it.
    monitorsApi.list.mockResolvedValue({ data: [makeMonitor('1', 'a'), makeMonitor('2', 'b')] })
    await vi.advanceTimersByTimeAsync(6000)
    await Promise.resolve()
    await Promise.resolve()

    expect(monitorsApi.bulkAction).toHaveBeenCalledTimes(1)
    expect(store.monitors.map(m => m.id).sort()).toEqual(['1', '2'])
  })
})
