<template>
  <time v-if="valid" :datetime="isoValue" :title="absoluteLabel">{{ display }}</time>
  <span v-else>—</span>
</template>

<script setup>
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useTimezone } from '../../composables/useTimezone'

const props = defineProps({
  value: { type: [String, Number, Date], default: null },
  // 'datetime' (short date + time), 'date', 'time', 'relative'
  format: { type: String, default: 'datetime' },
})

const { locale } = useI18n()
const { format: tzFormat, formatRelative, formatAbsolute } = useTimezone()

const date = computed(() => {
  if (props.value == null) return null
  const d = props.value instanceof Date ? props.value : new Date(props.value)
  return Number.isNaN(d.getTime()) ? null : d
})
const valid = computed(() => date.value != null)

const isoValue = computed(() => (date.value ? date.value.toISOString() : ''))

const display = computed(() => {
  if (!date.value) return ''
  switch (props.format) {
    case 'date':
      return tzFormat(date.value, { year: 'numeric', month: 'short', day: 'numeric' }, locale.value)
    case 'time':
      return tzFormat(date.value, { hour: '2-digit', minute: '2-digit' }, locale.value)
    case 'relative':
      return formatRelative(date.value, locale.value)
    case 'datetime':
    default:
      return tzFormat(
        date.value,
        { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' },
        locale.value,
      )
  }
})

// Tooltip always shows the absolute ISO + timezone for disambiguation.
const absoluteLabel = computed(() => formatAbsolute(date.value, locale.value))
</script>
