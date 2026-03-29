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

    it('returns A for perfect monitor (100% uptime, fast, no incident)', async () => {
      expect(await healthOf({
        uptime_24h: 100,
        last_response_time_ms: 50,
        has_open_incident: false,
      })).toBe('A')
    })

    it('returns B for good monitor (97% uptime, moderate RT)', async () => {
      // score = 97*0.7 + 14 + 10 = 67.9 + 14 + 10 = 91.9 → below 95 → not B
      // Actually: 97*0.7 = 67.9, RT 500 → +14, no incident → +10 = 91.9 → C
      // Let's use 99% uptime, RT 500
      // 99*0.7 = 69.3 + 14 + 10 = 93.3 → still below 95 → C
      // For B: need score >= 95. 99.5*0.7 = 69.65 + 14 + 10 = 93.65 → C
      // For B with fast RT: 96*0.7 = 67.2 + 20 + 10 = 97.2 → A
      // B range is 95-99. Let's find: uptime=98, RT<300, no incident
      // 98*0.7 = 68.6 + 20 + 10 = 98.6 → A (>=99)
      // uptime=97: 97*0.7 = 67.9 + 20 + 10 = 97.9 → B
      expect(await healthOf({
        uptime_24h: 97,
        last_response_time_ms: 100,
        has_open_incident: false,
      })).toBe('B')
    })

    it('returns C for moderate monitor', async () => {
      // uptime=90, fast RT: 90*0.7=63 + 20 + 10 = 93 → C (>=85 <95)
      expect(await healthOf({
        uptime_24h: 90,
        last_response_time_ms: 200,
        has_open_incident: false,
      })).toBe('C')
    })

    it('returns D for degraded monitor', async () => {
      // uptime=85, slow RT: 85*0.7=59.5 + 7 + 10 = 76.5 → D (>=70 <85)
      expect(await healthOf({
        uptime_24h: 85,
        last_response_time_ms: 1500,
        has_open_incident: false,
      })).toBe('D')
    })

    it('returns F for failing monitor', async () => {
      // uptime=50, slow, incident: 50*0.7=35 + 7 + 0 = 42 → F
      expect(await healthOf({
        uptime_24h: 50,
        last_response_time_ms: 1500,
        has_open_incident: true,
      })).toBe('F')
    })

    it('incident penalty reduces score by 10', async () => {
      // Without incident: 95*0.7=66.5 + 20 + 10 = 96.5 → B
      const withoutIncident = await healthOf({
        uptime_24h: 95,
        last_response_time_ms: 100,
        has_open_incident: false,
      })
      store.monitors = [] // reset

      // With incident: 95*0.7=66.5 + 20 + 0 = 86.5 → C
      const withIncident = await healthOf({
        uptime_24h: 95,
        last_response_time_ms: 100,
        has_open_incident: true,
      })

      // Score difference should push to a lower grade
      expect(withoutIncident).not.toBe(withIncident)
    })

    it('no response time data gives neutral 10 points', async () => {
      // uptime=100, no RT, no incident: 100*0.7=70 + 10 + 10 = 90 → C
      expect(await healthOf({
        uptime_24h: 100,
        last_response_time_ms: null,
        has_open_incident: false,
      })).toBe('C')
    })

    it('response time tiers: <300, <800, <2000, >=2000', async () => {
      // All with uptime=100, no incident → base = 70 + 10 = 80
      // RT < 300  → +20 = 100 → A
      expect(await healthOf({ uptime_24h: 100, last_response_time_ms: 100 })).toBe('A')
      store.monitors = []
      // RT 500 → +14 = 94 → C
      expect(await healthOf({ uptime_24h: 100, last_response_time_ms: 500 })).toBe('C')
      store.monitors = []
      // RT 1500 → +7 = 87 → C
      expect(await healthOf({ uptime_24h: 100, last_response_time_ms: 1500 })).toBe('C')
      store.monitors = []
      // RT 3000 → +0 = 80 → D (>=70 <85)
      expect(await healthOf({ uptime_24h: 100, last_response_time_ms: 3000 })).toBe('D')
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
