<template>
  <router-link :to="to" custom v-slot="{ href, isActive, isExactActive, navigate }">
    <a
      :href="href"
      @click="onClick($event, navigate)"
      class="nav-link"
      :class="{ 'nav-link--active': activeState(isActive, isExactActive) }"
    >
      <component :is="icon" :size="14" :stroke-width="activeState(isActive, isExactActive) ? 2.5 : 1.8" class="nav-link__icon" />
      <span class="nav-link__label">{{ label }}</span>
      <span v-if="badge" class="nav-link__badge">{{ badge > 99 ? '99+' : badge }}</span>
    </a>
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
function onClick(ev, navigate) {
  // Preserve native link behavior (middle-click / ctrl-click open in new tab)
  // by only hijacking plain left-clicks.
  if (ev.defaultPrevented) return
  if (ev.button !== 0) return
  if (ev.metaKey || ev.ctrlKey || ev.shiftKey || ev.altKey) return
  ev.preventDefault()
  navigate(ev)
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
  text-decoration: none;
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

/* Mobile: bigger touch targets and label so the drawer is comfortable to tap */
@media (max-width: 1023px) {
  .nav-link {
    padding: 12px 12px;
    font-size: 14px;
    gap: 12px;
    border-radius: 8px;
    min-height: 44px;
    -webkit-tap-highlight-color: transparent;
  }
  .nav-link__icon { width: 18px; height: 18px; }
  .nav-link__badge {
    min-width: 22px;
    height: 22px;
    font-size: 11px;
  }
}
</style>
