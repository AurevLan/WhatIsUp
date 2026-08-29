/**
 * usePendingDiscoveryCount (plan E, E-3) — nav badge counter: fetches on
 * mount, polls while mounted, collapses any failure to zero, stops polling
 * on unmount.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { defineComponent, h } from 'vue'
import { mount } from '@vue/test-utils'

vi.mock('../src/api/discovery', () => ({
  discoveryApi: {
    services: { pendingCount: vi.fn() },
  },
}))

import { discoveryApi } from '../src/api/discovery'
import { usePendingDiscoveryCount } from '../src/composables/usePendingDiscoveryCount'

function mountHost() {
  let exposed
  const Host = defineComponent({
    setup() {
      exposed = usePendingDiscoveryCount()
      return () => h('div', String(exposed.pendingCount.value))
    },
  })
  const wrapper = mount(Host)
  return { wrapper, get pendingCount() { return exposed.pendingCount } }
}

describe('usePendingDiscoveryCount', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.useFakeTimers()
  })
  afterEach(() => {
    vi.useRealTimers()
  })

  it('fetches the count on mount', async () => {
    discoveryApi.services.pendingCount.mockResolvedValue({ data: { count: 3 } })
    const { pendingCount } = mountHost()
    await vi.advanceTimersByTimeAsync(0)
    expect(discoveryApi.services.pendingCount).toHaveBeenCalledWith({ skipErrorToast: true })
    expect(pendingCount.value).toBe(3)
  })

  it('collapses a request failure to zero', async () => {
    discoveryApi.services.pendingCount.mockRejectedValue(new Error('network'))
    const { pendingCount } = mountHost()
    await vi.advanceTimersByTimeAsync(0)
    expect(pendingCount.value).toBe(0)
  })

  it('polls again after the interval elapses', async () => {
    discoveryApi.services.pendingCount
      .mockResolvedValueOnce({ data: { count: 1 } })
      .mockResolvedValueOnce({ data: { count: 5 } })
    const { pendingCount } = mountHost()
    await vi.advanceTimersByTimeAsync(0)
    expect(pendingCount.value).toBe(1)

    await vi.advanceTimersByTimeAsync(30_000)
    expect(pendingCount.value).toBe(5)
    expect(discoveryApi.services.pendingCount).toHaveBeenCalledTimes(2)
  })

  it('stops polling once unmounted', async () => {
    discoveryApi.services.pendingCount.mockResolvedValue({ data: { count: 1 } })
    const { wrapper } = mountHost()
    await vi.advanceTimersByTimeAsync(0)
    wrapper.unmount()

    await vi.advanceTimersByTimeAsync(60_000)
    expect(discoveryApi.services.pendingCount).toHaveBeenCalledTimes(1)
  })
})
