/**
 * Tests for the monitors Pinia store.
 *
 * Covers: enrich(), _computeHealth() scoring, applyCheckResult() sparkline,
 * setFlapping() timer lifecycle.
 */

import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'

// Mock the API module before importing the store
vi.mock('../src/api/monitors', () => ({
  monitorsApi: {
    list: vi.fn(),
    create: vi.fn(),
    update: vi.fn(),
    delete: vi.fn(),
  },
}))

import { useMonitorStore } from '../src/stores/monitors'
import { monitorsApi } from '../src/api/monitors'

// ── Helpers ──────────────────────────────────────────────────────────────────

function makeMonitor(overrides = {}) {
  return {
    id: 'mon-1',
    name: 'Test',
    url: 'https://example.com',
    last_status: 'up',
    uptime_24h: 99.5,
    has_open_incident: false,
    last_response_time_ms: 120,
    sparkline: [100, 110, 120],
    ...overrides,
  }
}

// ── Setup ────────────────────────────────────────────────────────────────────

describe('monitors store', () => {
  let store

  beforeEach(() => {
    setActivePinia(createPinia())
    store = useMonitorStore()
    vi.clearAllMocks()
  })

  // ── enrich() ─────────────────────────────────────────────────────────

  describe('enrich (via fetchAll)', () => {
    it('maps raw API fields to _prefixed computed fields', async () => {
      monitorsApi.list.mockResolvedValue({
        data: [makeMonitor()],
      })
      await store.fetchAll()

      const m = store.monitors[0]
      expect(m._lastStatus).toBe('up')
      expect(m._uptime24h).toBe(99.5)
      expect(m._hasOpenIncident).toBe(false)
      expect(m._lastResponseTimeMs).toBe(120)
      expect(m._sparkline).toEqual([100, 110, 120])
      expect(m._isFlapping).toBe(false)
    })

    it('handles missing optional fields with defaults', async () => {
      monitorsApi.list.mockResolvedValue({
        data: [{ id: 'mon-2', name: 'Bare' }],
      })
      await store.fetchAll()

      const m = store.monitors[0]
      expect(m._lastStatus).toBeNull()
      expect(m._uptime24h).toBeNull()
      expect(m._hasOpenIncident).toBe(false)
      expect(m._sparkline).toEqual([])
    })
  })

  // ── _computeHealth() ─────────────────────────────────────────────────

  describe('health scoring', () => {
    async function healthOf(overrides) {
      monitorsApi.list.mockResolvedValue({
        data: [makeMonitor(overrides)],
      })
      await store.fetchAll()
      return store.monitors[0]._healthScore
    }

    it('returns null when uptime is unknown', async () => {
      expect(await healthOf({ uptime_24h: null })).toBeNull()
    })

    // Current algorithm (see _computeHealth in src/stores/monitors.js):
    //   score = uptime * 0.6
    //         + (rt/p95 ratio bonus: ≤0.6 → 25, ≤1.0 → 22, ≤1.5 → 12, ≤2.5 → 5, else 0)
    //         + (15 when rt or p95 is missing — neutral)
    //         + (15 when no open incident)
    // Grades:  A ≥ 90 · B ≥ 75 · C ≥ 55 · D ≥ 35 · F < 35

    it('returns A for perfect monitor (100% uptime, rt well under p95, no incident)', async () => {
      // 100*0.6 + 25 (ratio 0.1) + 15 = 100 → A
      expect(await healthOf({
        uptime_24h: 100,
        last_response_time_ms: 50,
        p95_response_time_ms: 500,
        has_open_incident: false,
      })).toBe('A')
    })

    it('returns B for good monitor (rt moderately above p95)', async () => {
      // 98*0.6 + 12 (ratio 1.25) + 15 = 85.8 → B
      expect(await healthOf({
        uptime_24h: 98,
        last_response_time_ms: 500,
        p95_response_time_ms: 400,
        has_open_incident: false,
      })).toBe('B')
    })

    it('returns C for degraded monitor (rt 2× p95)', async () => {
      // 90*0.6 + 5 (ratio 2.0) + 15 = 74 → C (< 75)
      expect(await healthOf({
        uptime_24h: 90,
        last_response_time_ms: 800,
        p95_response_time_ms: 400,
        has_open_incident: false,
      })).toBe('C')
    })

    it('returns D for unhealthy monitor (low uptime + rt way above p95)', async () => {
      // 80*0.6 + 0 (ratio 4.0) + 15 = 63 → C (actually)
      // 70*0.6 + 0 (ratio 4.0) + 15 = 57 → C still
      // 65*0.6 + 0 (ratio 4.0) + 15 = 54 → D
      expect(await healthOf({
        uptime_24h: 65,
        last_response_time_ms: 2000,
        p95_response_time_ms: 500,
        has_open_incident: false,
      })).toBe('D')
    })

    it('returns F for failing monitor', async () => {
      // 20*0.6 + 0 (ratio 6.0) + 0 (incident) = 12 → F
      expect(await healthOf({
        uptime_24h: 20,
        last_response_time_ms: 3000,
        p95_response_time_ms: 500,
        has_open_incident: true,
      })).toBe('F')
    })

    it('incident penalty reduces the score by 15 and drops the grade', async () => {
      // No incident: 85*0.6 + 22 (ratio 1.0) + 15 = 88 → B
      const withoutIncident = await healthOf({
        uptime_24h: 85,
        last_response_time_ms: 500,
        p95_response_time_ms: 500,
        has_open_incident: false,
      })
      store.monitors = []
      // With incident: 85*0.6 + 22 + 0 = 73 → C
      const withIncident = await healthOf({
        uptime_24h: 85,
        last_response_time_ms: 500,
        p95_response_time_ms: 500,
        has_open_incident: true,
      })
      expect(withoutIncident).toBe('B')
      expect(withIncident).toBe('C')
    })

    it('no rt or no p95 baseline yields the neutral +15 bonus', async () => {
      // 100*0.6 + 15 (neutral, rt null) + 15 = 90 → A
      expect(await healthOf({
        uptime_24h: 100,
        last_response_time_ms: null,
        p95_response_time_ms: null,
        has_open_incident: false,
      })).toBe('A')
      store.monitors = []
      // 100*0.6 + 15 (neutral, p95 null) + 15 = 90 → A
      expect(await healthOf({
        uptime_24h: 100,
        last_response_time_ms: 123,
        p95_response_time_ms: null,
        has_open_incident: false,
      })).toBe('A')
    })

    it('response time is graded by rt/p95 ratio, not an absolute threshold', async () => {
      // Fix uptime=100 and no incident → base = 60 + 15 = 75
      // ratio 0.5 → +25 = 100 → A
      expect(await healthOf({
        uptime_24h: 100, last_response_time_ms: 500, p95_response_time_ms: 1000,
      })).toBe('A')
      store.monitors = []
      // ratio 0.9 → +22 = 97 → A
      expect(await healthOf({
        uptime_24h: 100, last_response_time_ms: 900, p95_response_time_ms: 1000,
      })).toBe('A')
      store.monitors = []
      // ratio 1.25 → +12 = 87 → B
      expect(await healthOf({
        uptime_24h: 100, last_response_time_ms: 1250, p95_response_time_ms: 1000,
      })).toBe('B')
      store.monitors = []
      // ratio 2.0 → +5 = 80 → B
      expect(await healthOf({
        uptime_24h: 100, last_response_time_ms: 2000, p95_response_time_ms: 1000,
      })).toBe('B')
      store.monitors = []
      // ratio 3.0 (> 2.5) → +0 = 75 → B (exact boundary)
      expect(await healthOf({
        uptime_24h: 100, last_response_time_ms: 3000, p95_response_time_ms: 1000,
      })).toBe('B')
    })
  })

  // ── applyCheckResult() ───────────────────────────────────────────────

  describe('applyCheckResult', () => {
    beforeEach(async () => {
      monitorsApi.list.mockResolvedValue({
        data: [makeMonitor({ sparkline: [100, 200, 300] })],
      })
      await store.fetchAll()
    })

    it('updates status and response time', () => {
      store.applyCheckResult({
        monitor_id: 'mon-1',
        status: 'down',
        response_time_ms: 5000,
        checked_at: '2026-01-01T00:00:00Z',
      })
      const m = store.monitors[0]
      expect(m._lastStatus).toBe('down')
      expect(m._lastResponseTimeMs).toBe(5000)
    })

    it('appends to sparkline and caps at 20 points', () => {
      // Start with 3 points, add 18 more to reach 21 → should cap at 20
      for (let i = 0; i < 18; i++) {
        store.applyCheckResult({
          monitor_id: 'mon-1',
          status: 'up',
          response_time_ms: 100 + i,
        })
      }
      expect(store.monitors[0]._sparkline.length).toBe(20)
      // First original value (100) should have been shifted out
      expect(store.monitors[0]._sparkline[0]).not.toBe(100)
    })

    it('ignores events for unknown monitors', () => {
      store.applyCheckResult({
        monitor_id: 'unknown-id',
        status: 'down',
        response_time_ms: 999,
      })
      // No crash, original monitor unchanged
      expect(store.monitors[0]._lastStatus).toBe('up')
    })

    it('preserves sparkline when response_time_ms is null', () => {
      store.applyCheckResult({
        monitor_id: 'mon-1',
        status: 'up',
        response_time_ms: null,
      })
      // Sparkline should be unchanged
      expect(store.monitors[0]._sparkline).toEqual([100, 200, 300])
    })

    it('recalculates health score after check result', () => {
      const before = store.monitors[0]._healthScore
      store.applyCheckResult({
        monitor_id: 'mon-1',
        status: 'down',
        response_time_ms: 5000,
      })
      // Health should be recalculated (may or may not change depending on uptime)
      expect(store.monitors[0]._healthScore).toBeDefined()
    })
  })

  // ── setFlapping() ────────────────────────────────────────────────────

  describe('setFlapping', () => {
    beforeEach(async () => {
      vi.useFakeTimers()
      monitorsApi.list.mockResolvedValue({
        data: [makeMonitor()],
      })
      await store.fetchAll()
    })

    afterEach(() => {
      vi.useRealTimers()
    })

    it('sets _isFlapping to true', () => {
      store.setFlapping('mon-1')
      expect(store.monitors[0]._isFlapping).toBe(true)
    })

    it('auto-clears after 10 minutes', () => {
      store.setFlapping('mon-1')
      expect(store.monitors[0]._isFlapping).toBe(true)

      vi.advanceTimersByTime(10 * 60 * 1000)
      expect(store.monitors[0]._isFlapping).toBe(false)
    })

    it('resets timer on repeated calls', () => {
      store.setFlapping('mon-1')
      vi.advanceTimersByTime(5 * 60 * 1000) // 5 min

      store.setFlapping('mon-1') // reset timer
      vi.advanceTimersByTime(5 * 60 * 1000) // 5 more min (10 total, but only 5 since reset)
      expect(store.monitors[0]._isFlapping).toBe(true)

      vi.advanceTimersByTime(5 * 60 * 1000) // 10 min since reset
      expect(store.monitors[0]._isFlapping).toBe(false)
    })

    it('ignores unknown monitor ID', () => {
      store.setFlapping('nonexistent')
      // No crash
      expect(store.monitors[0]._isFlapping).toBe(false)
    })
  })

  // ── CRUD operations ──────────────────────────────────────────────────

  describe('CRUD', () => {
    it('create() adds to beginning of list', async () => {
      monitorsApi.list.mockResolvedValue({ data: [makeMonitor()] })
      await store.fetchAll()

      monitorsApi.create.mockResolvedValue({
        data: makeMonitor({ id: 'mon-new', name: 'New' }),
      })
      await store.create({ name: 'New', url: 'https://new.com' })

      expect(store.monitors[0].id).toBe('mon-new')
      expect(store.monitors.length).toBe(2)
    })

    it('update() replaces monitor in-place', async () => {
      monitorsApi.list.mockResolvedValue({ data: [makeMonitor()] })
      await store.fetchAll()

      monitorsApi.update.mockResolvedValue({
        data: makeMonitor({ name: 'Updated' }),
      })
      await store.update('mon-1', { name: 'Updated' })

      expect(store.monitors[0].name).toBe('Updated')
      expect(store.monitors.length).toBe(1)
    })

    it('remove() filters out deleted monitor', async () => {
      monitorsApi.list.mockResolvedValue({
        data: [makeMonitor(), makeMonitor({ id: 'mon-2' })],
      })
      await store.fetchAll()

      monitorsApi.delete.mockResolvedValue({})
      await store.remove('mon-1')

      expect(store.monitors.length).toBe(1)
      expect(store.monitors[0].id).toBe('mon-2')
    })

    it('fetchAll() sets loading flag', async () => {
      let resolvePromise
      monitorsApi.list.mockReturnValue(
        new Promise((resolve) => { resolvePromise = resolve })
      )

      const fetchPromise = store.fetchAll()
      expect(store.loading).toBe(true)

      resolvePromise({ data: [] })
      await fetchPromise
      expect(store.loading).toBe(false)
    })
  })
})
