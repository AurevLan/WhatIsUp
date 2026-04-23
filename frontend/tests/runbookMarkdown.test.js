import { describe, it, expect } from 'vitest'
import { renderRunbookMarkdown } from '../src/lib/runbookMarkdown'

describe('renderRunbookMarkdown', () => {
  it('returns empty string for null / empty / non-string input', () => {
    expect(renderRunbookMarkdown('')).toBe('')
    expect(renderRunbookMarkdown(null)).toBe('')
    expect(renderRunbookMarkdown(undefined)).toBe('')
    expect(renderRunbookMarkdown(42)).toBe('')
  })

  it('escapes raw HTML — no user script reaches the DOM', () => {
    const html = renderRunbookMarkdown('<script>alert(1)</script>')
    expect(html).not.toContain('<script')
    expect(html).toContain('&lt;script&gt;')
  })

  it('renders headings h1-h3', () => {
    expect(renderRunbookMarkdown('# T1')).toContain('<h1>T1</h1>')
    expect(renderRunbookMarkdown('## T2')).toContain('<h2>T2</h2>')
    expect(renderRunbookMarkdown('### T3')).toContain('<h3>T3</h3>')
  })

  it('renders bullet lists', () => {
    const html = renderRunbookMarkdown('- one\n- two')
    expect(html).toContain('<ul>')
    expect(html).toContain('<li>one</li>')
    expect(html).toContain('<li>two</li>')
    expect(html).toContain('</ul>')
  })

  it('renders ordered lists', () => {
    const html = renderRunbookMarkdown('1. first\n2. second')
    expect(html).toContain('<ol>')
    expect(html).toContain('<li>first</li>')
    expect(html).toContain('<li>second</li>')
  })

  it('renders task checkboxes', () => {
    const html = renderRunbookMarkdown('- [ ] todo\n- [x] done')
    expect(html).toContain('<input type="checkbox" disabled>')
    expect(html).toContain('<input type="checkbox" disabled checked>')
    expect(html).toContain('todo')
    expect(html).toContain('done')
  })

  it('renders bold, italic, inline code', () => {
    const html = renderRunbookMarkdown('This is **bold** and *italic* and `code`.')
    expect(html).toContain('<strong>bold</strong>')
    expect(html).toContain('<em>italic</em>')
    expect(html).toContain('<code>code</code>')
  })

  it('renders fenced code blocks without re-interpreting markdown inside', () => {
    const html = renderRunbookMarkdown('```\n# not a heading\n**bold**\n```')
    expect(html).toContain('<pre><code>')
    expect(html).toContain('# not a heading')
    expect(html).toContain('**bold**')
    expect(html).not.toContain('<h1>')
    expect(html).not.toContain('<strong>')
  })

  it('allows http(s) links but strips javascript: hrefs', () => {
    const ok = renderRunbookMarkdown('[click](https://example.com)')
    expect(ok).toContain('href="https://example.com"')
    expect(ok).toContain('rel="noopener noreferrer"')

    const bad = renderRunbookMarkdown('[click](javascript:alert(1))')
    expect(bad).toContain('href="#"')
    expect(bad).not.toContain('javascript:')
  })

  it('wraps plain lines into paragraphs separated by blank lines', () => {
    const html = renderRunbookMarkdown('first line\n\nsecond paragraph')
    expect(html).toContain('<p>first line</p>')
    expect(html).toContain('<p>second paragraph</p>')
  })
})
