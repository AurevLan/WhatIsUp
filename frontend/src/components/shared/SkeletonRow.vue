<template>
  <div class="skeleton-row" role="status" aria-busy="true" aria-label="Loading row">
    <SkeletonBox v-if="circle" circle :height="circleSize" />
    <div class="flex-1 space-y-1.5">
      <SkeletonBox width="60%" height="0.7rem" />
      <SkeletonBox width="40%" height="0.6rem" />
    </div>
    <SkeletonBox v-if="trailing" :width="trailingWidth" height="0.7rem" />
  </div>
</template>

<script setup>
import SkeletonBox from './SkeletonBox.vue'

defineProps({
  circle: { type: Boolean, default: true },
  circleSize: { type: String, default: '2rem' },
  trailing: { type: Boolean, default: true },
  trailingWidth: { type: String, default: '4rem' },
})
</script>
