import { describe, it, expect, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useCommandPaletteStore, PALETTE_RECENTS_KEY, PALETTE_RECENTS_MAX } from '../src/stores/commandPalette'

beforeEach(() => {
  setActivePinia(createPinia())
  try { window.localStorage.clear() } catch { /* ignore */ }
})

describe('commandPalette store', () => {
  it('starts empty when nothing in localStorage', () => {
    const s = useCommandPaletteStore()
    expect(s.recents).toEqual([])
  })

  it('loads recents from localStorage on init', () => {
    window.localStorage.setItem(
      PALETTE_RECENTS_KEY,
      JSON.stringify([{ type: 'monitor', id: 'a', name: 'A', route: '/monitors/a', ts: 1 }]),
    )
    const s = useCommandPaletteStore()
    expect(s.recents).toHaveLength(1)
    expect(s.recents[0].name).toBe('A')
  })

  it('records a visit and persists it', () => {
    const s = useCommandPaletteStore()
    s.recordVisit({ type: 'monitor', id: 'a', name: 'A', route: '/monitors/a' })
    expect(s.recents).toHaveLength(1)
    const persisted = JSON.parse(window.localStorage.getItem(PALETTE_RECENTS_KEY))
    expect(persisted[0].name).toBe('A')
  })

  it('moves repeat visits to the front (no duplicates)', () => {
    const s = useCommandPaletteStore()
    s.recordVisit({ type: 'monitor', id: 'a', name: 'A', route: '/monitors/a' })
    s.recordVisit({ type: 'monitor', id: 'b', name: 'B', route: '/monitors/b' })
    s.recordVisit({ type: 'monitor', id: 'a', name: 'A', route: '/monitors/a' })
    expect(s.recents).toHaveLength(2)
    expect(s.recents[0].id).toBe('a')
    expect(s.recents[1].id).toBe('b')
  })

  it('caps the list at PALETTE_RECENTS_MAX', () => {
    const s = useCommandPaletteStore()
    for (let i = 0; i < PALETTE_RECENTS_MAX + 5; i++) {
      s.recordVisit({ type: 'monitor', id: `m${i}`, name: `M${i}`, route: `/monitors/m${i}` })
    }
    expect(s.recents).toHaveLength(PALETTE_RECENTS_MAX)
    // Most recent comes first.
    expect(s.recents[0].id).toBe(`m${PALETTE_RECENTS_MAX + 4}`)
  })

  it('ignores incomplete visit payloads', () => {
    const s = useCommandPaletteStore()
    s.recordVisit({ id: 'a', name: 'A' }) // missing type/route
    s.recordVisit(null)
    expect(s.recents).toEqual([])
  })

  it('clearRecents wipes both state and storage', () => {
    const s = useCommandPaletteStore()
    s.recordVisit({ type: 'monitor', id: 'a', name: 'A', route: '/x' })
    s.clearRecents()
    expect(s.recents).toEqual([])
    expect(window.localStorage.getItem(PALETTE_RECENTS_KEY)).toBe('[]')
  })

  it('forget drops a single entry', () => {
    const s = useCommandPaletteStore()
    s.recordVisit({ type: 'monitor', id: 'a', name: 'A', route: '/x' })
    s.recordVisit({ type: 'monitor', id: 'b', name: 'B', route: '/y' })
    s.forget('monitor', 'a')
    expect(s.recents).toHaveLength(1)
    expect(s.recents[0].id).toBe('b')
  })
})
