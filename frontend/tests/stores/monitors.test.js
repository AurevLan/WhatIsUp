import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'

const apiList = vi.fn()
const apiCreate = vi.fn()
const apiUpdate = vi.fn()
const apiDelete = vi.fn()

vi.mock('../../src/api/monitors', () => ({
  monitorsApi: {
    list: (...a) => apiList(...a),
    create: (...a) => apiCreate(...a),
    update: (...a) => apiUpdate(...a),
    delete: (...a) => apiDelete(...a),
  },
}))

import { useMonitorStore } from '../../src/stores/monitors'

const fixture = (overrides = {}) => ({
  id: 'mon-1',
  name: 'example.com',
  url: 'https://example.com',
  last_status: 'up',
  uptime_24h: 99.5,
  has_open_incident: false,
  last_response_time_ms: 120,
  p95_response_time_ms: 200,
  sparkline: [110, 115, 120],
  ...overrides,
})

beforeEach(() => {
  setActivePinia(createPinia())
  apiList.mockReset()
  apiCreate.mockReset()
  apiUpdate.mockReset()
  apiDelete.mockReset()
  vi.useFakeTimers()
})

afterEach(() => {
  vi.useRealTimers()
})

describe('monitors store', () => {
  it('fetchAll loads + enriches monitors with the _* mirror fields', async () => {
    apiList.mockResolvedValueOnce({ data: [fixture()] })
    const store = useMonitorStore()
    await store.fetchAll()

    expect(store.monitors.length).toBe(1)
    const m = store.monitors[0]
    expect(m._lastStatus).toBe('up')
    expect(m._uptime24h).toBe(99.5)
    expect(m._hasOpenIncident).toBe(false)
    expect(m._sparkline).toEqual([110, 115, 120])
    expect(m._isFlapping).toBe(false)
    expect(['A', 'B', 'C', 'D', 'F']).toContain(m._healthScore)
  })

  it('healthScore is null when uptime is unknown', async () => {
    apiList.mockResolvedValueOnce({ data: [fixture({ uptime_24h: null })] })
    const store = useMonitorStore()
    await store.fetchAll()
    expect(store.monitors[0]._healthScore).toBe(null)
  })

  it('healthScore degrades when response time blows past p95', async () => {
    apiList.mockResolvedValueOnce({
      data: [fixture({ last_response_time_ms: 800, p95_response_time_ms: 200 })],
    })
    const store = useMonitorStore()
    await store.fetchAll()
    // 99.5 * 0.6 = 59.7 + 0 (rt 4x p95) + 15 (no incident) = ~74.7 → C or D
    expect(['C', 'D']).toContain(store.monitors[0]._healthScore)
  })

  it('create unshifts the new monitor at the head', async () => {
    apiList.mockResolvedValueOnce({ data: [fixture({ id: 'mon-existing' })] })
    apiCreate.mockResolvedValueOnce({ data: fixture({ id: 'mon-new', name: 'new.example' }) })

    const store = useMonitorStore()
    await store.fetchAll()
    await store.create({ name: 'new.example' })

    expect(store.monitors.length).toBe(2)
    expect(store.monitors[0].id).toBe('mon-new')
  })

  it('update replaces the matching monitor in-place', async () => {
    apiList.mockResolvedValueOnce({ data: [fixture()] })
    apiUpdate.mockResolvedValueOnce({ data: fixture({ name: 'renamed.example', uptime_24h: 100 }) })

    const store = useMonitorStore()
    await store.fetchAll()
    await store.update('mon-1', { name: 'renamed.example' })

    expect(store.monitors.length).toBe(1)
    expect(store.monitors[0].name).toBe('renamed.example')
    expect(store.monitors[0]._uptime24h).toBe(100)
  })

  it('update is a no-op when the id is not in the list', async () => {
    apiList.mockResolvedValueOnce({ data: [fixture()] })
    apiUpdate.mockResolvedValueOnce({ data: fixture({ id: 'unknown' }) })

    const store = useMonitorStore()
    await store.fetchAll()
    await store.update('unknown', { name: 'x' })

    expect(store.monitors.length).toBe(1)
    expect(store.monitors[0].id).toBe('mon-1')
  })

  it('remove drops the monitor from the list', async () => {
    apiList.mockResolvedValueOnce({ data: [fixture(), fixture({ id: 'mon-2' })] })
    apiDelete.mockResolvedValueOnce({ data: {} })

    const store = useMonitorStore()
    await store.fetchAll()
    await store.remove('mon-1')

    expect(store.monitors.length).toBe(1)
    expect(store.monitors[0].id).toBe('mon-2')
  })

  it('applyCheckResult updates status, RT, sparkline (capped at 20), and flashes on change', async () => {
    apiList.mockResolvedValueOnce({ data: [fixture({ sparkline: Array(19).fill(100) })] })
    const store = useMonitorStore()
    await store.fetchAll()

    store.applyCheckResult({
      monitor_id: 'mon-1',
      status: 'down',
      response_time_ms: 250,
      checked_at: '2026-05-09T22:00:00Z',
    })

    const m = store.monitors[0]
    expect(m._lastStatus).toBe('down')
    expect(m._lastResponseTimeMs).toBe(250)
    expect(m._wsFlash).toBe('down')
    expect(m._sparkline.length).toBe(20)
    expect(m._sparkline[m._sparkline.length - 1]).toBe(250)

    // flash auto-clears after 1600ms
    vi.advanceTimersByTime(1700)
    expect(m._wsFlash).toBe(null)
  })

  it('applyCheckResult sparkline cap drops oldest entry past 20', async () => {
    apiList.mockResolvedValueOnce({ data: [fixture({ sparkline: Array(20).fill(100).map((_, i) => i) })] })
    const store = useMonitorStore()
    await store.fetchAll()

    store.applyCheckResult({ monitor_id: 'mon-1', status: 'up', response_time_ms: 999 })

    const m = store.monitors[0]
    expect(m._sparkline.length).toBe(20)
    expect(m._sparkline[0]).toBe(1)              // index 0 dropped, was 0
    expect(m._sparkline[m._sparkline.length - 1]).toBe(999)
  })

  it('applyCheckResult silently ignores events for unknown monitor ids', async () => {
    apiList.mockResolvedValueOnce({ data: [fixture()] })
    const store = useMonitorStore()
    await store.fetchAll()

    expect(() =>
      store.applyCheckResult({ monitor_id: 'ghost', status: 'down' })
    ).not.toThrow()
  })

  it('setFlapping flips the flag and auto-clears after 10 minutes', async () => {
    apiList.mockResolvedValueOnce({ data: [fixture()] })
    const store = useMonitorStore()
    await store.fetchAll()

    store.setFlapping('mon-1')
    expect(store.monitors[0]._isFlapping).toBe(true)

    vi.advanceTimersByTime(10 * 60 * 1000 + 1000)
    expect(store.monitors[0]._isFlapping).toBe(false)
  })

  it('setFlapping is a no-op for unknown monitor ids', async () => {
    apiList.mockResolvedValueOnce({ data: [fixture()] })
    const store = useMonitorStore()
    await store.fetchAll()
    expect(() => store.setFlapping('ghost')).not.toThrow()
  })
})
