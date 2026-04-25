<template>
  <div class="space-y-2" role="status" aria-busy="true" :aria-label="ariaLabel">
    <SkeletonBox
      v-for="(w, i) in widths"
      :key="i"
      :width="w"
      :height="lineHeight"
      :aria-label="undefined"
    />
  </div>
</template>

<script setup>
import { computed } from 'vue'
import SkeletonBox from './SkeletonBox.vue'

const props = defineProps({
  lines: { type: Number, default: 3 },
  lineHeight: { type: String, default: '0.75rem' },
  ariaLabel: { type: String, default: 'Loading' },
})

const widths = computed(() => {
  const arr = []
  for (let i = 0; i < props.lines; i++) {
    if (i === props.lines - 1 && props.lines > 1) arr.push('60%')
    else arr.push('100%')
  }
  return arr
})
</script>
