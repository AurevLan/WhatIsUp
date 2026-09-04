<template>
  <span v-if="cfg" class="verdict-badge" :class="cfg.cls" :aria-label="fullLabel">{{ shortLabel }}</span>
</template>

<script setup>
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { verdictInfo } from '../../lib/networkVerdict'

// Reusable network-verdict badge (plan_cap_v2 §3a) — the same information
// IncidentsView used to render inline, now shared by the incident list, the
// monitor list, the dashboard and the monitor detail page. Renders nothing
// for a null/unknown verdict (the majority of historical incidents — computed
// before V2-02-02, or never classified) to avoid an empty case everywhere
// it's dropped in.
//
// Accessibility: the short label is a compact shorthand ("Carrier", "ASN"
// used to say nothing to a user); the full sentence explanation is always
// exposed via `aria-label`, read by assistive tech regardless of hover,
// focus, or touch — unlike the `title=` attribute this replaces, which never
// fires on a touchscreen (plan_cap_v2 §3a).
const props = defineProps({
  verdict: { type: String, default: null },
})

const { t } = useI18n()

const cfg = computed(() => verdictInfo(props.verdict))
const shortLabel = computed(() => (cfg.value ? t(cfg.value.labelKey) : ''))
const fullLabel = computed(() =>
  cfg.value ? `${shortLabel.value} — ${t(cfg.value.explainKey)}` : '',
)
</script>

<style scoped>
.verdict-badge {
  display: inline-flex;
  align-items: center;
  margin-left: 4px;
  padding: 2px 8px;
  border-radius: 99px;
  font-size: 0.58rem;
  font-weight: 700;
  letter-spacing: 0.03em;
  text-transform: uppercase;
  white-space: nowrap;
  line-height: 1.5;
}
.verdict-badge--service {
  background: color-mix(in srgb, var(--down) 12%, transparent);
  color: var(--down);
  border: 1px solid color-mix(in srgb, var(--down) 25%, transparent);
}
.verdict-badge--asn,
.verdict-badge--geo {
  background: color-mix(in srgb, var(--accent) 12%, transparent);
  color: var(--accent);
  border: 1px solid color-mix(in srgb, var(--accent) 25%, transparent);
}
.verdict-badge--inconclusive {
  background: color-mix(in srgb, var(--text-3) 12%, transparent);
  color: var(--text-3);
  border: 1px solid color-mix(in srgb, var(--text-3) 25%, transparent);
}
</style>
