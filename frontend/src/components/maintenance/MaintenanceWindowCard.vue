<template>
  <div class="flex items-start justify-between gap-4">
    <!-- Left: info -->
    <div class="flex-1 min-w-0">
      <div class="flex items-center gap-2 flex-wrap">
        <h3 class="font-semibold text-(--text-1)">{{ w.name }}</h3>
        <span class="text-xs px-2 py-0.5 rounded-full" :class="statusBadgeClass">
          {{ statusLabel }}
        </span>
      </div>
      <p v-if="w.description" class="text-sm text-(--text-3) mt-1 truncate">{{ w.description }}</p>
      <div class="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-(--text-3)">
        <span>{{ formatDt(w.starts_at) }} → {{ formatDt(w.ends_at) }}</span>
        <span v-if="monitorObj" class="flex items-center gap-1">
          <span class="w-1.5 h-1.5 rounded-full bg-(--accent)" />
          <span class="text-(--accent)">{{ monitorObj.name }}</span>
        </span>
        <span v-if="!w.suppress_alerts" class="text-(--warn)">⚠ {{ t('maintenance.alerts_not_suppressed') }}</span>
      </div>
    </div>

    <!-- Right: actions -->
    <div class="flex items-center gap-1 shrink-0">
      <button @click="$emit('edit', w)" class="btn-icon" :title="t('common.edit')">
        <Pencil :size="13" />
      </button>
      <button @click="$emit('delete', w)" class="btn-icon text-(--down)" :title="t('common.delete')">
        <Trash2 :size="13" />
      </button>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { Trash2, Pencil } from 'lucide-vue-next'

const props = defineProps({
  w:        { type: Object, required: true },
  monitors: { type: Array,  default: () => [] },
})

defineEmits(['delete', 'edit'])

const { t } = useI18n()

const monitorObj = computed(() =>
  props.w.monitor_id ? props.monitors.find(m => m.id === props.w.monitor_id) : null
)

const status = computed(() => {
  const now   = new Date()
  const start = new Date(props.w.starts_at)
  const end   = new Date(props.w.ends_at)
  if (start <= now && end >= now) return 'active'
  if (start > now) return 'scheduled'
  return 'completed'
})

const statusBadgeClass = computed(() => ({
  active:    'bg-[color-mix(in_srgb,var(--warn)_15%,transparent)] text-(--warn)',
  scheduled: 'bg-(--accent-glow) text-(--accent)',
  completed: 'bg-(--bg-surface-2) text-(--text-3)',
}[status.value]))

const statusLabel = computed(() => ({
  active:    t('maintenance.status_active'),
  scheduled: t('maintenance.status_scheduled'),
  completed: t('maintenance.status_completed'),
}[status.value]))

function formatDt(dt) {
  return new Date(dt).toLocaleString(undefined, {
    month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
  })
}
</script>
