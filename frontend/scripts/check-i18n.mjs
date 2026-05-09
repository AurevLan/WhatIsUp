#!/usr/bin/env node
import en from '../src/i18n/en.js'
import fr from '../src/i18n/fr.js'

function flatten(obj, prefix = '') {
  const out = new Map()
  for (const [k, v] of Object.entries(obj)) {
    const key = prefix ? `${prefix}.${k}` : k
    if (v && typeof v === 'object' && !Array.isArray(v)) {
      for (const [nk, nv] of flatten(v, key)) out.set(nk, nv)
    } else {
      out.set(key, v)
    }
  }
  return out
}

const enFlat = flatten(en)
const frFlat = flatten(fr)

const missingInFr = [...enFlat.keys()].filter((k) => !frFlat.has(k))
const missingInEn = [...frFlat.keys()].filter((k) => !enFlat.has(k))

const fmt = (label, list) => {
  if (list.length === 0) return `  ${label}: ✓ none\n`
  return `  ${label} (${list.length}):\n` + list.map((k) => `    - ${k}`).join('\n') + '\n'
}

const summary = `i18n key parity check\n` + fmt('missing in fr.js', missingInFr) + fmt('missing in en.js', missingInEn)

if (missingInFr.length === 0 && missingInEn.length === 0) {
  console.log(summary + '\n✓ en.js and fr.js are in sync (' + enFlat.size + ' keys each)')
  process.exit(0)
}

console.error(summary)
console.error(`\n✗ i18n parity check failed: ${missingInFr.length + missingInEn.length} divergent key(s).`)
console.error('Add the missing keys, then rerun: npm run check:i18n')
process.exit(1)
