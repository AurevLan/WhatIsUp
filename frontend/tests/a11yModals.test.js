/**
 * A11Y-1 guard (plan_accessibilite.md) — every modal dialog must go through
 * BaseModal (focus trap, ARIA, Escape, focus restitution). A hand-rolled
 * `fixed inset-0` overlay in a .vue file is a regression.
 *
 * Allowed exceptions are non-dialog backdrops, listed explicitly below.
 */

import { describe, it, expect } from 'vitest'
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join, relative } from 'node:path'

// vitest's module URLs are not file:// — resolve from the project root instead
const SRC = join(process.cwd(), 'src')

const ALLOWED = new Set([
  // Backdrop du drawer mobile — aria-hidden, pas un dialogue
  'views/layouts/AppLayout.vue',
  // Backdrop invisible (z-10) fermant le dropdown de sélection de monitor,
  // à l'intérieur d'une BaseModal déjà en place
  'views/MaintenanceView.vue',
])

function vueFiles(dir) {
  return readdirSync(dir).flatMap((name) => {
    const p = join(dir, name)
    if (statSync(p).isDirectory()) return vueFiles(p)
    return name.endsWith('.vue') ? [p] : []
  })
}

describe('a11y — modal dialogs must use BaseModal', () => {
  it('finds no hand-rolled fixed-inset overlay outside the allowlist', () => {
    const offenders = vueFiles(SRC)
      .filter((f) => readFileSync(f, 'utf8').includes('fixed inset-0'))
      .map((f) => relative(SRC, f))
      .filter((p) => !ALLOWED.has(p))
    expect(offenders).toEqual([])
  })
})
