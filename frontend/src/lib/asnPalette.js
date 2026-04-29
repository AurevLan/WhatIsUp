// V2-02-06 — Deterministic color for an ASN.
//
// Same ASN → always the same color across reloads and across browsers, so the
// map and the legend stay coherent without persisting any palette server-side.
// We use FNV-1a 32-bit hash modulo a curated palette tuned for the dark theme.

const PALETTE = [
  '#60a5fa', // blue-400
  '#a855f7', // purple-500
  '#34d399', // emerald-400
  '#fbbf24', // amber-400
  '#f87171', // red-400
  '#22d3ee', // cyan-400
  '#fb7185', // rose-400
  '#a3e635', // lime-400
  '#f97316', // orange-500
  '#ec4899', // pink-500
  '#14b8a6', // teal-500
  '#8b5cf6', // violet-500
]

const UNKNOWN_COLOR = '#475569' // slate-600 — used when ASN is null

function fnv1a(str) {
  let h = 0x811c9dc5
  for (let i = 0; i < str.length; i++) {
    h ^= str.charCodeAt(i)
    h = (h + ((h << 1) + (h << 4) + (h << 7) + (h << 8) + (h << 24))) >>> 0
  }
  return h >>> 0
}

export function colorForAsn(asn) {
  if (asn == null || asn === '') return UNKNOWN_COLOR
  const idx = fnv1a(String(asn)) % PALETTE.length
  return PALETTE[idx]
}

export function asnLabel(asn, asnName) {
  if (asn == null) return null
  return asnName ? `AS${asn} ${asnName}` : `AS${asn}`
}

// V2-02-07 — true when the probe's egress IP differs from the IP we observe
// server-side. Indicates a proxy, NAT or VPN in the path.
export function hasProxyDivergence(probe) {
  if (!probe) return false
  const observed = probe.public_ip
  const reported = probe.self_reported_ip
  if (!observed || !reported) return false
  return observed !== reported
}
