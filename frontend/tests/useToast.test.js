/**
 * Tests for the toast dedup behaviour in composables/useToast.js.
 *
 * Repeated failures (e.g. a polling loop that keeps hitting the same error)
 * must not stack duplicate toasts — a second call with the same message
 * (and type) should just refresh the existing toast's auto-dismiss timer
 * instead of pushing a new entry.
 */

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { useToast } from '../src/composables/useToast'

describe('composables/useToast — dedup', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    // Drain any toasts left over from a previous test.
    const { toasts, remove } = useToast()
    for (const t of [...toasts]) remove(t.id)
  })

  afterEach(() => {
    vi.clearAllTimers()
    vi.useRealTimers()
  })

  it('does not stack a second toast with the same message and type', () => {
    const { toasts, error } = useToast()
    error('Network error')
    error('Network error')
    expect(toasts.length).toBe(1)
  })

  it('stacks toasts with different messages', () => {
    const { toasts, error } = useToast()
    error('Network error')
    error('Server error')
    expect(toasts.length).toBe(2)
  })

  it('stacks toasts with the same message but a different type', () => {
    const { toasts, error, success } = useToast()
    error('Done')
    success('Done')
    expect(toasts.length).toBe(2)
  })

  it('refreshes the timer instead of stacking — toast survives past the original duration', () => {
    const { toasts, error } = useToast()
    error('Network error')
    vi.advanceTimersByTime(4000)
    // Re-trigger before the first 5s timeout would have fired — this should
    // reset the clock rather than adding a new entry.
    error('Network error')
    vi.advanceTimersByTime(4000)
    // 8s of elapsed time > the 5s error duration, but since the timer was
    // refreshed at the 4s mark the toast should still be visible.
    expect(toasts.length).toBe(1)
  })

  it('eventually auto-dismisses after the refreshed duration elapses', () => {
    const { toasts, error } = useToast()
    error('Network error')
    vi.advanceTimersByTime(5000)
    expect(toasts.length).toBe(0)
  })

  it('allows a new toast with the same message once the previous one is dismissed', () => {
    const { toasts, error, remove } = useToast()
    error('Network error')
    remove(toasts[0].id)
    error('Network error')
    expect(toasts.length).toBe(1)
  })
})
