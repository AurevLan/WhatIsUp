import { describe, it, expect } from 'vitest'

import {
  levelBgClass,
  levelColor,
  levelTextClass,
  uptimeLevel,
} from '../src/lib/themeColors'
import { useMonitorDisplay } from '../src/composables/useMonitorDisplay'

// B1 — l'échelle de santé (≥99 / ≥90) vivait en double dans useMonitorDisplay
// et en triple dans ProbeMap. Ces tests pinnent le barème partagé et le fait
// que toutes les couleurs qui en dérivent restent tokenisées (VELOURS) : une
// régression vers la palette Tailwind brute (emerald/amber/red) échoue ici.

describe('uptimeLevel', () => {
  it.each([
    [100, 'up'],
    [99, 'up'],
    [98.9, 'warn'],
    [90, 'warn'],
    [89.9, 'down'],
    [0, 'down'],
  ])('maps %s%% to %s', (percent, level) => {
    expect(uptimeLevel(percent)).toBe(level)
  })

  it('treats a missing value as unknown, not as an outage', () => {
    expect(uptimeLevel(null)).toBe('unknown')
    expect(uptimeLevel(undefined)).toBe('unknown')
  })
})

describe('level → design-system classes', () => {
  it('only ever returns tokenized classes', () => {
    for (const level of ['up', 'warn', 'down', 'unknown']) {
      expect(levelTextClass(level)).toMatch(/^text-\(--[a-z0-9-]+\)$/)
      expect(levelBgClass(level)).toMatch(/^bg-\(--[a-z0-9-]+\)$/)
    }
  })

  it('falls back to the neutral token for an unknown level', () => {
    expect(levelTextClass('wat')).toBe('text-(--text-3)')
    expect(levelBgClass('wat')).toBe('bg-(--text-3)')
  })

  it('resolves a usable color for SVG / Leaflet even under jsdom', () => {
    // cssVar retourne '' sous jsdom : le fallback hex doit prendre le relais,
    // sinon les marqueurs Leaflet seraient rendus sans couleur.
    for (const level of ['up', 'warn', 'down', 'unknown']) {
      expect(levelColor(level)).toMatch(/^#[0-9a-f]{6}$/i)
    }
  })
})

describe('useMonitorDisplay colors', () => {
  const { uptimeColor, responseTimeColor } = useMonitorDisplay()

  it('derives uptime colors from the shared scale', () => {
    expect(uptimeColor(99.5)).toBe('text-(--up)')
    expect(uptimeColor(95)).toBe('text-(--warn)')
    expect(uptimeColor(50)).toBe('text-(--down)')
    expect(uptimeColor(null)).toBe('text-(--text-3)')
  })

  it('grades response time against the monitor p95, not the uptime scale', () => {
    const monitor = { _p95ResponseTimeMs: 1000 }
    expect(responseTimeColor(500, monitor)).toBe('text-(--up)')
    expect(responseTimeColor(1000, monitor)).toBe('text-(--warn)')
    expect(responseTimeColor(2000, monitor)).toBe('text-(--down)')
  })

  it('stays neutral when there is no p95 baseline to compare against', () => {
    expect(responseTimeColor(1200, { _p95ResponseTimeMs: null })).toBe('text-(--text-3)')
    expect(responseTimeColor(1200, {})).toBe('text-(--text-3)')
    expect(responseTimeColor(null, { _p95ResponseTimeMs: 1000 })).toBe('text-(--text-3)')
  })
})
