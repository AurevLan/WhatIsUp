import { describe, it, expect } from 'vitest'
import { buildMapPopup } from '../src/lib/mapPopup'

// Leaflet renders a *string* popup as innerHTML, so a probe name is a stored
// XSS vector unless the popup is built as DOM. These tests pin the escaping —
// they fail the moment someone goes back to a template literal.
describe('buildMapPopup', () => {
  it('renders tenant text as text, never as markup', () => {
    const el = buildMapPopup([
      { text: '<img src=x onerror="alert(1)">', bold: true },
      { text: '<script>alert(2)</script>' },
    ])

    expect(el.querySelector('img')).toBeNull()
    expect(el.querySelector('script')).toBeNull()
    expect(el.textContent).toContain('<img src=x onerror="alert(1)">')
    expect(el.textContent).toContain('<script>alert(2)</script>')
  })

  it('keeps the caller-controlled styling and bold segments', () => {
    const el = buildMapPopup([
      { text: 'probe-1', bold: true, style: 'font-size:13px;' },
      { text: 'Paris', style: 'color:red;' },
    ])

    const bold = el.querySelector('b')
    expect(bold.textContent).toBe('probe-1')
    expect(bold.style.fontSize).toBe('13px')
    expect(el.querySelectorAll('span')[0].style.color).toBe('red')
  })

  it('renders a multi-segment line without a break between its segments', () => {
    const el = buildMapPopup([[{ text: '● up' }, { text: ' — 42ms' }], { text: 'just now' }])

    // One <br>: between the two lines, not inside the first one.
    expect(el.querySelectorAll('br')).toHaveLength(1)
    expect(el.textContent).toBe('● up — 42msjust now')
  })

  it('drops null and empty segments instead of leaving blank rows', () => {
    const el = buildMapPopup([
      { text: 'only line' },
      null,
      { text: '' },
      { text: null },
      [null, { text: '' }],
    ])

    expect(el.querySelectorAll('br')).toHaveLength(0)
    expect(el.textContent).toBe('only line')
  })

  it('coerces non-string values (a probe id fallback stays readable)', () => {
    const el = buildMapPopup([{ text: 42 }])
    expect(el.textContent).toBe('42')
  })
})
