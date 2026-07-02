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

import { useMonitorStore } from '../src/stores/monitors'
import { monitorsApi } from '../src/api/monitors'
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
})
