import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { defineComponent, h } from 'vue'
import { useHotkeys, HOTKEYS_SEQUENCE_TIMEOUT_MS } from '../src/composables/useHotkeys'

function makeHost(bindings) {
  return defineComponent({
    setup() {
      useHotkeys(bindings)
      return () => h('div')
    },
  })
}

function dispatch(key, opts = {}) {
  const e = new KeyboardEvent('keydown', {
    key,
    bubbles: true,
    cancelable: true,
    ...opts,
  })
  window.dispatchEvent(e)
  return e
}

beforeEach(() => {
  vi.useFakeTimers()
})

describe('useHotkeys', () => {
  it('fires single-key bindings immediately', () => {
    const run = vi.fn()
    mount(makeHost([{ keys: '?', run }]))
    dispatch('?')
    expect(run).toHaveBeenCalledOnce()
  })

  it('fires sequence bindings (g d) within window', () => {
    const run = vi.fn()
    mount(makeHost([{ keys: 'g d', run }]))
    dispatch('g')
    expect(run).not.toHaveBeenCalled()
    dispatch('d')
    expect(run).toHaveBeenCalledOnce()
  })

  it('drops the buffer after the timeout', () => {
    const run = vi.fn()
    mount(makeHost([{ keys: 'g d', run }]))
    dispatch('g')
    vi.advanceTimersByTime(HOTKEYS_SEQUENCE_TIMEOUT_MS + 10)
    dispatch('d')
    expect(run).not.toHaveBeenCalled()
  })

  it('ignores bindings while typing in inputs', () => {
    const run = vi.fn()
    mount(makeHost([{ keys: '?', run }]))
    const input = document.createElement('input')
    document.body.appendChild(input)
    input.focus()
    input.dispatchEvent(new KeyboardEvent('keydown', { key: '?', bubbles: true }))
    expect(run).not.toHaveBeenCalled()
    input.remove()
  })

  it('ignores bindings when modifier keys are held', () => {
    const run = vi.fn()
    mount(makeHost([{ keys: 'k', run }]))
    dispatch('k', { metaKey: true })
    dispatch('k', { ctrlKey: true })
    expect(run).not.toHaveBeenCalled()
  })

  it('does not fire prefix matches for the wrong continuation', () => {
    const goM = vi.fn()
    const goD = vi.fn()
    mount(makeHost([
      { keys: 'g m', run: goM },
      { keys: 'g d', run: goD },
    ]))
    dispatch('g')
    dispatch('x')
    vi.advanceTimersByTime(HOTKEYS_SEQUENCE_TIMEOUT_MS + 10)
    dispatch('m')
    expect(goM).not.toHaveBeenCalled()
    expect(goD).not.toHaveBeenCalled()
  })

  it('matches the right binding among siblings', () => {
    const goM = vi.fn()
    const goD = vi.fn()
    mount(makeHost([
      { keys: 'g m', run: goM },
      { keys: 'g d', run: goD },
    ]))
    dispatch('g')
    dispatch('d')
    expect(goD).toHaveBeenCalledOnce()
    expect(goM).not.toHaveBeenCalled()
  })

  it('cleans up the listener on unmount', () => {
    const run = vi.fn()
    const w = mount(makeHost([{ keys: '?', run }]))
    w.unmount()
    dispatch('?')
    expect(run).not.toHaveBeenCalled()
  })
})
