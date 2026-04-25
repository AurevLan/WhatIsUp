import { defineStore } from 'pinia'

const STORAGE_KEY = 'whatisup_palette_recents'
const MAX_RECENTS = 12

function loadRecents() {
  try {
    const raw = window.localStorage?.getItem(STORAGE_KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw)
    return Array.isArray(parsed) ? parsed : []
  } catch {
    return []
  }
}

function saveRecents(items) {
  try {
    window.localStorage?.setItem(STORAGE_KEY, JSON.stringify(items))
  } catch {
    // ignore quota / disabled storage
  }
}

export const useCommandPaletteStore = defineStore('commandPalette', {
  state: () => ({
    recents: loadRecents(),
  }),
  actions: {
    /**
     * Record a visited item so the palette can surface it under "Recent".
     * `item` shape: { type, id, name, route }
     */
    recordVisit(item) {
      if (!item || !item.id || !item.type || !item.route) return
      const key = `${item.type}:${item.id}`
      const next = [
        { ...item, ts: Date.now() },
        ...this.recents.filter((r) => `${r.type}:${r.id}` !== key),
      ].slice(0, MAX_RECENTS)
      this.recents = next
      saveRecents(next)
    },
    clearRecents() {
      this.recents = []
      saveRecents([])
    },
    /**
     * Drop one recent (e.g. monitor was deleted).
     */
    forget(type, id) {
      const next = this.recents.filter((r) => !(r.type === type && r.id === id))
      this.recents = next
      saveRecents(next)
    },
  },
})

export const PALETTE_RECENTS_KEY = STORAGE_KEY
export const PALETTE_RECENTS_MAX = MAX_RECENTS
