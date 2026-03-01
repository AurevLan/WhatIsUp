<template>
  <div class="card-sm flex items-center gap-4">
    <div class="w-10 h-10 rounded-xl flex items-center justify-center flex-shrink-0" :class="iconBg">
      <component :is="icon" class="w-5 h-5" :class="iconColor" />
    </div>
    <div class="min-w-0">
      <p class="text-xs text-gray-500 font-medium uppercase tracking-wide truncate">{{ label }}</p>
      <p class="text-2xl font-bold mt-0.5" :class="valueColor">{{ value }}</p>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  label: String,
  value: [Number, String],
  color: { type: String, default: 'blue' },
  icon: { type: Object, required: true },
})

const palettes = {
  blue:    { bg: 'bg-blue-500/10',    icon: 'text-blue-400',    value: 'text-blue-400' },
  emerald: { bg: 'bg-emerald-500/10', icon: 'text-emerald-400', value: 'text-emerald-400' },
  red:     { bg: 'bg-red-500/10',     icon: 'text-red-400',     value: 'text-red-400' },
  amber:   { bg: 'bg-amber-500/10',   icon: 'text-amber-400',   value: 'text-amber-400' },
  gray:    { bg: 'bg-gray-500/10',    icon: 'text-gray-400',    value: 'text-gray-400' },
}

const p = computed(() => palettes[props.color] || palettes.blue)
const iconBg    = computed(() => p.value.bg)
const iconColor = computed(() => p.value.icon)
const valueColor = computed(() => p.value.value)
</script>
