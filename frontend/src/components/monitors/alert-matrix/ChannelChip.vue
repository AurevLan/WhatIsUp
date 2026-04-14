<template>
  <button
    type="button"
    @click="$emit('toggle')"
    class="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-medium border transition-all"
    :class="[
      active ? styles.activeClass : styles.inactiveClass,
      removable ? 'pr-1.5' : '',
    ]"
    :style="active ? styles.activeStyle : ''"
    :title="channel.name"
  >
    <span class="w-1.5 h-1.5 rounded-full" :style="`background:${styles.dot}`"></span>
    <span>{{ channel.name }}</span>
    <span v-if="active && removable" class="opacity-60 hover:opacity-100 text-[10px] pl-0.5">✕</span>
  </button>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  channel: { type: Object, required: true },
  active: { type: Boolean, default: false },
  removable: { type: Boolean, default: true },
})
defineEmits(['toggle'])

const PALETTE = {
  slack:     { dot: '#7c3aed', bg: 'rgba(124,58,237,0.15)', border: 'rgba(124,58,237,0.6)', text: '#c4b5fd' },
  pagerduty: { dot: '#dc2626', bg: 'rgba(220,38,38,0.15)',  border: 'rgba(220,38,38,0.6)',  text: '#fca5a5' },
  opsgenie:  { dot: '#f97316', bg: 'rgba(249,115,22,0.15)', border: 'rgba(249,115,22,0.6)', text: '#fdba74' },
  telegram:  { dot: '#06b6d4', bg: 'rgba(6,182,212,0.15)',  border: 'rgba(6,182,212,0.6)',  text: '#67e8f9' },
  email:     { dot: '#9ca3af', bg: 'rgba(156,163,175,0.15)',border: 'rgba(156,163,175,0.6)',text: '#d1d5db' },
  webhook:   { dot: '#f59e0b', bg: 'rgba(245,158,11,0.15)', border: 'rgba(245,158,11,0.6)', text: '#fcd34d' },
  signal:    { dot: '#3b82f6', bg: 'rgba(59,130,246,0.15)', border: 'rgba(59,130,246,0.6)', text: '#93c5fd' },
  fcm:       { dot: '#ec4899', bg: 'rgba(236,72,153,0.15)', border: 'rgba(236,72,153,0.6)', text: '#f9a8d4' },
}

const styles = computed(() => {
  const p = PALETTE[props.channel.type] ?? PALETTE.email
  return {
    dot: p.dot,
    activeStyle: `background:${p.bg};border-color:${p.border};color:${p.text};`,
    activeClass: '',
    inactiveClass: 'border-gray-700 text-gray-500 hover:text-gray-300 hover:border-gray-500 bg-transparent',
  }
})
</script>
