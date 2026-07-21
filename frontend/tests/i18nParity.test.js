import { describe, it, expect } from 'vitest'

import en from '../src/i18n/en'
import fr from '../src/i18n/fr'

// B3 — garde-fou permanent du sweep i18n.
//
// Une clé ajoutée dans une seule locale ne casse rien à la compilation : elle
// se voit uniquement à l'exécution, sous la forme du chemin brut affiché à
// l'écran (« scenario.add_step ») pour les utilisateurs de l'autre langue.
// Ce test fait échouer la CI à la place.

function flatten(obj, prefix = '') {
  const out = {}
  for (const [k, v] of Object.entries(obj)) {
    const path = prefix ? `${prefix}.${k}` : k
    if (v && typeof v === 'object' && !Array.isArray(v)) Object.assign(out, flatten(v, path))
    else out[path] = v
  }
  return out
}

const flatEn = flatten(en)
const flatFr = flatten(fr)

describe('i18n en/fr parity', () => {
  it('has no key present in only one locale', () => {
    const onlyEn = Object.keys(flatEn).filter((k) => !(k in flatFr))
    const onlyFr = Object.keys(flatFr).filter((k) => !(k in flatEn))
    expect({ onlyEn, onlyFr }).toEqual({ onlyEn: [], onlyFr: [] })
  })

  it('keeps the same shape on both sides — no leaf facing a sub-tree', () => {
    // `alerts.add_channel` (chaîne) a déjà collisionné avec un bloc imbriqué
    // du même nom : le type de chaque feuille doit concorder.
    const mismatched = Object.keys(flatEn)
      .filter((k) => k in flatFr)
      .filter((k) => typeof flatEn[k] !== typeof flatFr[k])
    expect(mismatched).toEqual([])
  })

  it('has no empty translation', () => {
    // Les libellés d'URL des types sans cible sont vides à dessein.
    const allowedEmpty = /^create_monitor\.types\.(heartbeat|composite)\.url_(label|placeholder)$/
    const empty = Object.entries(flatFr)
      .filter(([k, v]) => typeof v === 'string' && v.trim() === '' && !allowedEmpty.test(k))
      .map(([k]) => k)
    expect(empty).toEqual([])
  })

  it('carries the interpolation placeholders across locales', () => {
    // Un `{n}` oublié dans une traduction affiche un compteur vide.
    const placeholders = (s) => (String(s).match(/\{[a-zA-Z_]+\}/g) || []).sort()
    const broken = Object.keys(flatEn)
      .filter((k) => k in flatFr && typeof flatEn[k] === 'string')
      .filter((k) => {
        const a = placeholders(flatEn[k])
        const b = placeholders(flatFr[k])
        return a.join(',') !== b.join(',')
      })
    expect(broken).toEqual([])
  })
})
