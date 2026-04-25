<template>
  <Transition name="bulk-bar">
    <div
      v-if="count > 0"
      class="bulk-bar"
      role="region"
      :aria-label="$t('bulk.bar_aria')"
    >
      <span class="bulk-bar__count">{{ $t('bulk.n_selected', { n: count }) }}</span>
      <slot />
      <button
        type="button"
        class="bulk-bar__clear"
        @click="$emit('clear')"
      >{{ $t('bulk.deselect_all') }}</button>
    </div>
  </Transition>
</template>

<script setup>
defineProps({
  count: { type: Number, required: true },
})
defineEmits(['clear'])
</script>

<style scoped>
.bulk-bar {
  margin-bottom: 1rem;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.5rem;
  padding: 0.65rem 0.75rem;
  border-radius: 0.75rem;
  background: rgba(30, 64, 175, 0.18);
  border: 1px solid rgba(96, 165, 250, 0.40);
}
.bulk-bar__count {
  font-size: 0.78rem;
  font-weight: 600;
  color: #93c5fd;
  margin-right: 0.25rem;
}
.bulk-bar__clear {
  margin-left: auto;
  font-size: 0.7rem;
  color: var(--text-3);
  background: transparent;
  border: 0;
  cursor: pointer;
  padding: 0.25rem 0.5rem;
  border-radius: 0.375rem;
}
.bulk-bar__clear:hover { color: var(--text-1); background: rgba(255,255,255,0.05); }

.bulk-bar-enter-active, .bulk-bar-leave-active { transition: opacity 0.15s, transform 0.15s; }
.bulk-bar-enter-from, .bulk-bar-leave-to { opacity: 0; transform: translateY(-4px); }
</style>
