<template>
  <p v-if="hasSplit" class="text-[10px] text-(--text-3) mt-1 tabular-nums">
    <span v-if="stats.internal_uptime_percent !== null && stats.internal_uptime_percent !== undefined">
      <span class="text-(--text-2)">{{ t('monitor_detail.uptime_internal') }}</span>
      <span :class="colorFor(stats.internal_uptime_percent)">
        {{ stats.internal_uptime_percent.toFixed(2) }}%
      </span>
    </span>
    <span
      v-if="stats.external_uptime_percent !== null && stats.external_uptime_percent !== undefined"
      class="ml-2"
    >
      <span class="text-(--text-2)">{{ t('monitor_detail.uptime_external') }}</span>
      <span :class="colorFor(stats.external_uptime_percent)">
        {{ stats.external_uptime_percent.toFixed(2) }}%
      </span>
    </span>
  </p>
</template>

<script setup>
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

const props = defineProps({
  stats: { type: Object, default: null },
})

const { t } = useI18n()

const hasSplit = computed(() => {
  const s = props.stats
  if (!s) return false
  const hasInt = s.internal_uptime_percent !== null && s.internal_uptime_percent !== undefined
  const hasExt = s.external_uptime_percent !== null && s.external_uptime_percent !== undefined
  return hasInt && hasExt
})

function colorFor(pct) {
  if (pct >= 99) return 'text-(--up) ml-1'
  if (pct >= 95) return 'text-(--warn) ml-1'
  return 'text-(--down) ml-1'
}
</script>
