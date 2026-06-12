<template>
  <div class="card-sm flex items-center gap-4">
    <div class="w-10 h-10 rounded-xl flex items-center justify-center flex-shrink-0" :class="iconBg">
      <component :is="icon" class="w-5 h-5" :class="iconColor" />
    </div>
    <div class="min-w-0">
      <p class="text-xs text-(--text-3) font-medium uppercase tracking-wide truncate">{{ label }}</p>
      <p class="text-2xl font-bold font-display mt-0.5" :class="valueColor">{{ value }}</p>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  label: { type: String, required: true },
  value: { type: [Number, String], default: null },
  color: { type: String, default: 'blue' },
  icon: { type: Object, required: true },
})

const palettes = {
  blue:    { bg: 'bg-(--accent-glow)',    icon: 'text-(--accent)',    value: 'text-(--accent)' },
  emerald: { bg: 'bg-[color-mix(in_srgb,var(--up)_10%,transparent)]', icon: 'text-(--up)', value: 'text-(--up)' },
  red:     { bg: 'bg-[color-mix(in_srgb,var(--down)_10%,transparent)]',     icon: 'text-(--down)',     value: 'text-(--down)' },
  amber:   { bg: 'bg-[color-mix(in_srgb,var(--warn)_10%,transparent)]',   icon: 'text-(--warn)',   value: 'text-(--warn)' },
  gray:    { bg: 'bg-(--bg-surface-2)',    icon: 'text-(--text-2)',    value: 'text-(--text-2)' },
}

const p = computed(() => palettes[props.color] || palettes.blue)
const iconBg    = computed(() => p.value.bg)
const iconColor = computed(() => p.value.icon)
const valueColor = computed(() => p.value.value)
</script>
