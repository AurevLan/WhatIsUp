<template>
  <div
    class="skeleton"
    :class="{ 'skeleton-circle': circle }"
    :style="style"
    role="status"
    aria-busy="true"
    :aria-label="ariaLabel"
  />
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  width: { type: [String, Number], default: '100%' },
  height: { type: [String, Number], default: '1rem' },
  rounded: { type: String, default: 'sm' },
  circle: { type: Boolean, default: false },
  ariaLabel: { type: String, default: 'Loading' },
})

const radiusMap = {
  none: '0',
  sm: 'var(--radius-sm, 0.25rem)',
  md: '0.5rem',
  lg: '0.75rem',
  full: '9999px',
}

function toCss(v) {
  return typeof v === 'number' ? `${v}px` : v
}

const style = computed(() => {
  if (props.circle) {
    const size = toCss(props.width === '100%' ? props.height : props.width)
    return { width: size, height: size, borderRadius: '50%' }
  }
  return {
    width: toCss(props.width),
    height: toCss(props.height),
    borderRadius: radiusMap[props.rounded] ?? props.rounded,
  }
})
</script>
