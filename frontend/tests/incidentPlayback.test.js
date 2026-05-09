import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { nextTick } from 'vue'

const apiGet = vi.fn()
vi.mock('../src/api/client', () => ({
  default: { get: (...a) => apiGet(...a) },
}))

import { useIncidentPlayback } from '../src/composables/useIncidentPlayback'

const ts = (s) => new Date(`2026-05-10T10:${String(s).padStart(2, '0')}:00Z`).toISOString()

const fixture = {
  incident_id: 'inc-1',
  points: [
    { checked_at: ts(0), probe_id: 'p1', status: 'up' },
    { checked_at: ts(1), probe_id: 'p2', status: 'up' },
    { checked_at: ts(2), probe_id: 'p1', status: 'down' },
    { checked_at: ts(3), probe_id: 'p2', status: 'down' },
    { checked_at: ts(4), probe_id: 'p1', status: 'up' },
  ],
}

beforeEach(() => {
  apiGet.mockReset()
  vi.useFakeTimers()
})

afterEach(() => {
  vi.useRealTimers()
})

describe('useIncidentPlayback', () => {
  it('starts in a clean state before load()', () => {
    const pb = useIncidentPlayback('inc-1')
    expect(pb.loading.value).toBe(false)
    expect(pb.timeline.value).toBe(null)
    expect(pb.cursorMs.value).toBe(0)
    expect(pb.playing.value).toBe(false)
    expect(pb.durationMs.value).toBe(0)
    expect(pb.cursorAt.value).toBe(null)
    expect(pb.stateAtCursor.value.size).toBe(0)
  })

  it('load() pulls the timeline and computes the duration span', async () => {
    apiGet.mockResolvedValueOnce({ data: fixture })
    const pb = useIncidentPlayback('inc-1')
    await pb.load()

    expect(apiGet).toHaveBeenCalledWith('/incidents/inc-1/timeline')
    expect(pb.timeline.value).toBe(fixture)
    expect(pb.durationMs.value).toBe(4 * 60 * 1000)  // 4 minutes between first and last point
  })

  it('stateAtCursor returns only the points up to the cursor (latest per probe)', async () => {
    apiGet.mockResolvedValueOnce({ data: fixture })
    const pb = useIncidentPlayback('inc-1')
    await pb.load()

    // cursor at 0 → only the first point (p1 up)
    expect(pb.stateAtCursor.value.size).toBe(1)
    expect(pb.stateAtCursor.value.get('p1').status).toBe('up')

    // cursor at +2 min → p1 should be 'down' (latest sample), p2 'up'
    pb.seek(2 * 60 * 1000)
    expect(pb.stateAtCursor.value.get('p1').status).toBe('down')
    expect(pb.stateAtCursor.value.get('p2').status).toBe('up')

    // cursor at +4 min → p1 'up' again, p2 'down'
    pb.seek(4 * 60 * 1000)
    expect(pb.stateAtCursor.value.get('p1').status).toBe('up')
    expect(pb.stateAtCursor.value.get('p2').status).toBe('down')
  })

  it('seek clamps the cursor to [0, durationMs]', async () => {
    apiGet.mockResolvedValueOnce({ data: fixture })
    const pb = useIncidentPlayback('inc-1')
    await pb.load()

    pb.seek(-5000)
    expect(pb.cursorMs.value).toBe(0)

    pb.seek(99999999)
    expect(pb.cursorMs.value).toBe(pb.durationMs.value)
  })

  it('play() advances the cursor over time and pauses at the end', async () => {
    apiGet.mockResolvedValueOnce({ data: fixture })
    const pb = useIncidentPlayback('inc-1')
    await pb.load()

    pb.play()
    expect(pb.playing.value).toBe(true)

    // covers full duration in 30 ticks of 100ms each
    vi.advanceTimersByTime(3500)
    expect(pb.playing.value).toBe(false)
    expect(pb.cursorMs.value).toBe(pb.durationMs.value)
  })

  it('play() is idempotent — calling twice does not double the speed', async () => {
    apiGet.mockResolvedValueOnce({ data: fixture })
    const pb = useIncidentPlayback('inc-1')
    await pb.load()

    pb.play()
    const stepCursor = pb.durationMs.value / 30
    pb.play()  // second call should be a no-op

    vi.advanceTimersByTime(100)
    expect(pb.cursorMs.value).toBeCloseTo(stepCursor, 0)
  })

  it('pause() stops the play loop', async () => {
    apiGet.mockResolvedValueOnce({ data: fixture })
    const pb = useIncidentPlayback('inc-1')
    await pb.load()

    pb.play()
    vi.advanceTimersByTime(200)
    const cursorAtPause = pb.cursorMs.value
    pb.pause()
    vi.advanceTimersByTime(1000)
    expect(pb.cursorMs.value).toBe(cursorAtPause)
    expect(pb.playing.value).toBe(false)
  })

  it('reset() pauses + sends the cursor back to 0', async () => {
    apiGet.mockResolvedValueOnce({ data: fixture })
    const pb = useIncidentPlayback('inc-1')
    await pb.load()

    pb.seek(pb.durationMs.value)
    pb.play()
    pb.reset()
    expect(pb.cursorMs.value).toBe(0)
    expect(pb.playing.value).toBe(false)
  })

  it('load() sets error and clears timeline when API fails', async () => {
    apiGet.mockRejectedValueOnce({ response: { data: { detail: 'gone' } } })
    const pb = useIncidentPlayback('inc-1')
    await pb.load()

    expect(pb.error.value).toBe('gone')
    expect(pb.timeline.value).toBe(null)
    expect(pb.loading.value).toBe(false)
  })

  it('handles an empty timeline gracefully (durationMs=0, no crash on play)', async () => {
    apiGet.mockResolvedValueOnce({ data: { incident_id: 'inc-1', points: [] } })
    const pb = useIncidentPlayback('inc-1')
    await pb.load()

    expect(pb.durationMs.value).toBe(0)
    pb.play()
    expect(pb.playing.value).toBe(false)  // refused to start
  })
})
