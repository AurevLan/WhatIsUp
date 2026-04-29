import { describe, it, expect } from 'vitest'
import { asnLabel, colorForAsn, hasProxyDivergence } from '../src/lib/asnPalette'

describe('colorForAsn', () => {
  it('returns the unknown color for null/undefined/empty', () => {
    expect(colorForAsn(null)).toBe('#475569')
    expect(colorForAsn(undefined)).toBe('#475569')
    expect(colorForAsn('')).toBe('#475569')
  })

  it('is deterministic — same ASN always maps to the same color', () => {
    const a = colorForAsn(15169)
    const b = colorForAsn(15169)
    const c = colorForAsn(15169)
    expect(a).toBe(b)
    expect(b).toBe(c)
  })

  it('returns a color from the palette (never the unknown grey for a real ASN)', () => {
    expect(colorForAsn(15169)).not.toBe('#475569')
    expect(colorForAsn(2914)).not.toBe('#475569')
  })

  it('distributes typical ASNs across multiple colors (avoid trivial hash)', () => {
    const colors = new Set([15169, 2914, 13335, 16509, 7018, 8075, 32934].map(colorForAsn))
    // Expect at least 4 distinct colors out of 7 ASNs.
    expect(colors.size).toBeGreaterThanOrEqual(4)
  })

  it('accepts string ASN equally to number', () => {
    expect(colorForAsn('15169')).toBe(colorForAsn(15169))
  })
})

describe('asnLabel', () => {
  it('returns null when ASN is missing', () => {
    expect(asnLabel(null, 'GOOGLE')).toBeNull()
    expect(asnLabel(undefined, null)).toBeNull()
  })
  it('formats AS<num> when no name', () => {
    expect(asnLabel(15169, null)).toBe('AS15169')
  })
  it('formats AS<num> <name> when name present', () => {
    expect(asnLabel(15169, 'GOOGLE, US')).toBe('AS15169 GOOGLE, US')
  })
})

describe('hasProxyDivergence', () => {
  it('returns false when either IP is missing', () => {
    expect(hasProxyDivergence({ public_ip: null, self_reported_ip: '1.1.1.1' })).toBe(false)
    expect(hasProxyDivergence({ public_ip: '1.1.1.1', self_reported_ip: null })).toBe(false)
    expect(hasProxyDivergence(null)).toBe(false)
    expect(hasProxyDivergence(undefined)).toBe(false)
  })
  it('returns false when IPs match', () => {
    expect(hasProxyDivergence({ public_ip: '8.8.8.8', self_reported_ip: '8.8.8.8' })).toBe(false)
  })
  it('returns true when IPs diverge', () => {
    expect(hasProxyDivergence({ public_ip: '8.8.8.8', self_reported_ip: '1.1.1.1' })).toBe(true)
  })
})
