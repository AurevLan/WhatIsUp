<template>
  <Teleport to="body">
    <Transition name="modal">
      <div v-if="open" class="modal-overlay" @click.self="close">
        <div class="hotkeys-card">
          <header class="hotkeys-card__head">
            <h2>{{ $t('hotkeys.title') }}</h2>
            <button class="hotkeys-card__close" @click="close" :aria-label="$t('common.close')">
              <X :size="14" />
            </button>
          </header>

          <div class="hotkeys-card__body">
            <section v-for="group in groups" :key="group.label">
              <h3>{{ group.label }}</h3>
              <ul>
                <li v-for="row in group.rows" :key="row.keys">
                  <span class="hotkeys-card__label">{{ row.label }}</span>
                  <span class="hotkeys-card__keys">
                    <kbd v-for="(k, i) in row.keys.split(' ')" :key="i" class="kbd">{{ formatKey(k) }}</kbd>
                  </span>
                </li>
              </ul>
            </section>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup>
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { X } from 'lucide-vue-next'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
})
const emit = defineEmits(['update:modelValue'])

const { t } = useI18n()

const open = computed({
  get: () => props.modelValue,
  set: (v) => emit('update:modelValue', v),
})

function close() { open.value = false }

function formatKey(k) {
  if (k === 'mod') return navigator.platform.toUpperCase().includes('MAC') ? '⌘' : 'Ctrl'
  if (k === 'space') return '␣'
  return k
}

const groups = computed(() => [
  {
    label: t('hotkeys.section_navigation'),
    rows: [
      { keys: 'g d', label: t('hotkeys.go_dashboard') },
      { keys: 'g m', label: t('hotkeys.go_monitors') },
      { keys: 'g i', label: t('hotkeys.go_incidents') },
      { keys: 'g a', label: t('hotkeys.go_alerts') },
      { keys: 'g p', label: t('hotkeys.go_probes') },
      { keys: 'g s', label: t('hotkeys.go_settings') },
    ],
  },
  {
    label: t('hotkeys.section_actions'),
    rows: [
      { keys: 'mod k', label: t('hotkeys.open_palette') },
      { keys: '/', label: t('hotkeys.open_palette') },
      { keys: 'c', label: t('hotkeys.create_monitor') },
      { keys: '?', label: t('hotkeys.show_cheatsheet') },
    ],
  },
])
</script>

<style scoped>
.hotkeys-card {
  width: 100%;
  max-width: 460px;
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  box-shadow: 0 20px 60px rgba(0,0,0,.5);
  overflow: hidden;
  margin-top: -8vh;
}
.hotkeys-card__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  border-bottom: 1px solid var(--border);
}
.hotkeys-card__head h2 {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-1);
  margin: 0;
}
.hotkeys-card__close {
  background: none;
  border: 0;
  color: var(--text-3);
  cursor: pointer;
  padding: 4px;
  border-radius: 4px;
}
.hotkeys-card__close:hover { background: var(--bg-surface-2); color: var(--text-1); }
.hotkeys-card__body {
  padding: 12px 16px 18px;
  max-height: 60vh;
  overflow-y: auto;
}
.hotkeys-card__body section + section { margin-top: 14px; }
.hotkeys-card__body h3 {
  font-size: 10.5px;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--text-3);
  margin: 0 0 6px;
  font-weight: 600;
}
.hotkeys-card__body ul { list-style: none; padding: 0; margin: 0; }
.hotkeys-card__body li {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 6px 0;
  font-size: 12.5px;
  color: var(--text-2);
}
.hotkeys-card__keys {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
</style>
