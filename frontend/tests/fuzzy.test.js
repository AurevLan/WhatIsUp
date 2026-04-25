import { describe, it, expect } from 'vitest'
import { fuzzyScore, fuzzyFilter } from '../src/lib/fuzzy'

describe('fuzzyScore', () => {
  it('returns positive score for exact match', () => {
    expect(fuzzyScore('foo', 'foo')).toBeGreaterThan(0)
  })

  it('returns 0 when query characters are missing', () => {
    expect(fuzzyScore('xyz', 'monitor')).toBe(0)
  })

  it('returns 0 when characters are out of order', () => {
    expect(fuzzyScore('omn', 'mon')).toBe(0)
  })

  it('returns 1 for empty query (treated as match-all)', () => {
    expect(fuzzyScore('', 'anything')).toBe(1)
  })

  it('returns 0 when target is empty and query is not', () => {
    expect(fuzzyScore('q', '')).toBe(0)
  })

  it('is case-insensitive', () => {
    expect(fuzzyScore('FOO', 'foobar')).toBe(fuzzyScore('foo', 'FOOBAR'))
  })

  it('scores prefix match higher than substring match', () => {
    const prefix = fuzzyScore('mon', 'monitor')
    const middle = fuzzyScore('mon', 'global-monitor')
    expect(prefix).toBeGreaterThan(middle)
  })

  it('scores consecutive characters higher than scattered ones', () => {
    const consec = fuzzyScore('api', 'api-checker')
    const scatter = fuzzyScore('api', 'a-p-i-checker')
    expect(consec).toBeGreaterThan(scatter)
  })

  it('rewards word boundary matches', () => {
    const boundary = fuzzyScore('s', 'foo-server')
    const middle = fuzzyScore('s', 'pass')
    expect(boundary).toBeGreaterThan(middle)
  })
})

describe('fuzzyFilter', () => {
  const items = [
    { name: 'API status' },
    { name: 'database backup' },
    { name: 'staging API' },
    { name: 'home page' },
  ]

  it('returns all items when query empty', () => {
    expect(fuzzyFilter(items, '')).toHaveLength(4)
  })

  it('drops non-matching items', () => {
    const out = fuzzyFilter(items, 'api')
    expect(out.map(i => i.name)).toContain('API status')
    expect(out.map(i => i.name)).toContain('staging API')
    expect(out.map(i => i.name)).not.toContain('home page')
  })

  it('orders by score descending', () => {
    const out = fuzzyFilter(items, 'api')
    expect(out[0].name).toBe('API status')
  })

  it('uses custom getter', () => {
    const labelled = items.map(i => ({ payload: i.name }))
    const out = fuzzyFilter(labelled, 'home', (x) => x.payload)
    expect(out).toHaveLength(1)
    expect(out[0].payload).toBe('home page')
  })
})
