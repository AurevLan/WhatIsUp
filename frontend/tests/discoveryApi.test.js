/**
 * discoveryApi (plan D, D-3) — thin wrapper sanity: every call hits the
 * expected URL/verb, mirroring the conventions of the other api/*.js modules.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('../src/api/client', () => ({
  default: {
    get: vi.fn().mockResolvedValue({ data: [] }),
    post: vi.fn().mockResolvedValue({ data: {} }),
    patch: vi.fn().mockResolvedValue({ data: {} }),
    delete: vi.fn().mockResolvedValue({}),
  },
}))

import api from '../src/api/client'
import { discoveryApi } from '../src/api/discovery'

describe('discoveryApi', () => {
  beforeEach(() => vi.clearAllMocks())

  describe('sources', () => {
    it('list() GETs /discovery/sources/', async () => {
      await discoveryApi.sources.list()
      expect(api.get).toHaveBeenCalledWith('/discovery/sources/', {})
    })

    it('create() POSTs the payload', async () => {
      await discoveryApi.sources.create({ probe_id: 'p-1', source_type: 'docker', params: {} })
      expect(api.post).toHaveBeenCalledWith(
        '/discovery/sources/',
        { probe_id: 'p-1', source_type: 'docker', params: {} },
        {}
      )
    })

    it('update() PATCHes by id', async () => {
      await discoveryApi.sources.update('s-1', { enabled: false })
      expect(api.patch).toHaveBeenCalledWith('/discovery/sources/s-1', { enabled: false }, {})
    })

    it('remove() DELETEs by id', async () => {
      await discoveryApi.sources.remove('s-1')
      expect(api.delete).toHaveBeenCalledWith('/discovery/sources/s-1', {})
    })

    it('scanNow() POSTs to the scan-now endpoint', async () => {
      await discoveryApi.sources.scanNow('s-1')
      expect(api.post).toHaveBeenCalledWith('/discovery/sources/s-1/scan-now', {}, {})
    })
  })

  describe('services', () => {
    it('list() GETs /discovery/services/ with query params', async () => {
      await discoveryApi.services.list({ status: 'orphaned' })
      expect(api.get).toHaveBeenCalledWith('/discovery/services/', { params: { status: 'orphaned' } })
    })

    it('accept() POSTs to the accept endpoint', async () => {
      await discoveryApi.services.accept('svc-1', { name: 'x' })
      expect(api.post).toHaveBeenCalledWith('/discovery/services/svc-1/accept', { name: 'x' }, {})
    })

    it('dismiss() POSTs to the dismiss endpoint', async () => {
      await discoveryApi.services.dismiss('svc-1', { reason: 'noise' })
      expect(api.post).toHaveBeenCalledWith('/discovery/services/svc-1/dismiss', { reason: 'noise' }, {})
    })

    it('bulk() POSTs to the bulk endpoint', async () => {
      await discoveryApi.services.bulk({ action: 'accept', service_ids: ['a', 'b'] })
      expect(api.post).toHaveBeenCalledWith(
        '/discovery/services/bulk',
        { action: 'accept', service_ids: ['a', 'b'] },
        {}
      )
    })
  })
})
