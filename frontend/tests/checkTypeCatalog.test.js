import { describe, it, expect } from 'vitest'

import en from '../src/i18n/en'
import fr from '../src/i18n/fr'

// B2 — le catalogue des types de check vivait en double dans les modales de
// création et d'édition, avec des chaînes codées en dur qui avaient divergé :
// anglais côté création, français côté édition, quelle que soit la locale.
// Ces tests pinnent le fait que chaque type est désormais entièrement traduit
// dans les deux locales — un type ajouté sans traduction échoue ici.

const TYPES = [
  'http',
  'keyword',
  'json_path',
  'tcp',
  'dns',
  'scenario',
  'heartbeat',
  'udp',
  'smtp',
  'ping',
  'domain_expiry',
  'composite',
]

// heartbeat et composite n'ont pas de cible réseau : leurs libellés d'URL
// sont vides à dessein (le champ est masqué).
const TYPES_WITHOUT_TARGET = ['heartbeat', 'composite']

describe.each([
  ['en', en],
  ['fr', fr],
])('check type catalog (%s)', (locale, messages) => {
  it.each(TYPES)('has a label for %s', (type) => {
    expect(messages.monitors.check_type[type]).toBeTruthy()
  })

  it.each(TYPES)('has a full form catalog entry for %s', (type) => {
    const entry = messages.create_monitor.types[type]
    expect(entry, `${locale}: create_monitor.types.${type} is missing`).toBeDefined()
    expect(entry.description).toBeTruthy()
    expect(entry.name_placeholder).toBeTruthy()
    // url_label / url_placeholder sont volontairement vides pour les types
    // sans cible : on vérifie seulement que la clé existe.
    expect(entry).toHaveProperty('url_label')
    expect(entry).toHaveProperty('url_placeholder')
    if (!TYPES_WITHOUT_TARGET.includes(type)) {
      expect(entry.url_label, `${locale}: ${type} needs a target label`).toBeTruthy()
    }
  })
})

describe('locale parity', () => {
  it('describes every type in both locales, with no leftovers', () => {
    expect(Object.keys(fr.create_monitor.types).sort()).toEqual(
      Object.keys(en.create_monitor.types).sort(),
    )
    expect(Object.keys(en.create_monitor.types).sort()).toEqual([...TYPES].sort())
  })

  it('translates the extracted form field labels in both locales', () => {
    // Ces clés remplacent des chaînes qui étaient codées en dur en anglais
    // dans la modale de création et en français dans celle d'édition.
    const keys = [
      'udp_hint',
      'domain_expiry_threshold',
      'domain_expiry_hint',
      'dns_record_type',
      'dns_expected_value',
      'keyword_label',
      'keyword_negate',
      'keyword_negate_strong',
      'json_path_label',
      'json_expected_value',
      'composite_members_hint',
      'heartbeat_ping_url',
      'follow_redirects',
      'ssl_check',
    ]
    for (const key of keys) {
      expect(en.create_monitor[key], `en.create_monitor.${key}`).toBeTruthy()
      expect(fr.create_monitor[key], `fr.create_monitor.${key}`).toBeTruthy()
      expect(fr.create_monitor[key]).not.toBe(en.create_monitor[key])
    }
  })
})
