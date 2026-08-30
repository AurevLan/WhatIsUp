#!/usr/bin/env node
import { createI18n } from 'vue-i18n'
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

// Every message must actually compile. vue-i18n's message syntax gives
// meaning to characters that look inert in a plain string: `@` starts a linked
// message (`@:key`), `{...}` an interpolation. An unescaped e-mail address or a
// JSON snippet therefore throws at render time — and because these strings are
// placeholders, the failure is silent: the field just looks empty. Four such
// messages were live when this check was written, on four different screens.
// Checking "is there an @" would only close today's hole; compiling closes the
// class.
function uncompilable(locale, messages) {
  const i18n = createI18n({
    legacy: false,
    locale,
    messages: { [locale]: messages },
    missingWarn: false,
    fallbackWarn: false,
  })
  const broken = []
  for (const [key, value] of flatten(messages)) {
    if (typeof value !== 'string') continue
    try {
      i18n.global.t(key)
    } catch (err) {
      broken.push(`${locale}: ${key} — ${String(err.message).split('\n')[0]}`)
    }
  }
  return broken
}

const uncompilableMessages = [...uncompilable('en', en), ...uncompilable('fr', fr)]

const missingInFr = [...enFlat.keys()].filter((k) => !frFlat.has(k))
const missingInEn = [...frFlat.keys()].filter((k) => !enFlat.has(k))

const fmt = (label, list) => {
  if (list.length === 0) return `  ${label}: ✓ none\n`
  return `  ${label} (${list.length}):\n` + list.map((k) => `    - ${k}`).join('\n') + '\n'
}

const summary =
  `i18n key parity check\n` +
  fmt('missing in fr.js', missingInFr) +
  fmt('missing in en.js', missingInEn) +
  fmt('messages that fail to compile', uncompilableMessages)

if (missingInFr.length === 0 && missingInEn.length === 0 && uncompilableMessages.length === 0) {
  console.log(summary + '\n✓ en.js and fr.js are in sync (' + enFlat.size + ' keys each)')
  process.exit(0)
}

console.error(summary)
if (missingInFr.length || missingInEn.length) {
  console.error(`\n✗ ${missingInFr.length + missingInEn.length} divergent key(s). Add the missing keys.`)
}
if (uncompilableMessages.length) {
  console.error(
    `\n✗ ${uncompilableMessages.length} message(s) fail to compile and would render as nothing.\n` +
      "  Escape `@` as `\\@`, and literal braces as {'{'} and {'}'}."
  )
}
console.error('\nThen rerun: npm run check:i18n')
process.exit(1)
