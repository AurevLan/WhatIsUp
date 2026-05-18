import { describe, it, expect, vi, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'

// CODE-6: views must read probes through this store instead of refetching
// probesApi.list() directly. These tests pin the caching/dedup contract the
// refactor relies on.

const listMock = vi.fn()
vi.mock('../../src/api/probes', () => ({
  probesApi: { list: (...a) => listMock(...a) },
}))

import { useProbesStore } from '../../src/stores/probes'

const SAMPLE = [
  { id: 'p1', name: 'Paris' },
  { id: 'p2', name: 'NYC' },
]

beforeEach(() => {
  setActivePinia(createPinia())
  listMock.mockReset()
  listMock.mockResolvedValue({ data: SAMPLE })
})

describe('useProbesStore', () => {
  it('fetch() populates probes + probeMap', async () => {
    const store = useProbesStore()
    const data = await store.fetch()
    expect(data).toEqual(SAMPLE)
    expect(store.probes).toEqual(SAMPLE)
    expect(store.probeMap.p2.name).toBe('NYC')
    expect(listMock).toHaveBeenCalledTimes(1)
  })

  it('second fetch() is served from cache (no redundant API call)', async () => {
    const store = useProbesStore()
    await store.fetch()
    await store.fetch()
    expect(listMock).toHaveBeenCalledTimes(1)
  })

  it('fetch({ force: true }) bypasses the cache (admin post-mutation path)', async () => {
    const store = useProbesStore()
    await store.fetch()
    await store.fetch({ force: true })
    expect(listMock).toHaveBeenCalledTimes(2)
  })

  it('concurrent fetch() calls share a single in-flight request', async () => {
    const store = useProbesStore()
    const [a, b] = await Promise.all([store.fetch(), store.fetch()])
    expect(a).toEqual(SAMPLE)
    expect(b).toEqual(SAMPLE)
    expect(listMock).toHaveBeenCalledTimes(1)
  })

  it('API failure degrades gracefully to empty state', async () => {
    listMock.mockRejectedValueOnce(new Error('403'))
    const store = useProbesStore()
    const data = await store.fetch()
    expect(data).toEqual([])
    expect(store.probes).toEqual([])
    expect(store.probeMap).toEqual({})
  })
})
