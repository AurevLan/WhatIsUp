<template>
  <router-link :to="to" custom v-slot="{ isActive, isExactActive, navigate }">
    <button
      @click="navigate"
      class="nav-link"
      :class="{ 'nav-link--active': activeState(isActive, isExactActive) }"
    >
      <component :is="icon" :size="14" :stroke-width="activeState(isActive, isExactActive) ? 2.5 : 1.8" class="nav-link__icon" />
      <span class="nav-link__label">{{ label }}</span>
      <span v-if="badge" class="nav-link__badge">{{ badge > 99 ? '99+' : badge }}</span>
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

<style scoped>
.nav-link {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 5px 8px;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 500;
  font-family: inherit;
  color: var(--text-3);
  background: transparent;
  border: none;
  cursor: pointer;
  width: 100%;
  text-align: left;
  transition: color .15s, background .15s;
  position: relative;
}

.nav-link:hover {
  color: var(--text-2);
  background: rgba(255,255,255,.04);
}

.nav-link--active {
  color: #7cbcff;
  background: rgba(79,156,249,.1);
  font-weight: 600;
}
.nav-link--active:hover {
  color: #93caff;
  background: rgba(79,156,249,.14);
}

.nav-link__icon {
  flex-shrink: 0;
  opacity: .9;
}

.nav-link__label {
  flex: 1;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.nav-link__badge {
  min-width: 17px;
  height: 17px;
  border-radius: 99px;
  background: #ef4444;
  color: white;
  font-size: 9.5px;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 0 4px;
  flex-shrink: 0;
  letter-spacing: .01em;
}
</style>
