<template>
  <router-link :to="to" custom v-slot="{ href, isActive, isExactActive }">
    <a
      :href="href"
      @click="onClick($event)"
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
import { useRouter } from 'vue-router'

const props = defineProps({
  to: { type: String, required: true },
  icon: { type: [Object, Function], default: null },
  label: { type: String, required: true },
  exact: { type: Boolean, default: false },
  badge: { type: Number, default: 0 },
})

const router = useRouter()

function activeState(isActive, isExactActive) {
  return props.exact ? isExactActive : isActive
}
function onClick(ev) {
  // Preserve native link behavior (middle-click / ctrl-click open in new tab)
  // by only hijacking plain left-clicks.
  if (ev.defaultPrevented) return
  if (ev.button !== 0) return
  if (ev.metaKey || ev.ctrlKey || ev.shiftKey || ev.altKey) return
  ev.preventDefault()
  router.push(props.to)
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
  background: var(--bg-surface-2);
}

.nav-link--active {
  color: var(--accent);
  background: var(--accent-glow);
  font-weight: 600;
}
.nav-link--active:hover {
  color: var(--accent);
  background: color-mix(in srgb, var(--accent) 20%, transparent);
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
  background: var(--down);
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
