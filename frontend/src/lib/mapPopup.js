// Leaflet's `bindPopup`/`bindTooltip` treat a *string* argument as innerHTML,
// so any tenant-supplied field (a probe name, a location) interpolated into one
// is stored XSS. They also accept an HTMLElement — build the node instead, and
// every value goes through `textContent` while the styling stays ours.
//
// A line is one segment or an array of segments rendered side by side; a
// segment is `{ text, bold, style }`. Null/empty segments and lines that end up
// empty are dropped, so callers can inline conditionals without leaving blank
// rows behind.
export function buildMapPopup(lines) {
  const root = document.createElement('div')
  root.style.cssText = 'font-family:system-ui;min-width:150px;'

  let first = true
  for (const line of lines) {
    if (line == null) continue
    const segments = (Array.isArray(line) ? line : [line]).filter(
      (s) => s != null && s.text != null && s.text !== ''
    )
    if (segments.length === 0) continue

    if (!first) root.appendChild(document.createElement('br'))
    first = false

    for (const seg of segments) {
      const el = document.createElement(seg.bold ? 'b' : 'span')
      if (seg.style) el.style.cssText = seg.style
      el.textContent = String(seg.text)
      root.appendChild(el)
    }
  }
  return root
}
