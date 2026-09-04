import { describe, it, expect, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import NetworkVerdictBadge from '../src/components/shared/NetworkVerdictBadge.vue'

vi.mock('vue-i18n', () => ({
  useI18n: () => ({ t: (k) => k }),
}))

function render(props) {
  return mount(NetworkVerdictBadge, { props })
}

describe('NetworkVerdictBadge', () => {
  it.each([
    ['service_down', 'verdict-badge--service'],
    ['network_partition_asn', 'verdict-badge--asn'],
    ['network_partition_geo', 'verdict-badge--geo'],
    ['inconclusive', 'verdict-badge--inconclusive'],
  ])('renders the %s verdict with its class', (verdict, cls) => {
    const w = render({ verdict })
    expect(w.find('.verdict-badge').exists()).toBe(true)
    expect(w.classes()).toContain(cls)
  })

  it('renders nothing for a null verdict (most historical incidents)', () => {
    expect(render({ verdict: null }).find('.verdict-badge').exists()).toBe(false)
  })

  it('renders nothing for an unknown verdict string', () => {
    expect(render({ verdict: 'something_new' }).find('.verdict-badge').exists()).toBe(false)
  })

  it('always exposes a full explanation via aria-label, not title=', () => {
    const w = render({ verdict: 'network_partition_asn' })
    expect(w.attributes('title')).toBeUndefined()
    const label = w.attributes('aria-label')
    expect(label).toContain('incidents.verdict_short_partition_asn')
    expect(label).toContain('incidents.verdict_partition_asn_tip')
  })
})
