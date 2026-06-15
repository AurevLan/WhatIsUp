import { describe, it, expect, beforeEach, vi } from 'vitest'
import { ref } from 'vue'

const apiGet = vi.fn()
const apiPost = vi.fn()
vi.mock('../src/api/client', () => ({
  default: { get: apiGet, post: apiPost },
}))
vi.mock('../src/composables/useToast', () => ({
  useToast: () => ({ error: vi.fn(), success: vi.fn() }),
}))

let useDetectionAlertBridge
beforeEach(async () => {
  apiGet.mockReset()
  apiPost.mockReset().mockResolvedValue({ data: {} })
  useDetectionAlertBridge = (await import('../src/composables/useDetectionAlertBridge')).useDetectionAlertBridge
})

function mockApi({ channels = [], rules = [] }) {
  apiGet.mockImplementation((url) =>
    Promise.resolve({ data: url.includes('channels') ? channels : rules }),
  )
}

describe('useDetectionAlertBridge', () => {
  it('opens the modal when no rule for the condition exists and channels are available', async () => {
    mockApi({ channels: [{ id: 'c1', name: 'Email', type: 'email' }], rules: [] })
    const b = useDetectionAlertBridge(ref({ id: 'm1' }))
    await b.offerAlert('schema_drift')
    expect(b.alertModal.value).toBe(true)
    expect(b.alertChannelId.value).toBe('c1')
    expect(b.pendingCondition.value).toBe('schema_drift')
  })

  it('stays closed when a rule with that condition already exists', async () => {
    mockApi({
      channels: [{ id: 'c1', name: 'Email', type: 'email' }],
      rules: [{ monitor_id: 'm1', condition: 'schema_drift' }],
    })
    const b = useDetectionAlertBridge(ref({ id: 'm1' }))
    await b.offerAlert('schema_drift')
    expect(b.alertModal.value).toBe(false)
  })

  it('stays closed when no channels are configured', async () => {
    mockApi({ channels: [], rules: [] })
    const b = useDetectionAlertBridge(ref({ id: 'm1' }))
    await b.offerAlert('schema_drift')
    expect(b.alertModal.value).toBe(false)
  })

  it('createAlertRule posts the pending condition for the monitor + channel', async () => {
    mockApi({ channels: [{ id: 'c1', name: 'Email', type: 'email' }], rules: [] })
    const b = useDetectionAlertBridge(ref({ id: 'm1' }))
    await b.offerAlert('any_down')
    await b.createAlertRule()
    expect(apiPost).toHaveBeenCalledWith('/alerts/rules', {
      monitor_id: 'm1',
      condition: 'any_down',
      min_duration_seconds: 0,
      channel_ids: ['c1'],
    })
    expect(b.alertModal.value).toBe(false)
  })
})
