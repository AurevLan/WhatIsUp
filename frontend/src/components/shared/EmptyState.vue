<template>
  <div class="empty-state" :class="{ 'empty-state--inline': inline }">
    <div class="empty-state__icon">
      <slot name="icon">
        <Inbox :size="22" />
      </slot>
    </div>

    <p class="empty-state__title">{{ title }}</p>
    <p v-if="text" class="empty-state__text">{{ text }}</p>

    <div v-if="$slots.cta || ctaLabel || docHref || replayTour" class="empty-state__actions">
      <slot name="cta">
        <button
          v-if="ctaLabel"
          type="button"
          class="btn-primary"
          @click="$emit('cta')"
        >
          <Plus v-if="ctaIcon !== false" :size="14" />
          {{ ctaLabel }}
        </button>
      </slot>

      <a
        v-if="docHref"
        :href="docHref"
        target="_blank"
        rel="noopener noreferrer"
        class="empty-state__link"
      >
        <BookOpen :size="13" />
        {{ docLabel || $t('common.read_docs') }}
      </a>

      <button
        v-if="replayTour"
        type="button"
        class="empty-state__link"
        @click="onReplay"
      >
        <PlayCircle :size="13" />
        {{ $t('tour.replay') }}
      </button>
    </div>
  </div>
</template>

<script setup>
import { Inbox, Plus, BookOpen, PlayCircle } from 'lucide-vue-next'
import { useTour } from '../../composables/useTour'

defineProps({
  title: { type: String, required: true },
  text: { type: String, default: '' },
  ctaLabel: { type: String, default: '' },
  ctaIcon: { type: Boolean, default: true },
  docHref: { type: String, default: '' },
  docLabel: { type: String, default: '' },
  replayTour: { type: Boolean, default: false },
  inline: { type: Boolean, default: false },
})

defineEmits(['cta'])

const { requestTour } = useTour()

function onReplay() {
  requestTour()
}
</script>

<style scoped>
.empty-state__actions {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  flex-wrap: wrap;
  justify-content: center;
  margin-top: 0.25rem;
}
.empty-state__link {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  font-size: 0.8125rem;
  color: var(--text-3);
  background: transparent;
  border: 0;
  padding: 0.35rem 0.5rem;
  cursor: pointer;
  border-radius: 0.375rem;
  transition: color 0.15s, background 0.15s;
}
.empty-state__link:hover { color: var(--text-1); background: var(--bg-surface-2); }

.empty-state--inline {
  padding: 1.25rem 1rem;
}
</style>
