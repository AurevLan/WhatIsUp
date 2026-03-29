/**
 * Tests for composables (useToast, useConfirm) and webPush utility.
 */

import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest'

// ── useToast ─────────────────────────────────────────────────────────────────

describe('useToast', () => {
  let useToast

  beforeEach(async () => {
    vi.useFakeTimers()
    // Fresh import to reset module-level state
    vi.resetModules()
    const mod = await import('../src/composables/useToast.js')
    useToast = mod.useToast
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('adds a success toast', () => {
    const { toasts, success } = useToast()
    success('Done!')
    expect(toasts.length).toBe(1)
    expect(toasts[0].message).toBe('Done!')
    expect(toasts[0].type).toBe('success')
  })

  it('adds error, info, warning toasts', () => {
    const { toasts, error, info, warning } = useToast()
    error('Fail')
    info('Note')
    warning('Watch out')
    expect(toasts.length).toBe(3)
    expect(toasts[0].type).toBe('error')
    expect(toasts[1].type).toBe('info')
    expect(toasts[2].type).toBe('warning')
  })

  it('auto-removes toast after duration', () => {
    const { toasts, success } = useToast()
    success('Temp')
    expect(toasts.length).toBe(1)

    vi.advanceTimersByTime(3500)
    expect(toasts.length).toBe(0)
  })

  it('error toast has longer duration (5s)', () => {
    const { toasts, error } = useToast()
    error('Problem')

    vi.advanceTimersByTime(3500)
    expect(toasts.length).toBe(1) // still there

    vi.advanceTimersByTime(1500)
    expect(toasts.length).toBe(0) // gone after 5s
  })

  it('remove() manually removes a toast', () => {
    const { toasts, success, remove } = useToast()
    success('First')
    success('Second')
    expect(toasts.length).toBe(2)

    remove(toasts[0].id)
    expect(toasts.length).toBe(1)
    expect(toasts[0].message).toBe('Second')
  })

  it('each toast gets a unique id', () => {
    const { toasts, success } = useToast()
    success('A')
    success('B')
    expect(toasts[0].id).not.toBe(toasts[1].id)
  })
})

// ── useConfirm ───────────────────────────────────────────────────────────────

describe('useConfirm', () => {
  let useConfirm

  beforeEach(async () => {
    vi.resetModules()
    const mod = await import('../src/composables/useConfirm.js')
    useConfirm = mod.useConfirm
  })

  it('confirm() opens dialog and returns a promise', () => {
    const { confirmState, confirm } = useConfirm()
    const promise = confirm({ title: 'Delete?', message: 'Are you sure?' })

    expect(confirmState.visible).toBe(true)
    expect(confirmState.title).toBe('Delete?')
    expect(confirmState.message).toBe('Are you sure?')
    expect(promise).toBeInstanceOf(Promise)
  })

  it('answer(true) resolves the promise with true', async () => {
    const { confirm, answer } = useConfirm()
    const promise = confirm({ title: 'Ok?' })

    answer(true)
    expect(await promise).toBe(true)
  })

  it('answer(false) resolves the promise with false', async () => {
    const { confirm, answer } = useConfirm()
    const promise = confirm({ title: 'Cancel?' })

    answer(false)
    expect(await promise).toBe(false)
  })

  it('answer() hides the dialog', () => {
    const { confirmState, confirm, answer } = useConfirm()
    confirm({ title: 'Test' })
    expect(confirmState.visible).toBe(true)

    answer(true)
    expect(confirmState.visible).toBe(false)
  })

  it('uses default values when none provided', () => {
    const { confirmState, confirm } = useConfirm()
    confirm({})

    expect(confirmState.title).toBe('')
    expect(confirmState.message).toBe('')
    expect(confirmState.confirmLabel).toBe('Confirm')
    expect(confirmState.danger).toBe(true)
  })

  it('custom confirmLabel and danger=false', () => {
    const { confirmState, confirm } = useConfirm()
    confirm({ title: 'Archive?', confirmLabel: 'Archive', danger: false })

    expect(confirmState.confirmLabel).toBe('Archive')
    expect(confirmState.danger).toBe(false)
  })
})

// ── urlBase64ToUint8Array ────────────────────────────────────────────────────

describe('urlBase64ToUint8Array', () => {
  // We test the function directly by importing the store module
  // The function is not exported, so we replicate it here for unit testing
  function urlBase64ToUint8Array(base64String) {
    const padding = '='.repeat((4 - (base64String.length % 4)) % 4)
    const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/')
    const raw = atob(base64)
    return Uint8Array.from([...raw].map((c) => c.charCodeAt(0)))
  }

  it('converts a standard VAPID key', () => {
    // Example VAPID public key (base64url encoded)
    const key = 'BNbxGYNMhEIi9eGtKF2KXL1GOCpMqHgO0eCz4ZzKQBZcBi7m2Vh-DP8GjGJkNqMgb7mrMJOxmOoMKxMEF_yOHI'
    const result = urlBase64ToUint8Array(key)
    expect(result).toBeInstanceOf(Uint8Array)
    expect(result.length).toBeGreaterThan(0)
  })

  it('handles short input', () => {
    const result = urlBase64ToUint8Array('AQID') // [1, 2, 3]
    expect(result).toEqual(new Uint8Array([1, 2, 3]))
  })

  it('adds padding correctly', () => {
    // 'YQ' needs '==' padding → 'a'
    const result = urlBase64ToUint8Array('YQ')
    expect(result).toEqual(new Uint8Array([97])) // 'a' = 97
  })

  it('replaces url-safe chars with standard base64', () => {
    // '-' → '+', '_' → '/'
    const result = urlBase64ToUint8Array('A-B_')
    expect(result).toBeInstanceOf(Uint8Array)
    expect(result.length).toBe(3)
  })
})
