import { describe, it, expect, beforeEach, vi } from 'vitest'

const apiPost = vi.fn()
vi.mock('../src/api/client', () => ({
  default: { post: apiPost },
}))
vi.mock('../src/lib/serverConfig', () => ({
  isNative: () => false,
}))

let handleNotificationAction
beforeEach(async () => {
  apiPost.mockReset()
  apiPost.mockResolvedValue({ data: {} })
  // Re-import after mocks reset to get a fresh module instance.
  const mod = await import('../src/lib/pushNotifications')
  handleNotificationAction = mod.handleNotificationAction
})

function makeAction(actionId, data) {
  return { actionId, notification: { data } }
}

describe('handleNotificationAction (T1-04)', () => {
  it('routes the user to the monitor on a default tap', async () => {
    const router = { push: vi.fn() }
    await handleNotificationAction(makeAction('tap', { monitor_id: 'm1' }), router)
    expect(router.push).toHaveBeenCalledWith('/monitors/m1')
    expect(apiPost).not.toHaveBeenCalled()
  })

  it('calls /ack when the ack action button is tapped', async () => {
    const router = { push: vi.fn() }
    await handleNotificationAction(
      makeAction('ack', { incident_id: 'i1', monitor_id: 'm1' }),
      router,
    )
    expect(apiPost).toHaveBeenCalledWith('/incidents/i1/ack')
    expect(router.push).toHaveBeenCalledWith('/monitors/m1')
  })

  it('calls /snooze with 60 min for snooze_1h', async () => {
    await handleNotificationAction(
      makeAction('snooze_1h', { incident_id: 'i2', monitor_id: 'm2' }),
      null,
    )
    expect(apiPost).toHaveBeenCalledWith('/incidents/i2/snooze', { duration_minutes: 60 })
  })

  it('calls /snooze with 240 min for snooze_4h', async () => {
    await handleNotificationAction(
      makeAction('snooze_4h', { incident_id: 'i3', monitor_id: 'm3' }),
      null,
    )
    expect(apiPost).toHaveBeenCalledWith('/incidents/i3/snooze', { duration_minutes: 240 })
  })

  it('ignores unknown actions silently', async () => {
    await handleNotificationAction(
      makeAction('mystery', { incident_id: 'i4', monitor_id: 'm4' }),
      null,
    )
    expect(apiPost).not.toHaveBeenCalled()
  })

  it('survives missing incident id', async () => {
    await handleNotificationAction(makeAction('ack', { monitor_id: 'm5' }), null)
    expect(apiPost).not.toHaveBeenCalled()
  })

  it('does not crash when api call fails', async () => {
    apiPost.mockRejectedValueOnce(new Error('boom'))
    const router = { push: vi.fn() }
    await expect(
      handleNotificationAction(
        makeAction('ack', { incident_id: 'i6', monitor_id: 'm6' }),
        router,
      ),
    ).resolves.not.toThrow()
    expect(router.push).toHaveBeenCalledWith('/monitors/m6')
  })
})
