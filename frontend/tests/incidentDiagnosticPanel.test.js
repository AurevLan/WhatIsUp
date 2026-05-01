import { describe, it, expect, vi, beforeEach } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'

vi.mock('vue-i18n', () => ({
  useI18n: () => ({ t: (k) => k, locale: { value: 'en-US' } }),
}))

const mockGet = vi.fn()
vi.mock('../src/api/incidentUpdates', () => ({
  incidentUpdatesApi: { diagnostics: (id) => mockGet(id) },
}))

import IncidentDiagnosticPanel from '../src/components/incidents/IncidentDiagnosticPanel.vue'

const baseProps = { incidentId: 'abc-123' }

beforeEach(() => {
  mockGet.mockReset()
})

describe('IncidentDiagnosticPanel', () => {
  it('renders empty state when API returns []', async () => {
    mockGet.mockResolvedValue({ data: [] })
    const w = mount(IncidentDiagnosticPanel, { props: baseProps })
    await flushPromises()
    expect(w.find('.diag-empty').exists()).toBe(true)
  })

  it('groups results by probe and renders the kind label for each card', async () => {
    mockGet.mockResolvedValue({
      data: [
        {
          id: '1', incident_id: 'abc-123', probe_id: 'p1', probe_name: 'Paris',
          kind: 'traceroute',
          payload: { hops: [{ n: 1, ip: '10.0.0.1', rtt_ms: 1.2 }], total_hops: 1, target_ip: '1.2.3.4' },
          error: null, collected_at: '2026-05-01T10:00:00Z',
        },
        {
          id: '2', incident_id: 'abc-123', probe_id: 'p1', probe_name: 'Paris',
          kind: 'icmp_ping',
          payload: { packets_sent: 5, packets_received: 5, loss_pct: 0, rtt_avg_ms: 1.0 },
          error: null, collected_at: '2026-05-01T10:00:01Z',
        },
        {
          id: '3', incident_id: 'abc-123', probe_id: 'p2', probe_name: 'NYC',
          kind: 'traceroute',
          payload: { hops: [], total_hops: 0 },
          error: 'timeout', collected_at: '2026-05-01T10:00:00Z',
        },
      ],
    })
    const w = mount(IncidentDiagnosticPanel, { props: baseProps })
    await flushPromises()

    const probes = w.findAll('.diag-probe')
    expect(probes).toHaveLength(2)

    // Error rendering for the timeout sample
    const errCards = w.findAll('.diag-card--err')
    expect(errCards).toHaveLength(1)
    expect(errCards[0].text()).toContain('timeout')

    // 3 cards total
    expect(w.findAll('.diag-card')).toHaveLength(3)
  })

  it('shows the error message when API throws', async () => {
    mockGet.mockRejectedValue(new Error('boom'))
    const w = mount(IncidentDiagnosticPanel, { props: baseProps })
    await flushPromises()
    expect(w.find('.diag-error').text()).toContain('boom')
  })
})
