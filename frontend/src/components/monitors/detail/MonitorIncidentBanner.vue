<template>
  <div v-if="incident" class="card mb-6 inc-banner">
    <div class="inc-banner__head">
      <NetworkVerdictBadge :verdict="incident.network_verdict" />
      <span class="inc-banner__since">
        {{ t('monitor_detail.incident_banner_since', { date: fmtDate(incident.started_at) }) }}
      </span>
    </div>
    <p v-if="errorMessage" class="inc-banner__error">{{ errorMessage }}</p>
    <p v-if="verdictExplanation" class="inc-banner__explain">{{ verdictExplanation }}</p>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { verdictInfo } from '../../../lib/networkVerdict'
import NetworkVerdictBadge from '../../shared/NetworkVerdictBadge.vue'

// plan_cap_v2 §3a — "the fiche moniteur reunites the two halves of the
// answer". A product review measured the "why is it down?" path at 3 clicks,
// 2 views, ~8 screens of scrolling — error_message (MonitorRecentChecksTable)
// and the network verdict were never on the same screen. This banner puts
// both at the top of the page, visible with zero clicks, only while the
// monitor is actually down.
//
// The full sentence explanation is rendered as plain, always-visible text
// here (not hidden behind hover/focus like the compact badge elsewhere) —
// this page IS the place a user lands to get the full context.
const props = defineProps({
  incident: { type: Object, default: null },
  errorMessage: { type: String, default: null },
  formatDateTime: { type: Function, required: true },
})

const { t } = useI18n()

function fmtDate(v) {
  return props.formatDateTime(v)
}

const verdictExplanation = computed(() => {
  if (!props.incident) return null
  const info = verdictInfo(props.incident.network_verdict)
  return info ? t(info.explainKey) : null
})
</script>

<style scoped>
.inc-banner {
  border-left: 3px solid var(--down);
}
.inc-banner__head {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  flex-wrap: wrap;
}
.inc-banner__since {
  font-size: 0.8rem;
  color: var(--text-3);
}
.inc-banner__error {
  margin-top: 0.6rem;
  font-family: var(--font-mono, monospace);
  font-size: 0.8rem;
  color: var(--down);
  word-break: break-word;
}
.inc-banner__explain {
  margin-top: 0.4rem;
  font-size: 0.82rem;
  color: var(--text-2);
}
</style>
