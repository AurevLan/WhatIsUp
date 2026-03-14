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
      {{ label }}
    </button>
  </router-link>
</template>

<script setup>
const props = defineProps({ to: String, icon: [Object, Function], label: String, exact: { type: Boolean, default: false } })

function activeState(isActive, isExactActive) {
  return props.exact ? isExactActive : isActive
}
</script>
