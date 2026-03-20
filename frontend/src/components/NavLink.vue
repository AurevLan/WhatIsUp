<template>
  <router-link :to="to" custom v-slot="{ isActive, isExactActive, navigate }">
    <button
      @click="navigate"
      :style="{
        display: 'flex',
        alignItems: 'center',
        gap: '10px',
        padding: '8px 10px',
        borderRadius: '8px',
        fontSize: '13px',
        fontWeight: activeState(isActive, isExactActive) ? '600' : '500',
        color: activeState(isActive, isExactActive) ? '#60a5fa' : '#64748b',
        background: activeState(isActive, isExactActive) ? 'rgba(59,130,246,.12)' : 'transparent',
        border: 'none',
        cursor: 'pointer',
        width: '100%',
        textAlign: 'left',
        transition: 'all .15s',
      }"
      onmouseenter="if(!this.dataset.active){this.style.background='rgba(255,255,255,.04)';this.style.color='#94a3b8';}"
      onmouseleave="if(!this.dataset.active){this.style.background='transparent';this.style.color='#64748b';}"
      :data-active="activeState(isActive, isExactActive) || null"
    >
      <component :is="icon" :size="15" :stroke-width="activeState(isActive, isExactActive) ? 2.5 : 2" />
      <span style="flex:1;">{{ label }}</span>
      <span v-if="badge"
        style="min-width:18px;height:18px;border-radius:9px;background:#ef4444;color:white;font-size:10px;font-weight:700;display:flex;align-items:center;justify-content:center;padding:0 5px;flex-shrink:0;"
      >{{ badge > 99 ? '99+' : badge }}</span>
    </button>
  </router-link>
</template>

<script setup>
const props = defineProps({
  to: String,
  icon: [Object, Function],
  label: String,
  exact: { type: Boolean, default: false },
  badge: { type: Number, default: 0 },
})

function activeState(isActive, isExactActive) {
  return props.exact ? isExactActive : isActive
}
</script>
