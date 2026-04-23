// Minimal, safe markdown renderer for runbooks.
//
// Scope: headings h1-h3, bullet + ordered lists, task checkboxes, bold/italic,
// inline code, fenced code blocks, http(s) links, paragraphs, hard breaks.
//
// Safety: the input is HTML-escaped first; only literal substring patterns on
// already-escaped text are then rewritten into a fixed whitelist of tags. No
// raw user HTML ever reaches the DOM.

const escapeHtml = (s) =>
  s
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')

const safeHref = (url) => {
  const trimmed = url.trim()
  if (/^https?:\/\//i.test(trimmed)) return trimmed
  return '#'
}

const applyInline = (text) => {
  // input: HTML-escaped already. Order matters.
  let out = text

  // Fenced inline code `code`
  out = out.replace(/`([^`]+)`/g, (_, code) => `<code>${code}</code>`)

  // Links [text](http(s)://...)
  out = out.replace(/\[([^\]]+)\]\(([^)]+)\)/g, (_, label, url) => {
    return `<a href="${safeHref(url)}" target="_blank" rel="noopener noreferrer">${label}</a>`
  })

  // Bold **text**
  out = out.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')

  // Italic *text* (not part of a ** pair since we already consumed them)
  out = out.replace(/(^|[^*])\*([^*\s][^*]*)\*/g, '$1<em>$2</em>')

  return out
}

export function renderRunbookMarkdown(markdown) {
  if (!markdown || typeof markdown !== 'string') return ''

  const raw = escapeHtml(markdown)
  const lines = raw.split(/\r?\n/)

  const html = []
  let inList = null // 'ul' | 'ol' | null
  let inCode = false
  let codeBuf = []
  let paraBuf = []

  const flushPara = () => {
    if (paraBuf.length) {
      html.push(`<p>${applyInline(paraBuf.join(' '))}</p>`)
      paraBuf = []
    }
  }
  const closeList = () => {
    if (inList) {
      html.push(`</${inList}>`)
      inList = null
    }
  }

  for (const line of lines) {
    // Fenced code block toggle
    if (/^```/.test(line)) {
      if (inCode) {
        html.push(`<pre><code>${codeBuf.join('\n')}</code></pre>`)
        codeBuf = []
        inCode = false
      } else {
        flushPara()
        closeList()
        inCode = true
      }
      continue
    }
    if (inCode) {
      codeBuf.push(line)
      continue
    }

    // Blank line ends paragraph / list
    if (/^\s*$/.test(line)) {
      flushPara()
      closeList()
      continue
    }

    // Headings
    const h = /^(#{1,3})\s+(.*)$/.exec(line)
    if (h) {
      flushPara()
      closeList()
      const level = h[1].length
      html.push(`<h${level}>${applyInline(h[2])}</h${level}>`)
      continue
    }

    // Task list item: - [ ] / - [x]
    const task = /^\s*[-*]\s+\[([ xX])\]\s+(.*)$/.exec(line)
    if (task) {
      flushPara()
      if (inList !== 'ul') {
        closeList()
        html.push('<ul class="runbook-tasks">')
        inList = 'ul'
      }
      const checked = task[1].toLowerCase() === 'x' ? ' checked' : ''
      html.push(
        `<li class="runbook-task"><input type="checkbox" disabled${checked}> ${applyInline(task[2])}</li>`,
      )
      continue
    }

    // Bullet list
    const ul = /^\s*[-*]\s+(.*)$/.exec(line)
    if (ul) {
      flushPara()
      if (inList !== 'ul') {
        closeList()
        html.push('<ul>')
        inList = 'ul'
      }
      html.push(`<li>${applyInline(ul[1])}</li>`)
      continue
    }

    // Ordered list
    const ol = /^\s*\d+\.\s+(.*)$/.exec(line)
    if (ol) {
      flushPara()
      if (inList !== 'ol') {
        closeList()
        html.push('<ol>')
        inList = 'ol'
      }
      html.push(`<li>${applyInline(ol[1])}</li>`)
      continue
    }

    // Plain paragraph line
    closeList()
    paraBuf.push(line.trim())
  }

  if (inCode) html.push(`<pre><code>${codeBuf.join('\n')}</code></pre>`)
  flushPara()
  closeList()

  return html.join('\n')
}
