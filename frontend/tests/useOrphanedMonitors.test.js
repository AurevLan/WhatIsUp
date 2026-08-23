/**
 * useOrphanedMonitors (plan D, D-3) — the one extra call MonitorsView and
 * MonitorDetailView make to badge monitors whose discovered target
 * disappeared. Load-bearing rule from the plan: a user without discovery
 * access, or a network hiccup, must yield zero badges and never throw.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('../src/api/discovery', () => ({
  discoveryApi: {
    services: { list: vi.fn() },
  },
}))

import { discoveryApi } from '../src/api/discovery'
import { useOrphanedMonitors } from '../src/composables/useOrphanedMonitors'

describe('useOrphanedMonitors', () => {
  beforeEach(() => vi.clearAllMocks())

  it('starts with an empty set', () => {
    const { isOrphaned } = useOrphanedMonitors()
    expect(isOrphaned('mon-1')).toBe(false)
  })

  it('populates from monitor_id of the orphaned services returned', async () => {
    discoveryApi.services.list.mockResolvedValue({
      data: [
        { id: 'svc-1', monitor_id: 'mon-1' },
        { id: 'svc-2', monitor_id: 'mon-2' },
      ],
    })
    const { isOrphaned, loadOrphanedMonitors } = useOrphanedMonitors()
    await loadOrphanedMonitors()

    expect(isOrphaned('mon-1')).toBe(true)
    expect(isOrphaned('mon-2')).toBe(true)
    expect(isOrphaned('mon-3')).toBe(false)
    expect(discoveryApi.services.list).toHaveBeenCalledWith(
      { status: 'orphaned' },
      { skipErrorToast: true }
    )
  })

  it('filters out rows with no monitor_id', async () => {
    discoveryApi.services.list.mockResolvedValue({
      data: [{ id: 'svc-1', monitor_id: null }],
    })
    const { orphanedMonitorIds, loadOrphanedMonitors } = useOrphanedMonitors()
    await loadOrphanedMonitors()
    expect(orphanedMonitorIds.value.size).toBe(0)
  })

  it('collapses to an empty set on failure — no badges, no crash', async () => {
    discoveryApi.services.list.mockRejectedValue(new Error('403'))
    const { isOrphaned, loadOrphanedMonitors } = useOrphanedMonitors()
    await expect(loadOrphanedMonitors()).resolves.toBeUndefined()
    expect(isOrphaned('mon-1')).toBe(false)
  })
})
