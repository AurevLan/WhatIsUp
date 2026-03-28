<template>
  <Teleport to="body">
    <Transition name="modal">
      <div v-if="open" class="modal-overlay" @click.self="close" @keydown="onKeydown">
        <div class="palette">
          <div class="palette__search">
            <Search :size="16" />
            <input
              ref="inputRef"
              v-model="query"
              placeholder="Search monitors, navigate..."
              @keydown.stop
            />
            <kbd class="palette__kbd">Esc</kbd>
          </div>
          <div class="palette__results">
            <div v-for="(group, gi) in filteredGroups" :key="group.label" class="palette__group">
              <p class="palette__group-label">{{ group.label }}</p>
              <button
                v-for="(item, ii) in group.items"
                :key="item.id"
                class="palette__item"
                :class="{ 'palette__item--active': isActive(gi, ii) }"
                @click="activate(item)"
                @mouseenter="setActive(gi, ii)"
              >
                <component :is="item.icon" :size="15" />
                <span class="palette__item-name">{{ item.name }}</span>
                <span v-if="item.hint" class="palette__hint">{{ item.hint }}</span>
                <ArrowRight :size="12" class="palette__arrow" />
              </button>
            </div>
            <p v-if="totalCount === 0" class="palette__empty">No results</p>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup>
import { ref, computed, watch, nextTick } from 'vue'
import { useRouter } from 'vue-router'
import {
  Search,
  Monitor,
  LayoutDashboard,
  Bell,
  Settings,
  Plus,
  ArrowRight,
  MapPin,
  Clock,
  GitMerge,
  Activity,
  Layers,
  CalendarClock,
} from 'lucide-vue-next'
import { useMonitorStore } from '../stores/monitors'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
})
const emit = defineEmits(['update:modelValue'])

const router = useRouter()
const monitorStore = useMonitorStore()

const open = computed({
  get: () => props.modelValue,
  set: (v) => emit('update:modelValue', v),
})

const query = ref('')
const inputRef = ref(null)
const activeGroup = ref(0)
const activeItem = ref(0)

function close() {
  open.value = false
}

// Reset state when opening
watch(open, (v) => {
  if (v) {
    query.value = ''
    activeGroup.value = 0
    activeItem.value = 0
    nextTick(() => inputRef.value?.focus())
  }
})

// Navigation items
const navItems = [
  { id: 'nav-dashboard',    name: 'Dashboard',        icon: LayoutDashboard, route: '/' },
  { id: 'nav-monitors',     name: 'Monitors',         icon: Activity,        route: '/monitors' },
  { id: 'nav-groups',       name: 'Groups',           icon: Layers,          route: '/groups' },
  { id: 'nav-probes',       name: 'Probes',           icon: MapPin,          route: '/probes' },
  { id: 'nav-alerts',       name: 'Alerts',           icon: Bell,            route: '/alerts' },
  { id: 'nav-maintenance',  name: 'Maintenance',      icon: CalendarClock,   route: '/maintenance' },
  { id: 'nav-incidents',    name: 'Incidents',         icon: Clock,           route: '/incidents' },
  { id: 'nav-incident-groups', name: 'Incident Groups', icon: GitMerge,      route: '/incident-groups' },
  { id: 'nav-settings',     name: 'Settings',         icon: Settings,        route: '/settings' },
]

// Action items
const actionItems = [
  { id: 'action-new-monitor', name: 'New Monitor', icon: Plus, route: '/monitors', query: { create: 'true' }, hint: 'Create' },
]

// Build monitor items from store
const monitorItems = computed(() =>
  monitorStore.monitors.map((m) => ({
    id: `monitor-${m.id}`,
    name: m.name,
    icon: Monitor,
    route: `/monitors/${m.id}`,
    hint: m.check_type,
  }))
)

// Filter helper
function matchesQuery(item, q) {
  return item.name.toLowerCase().includes(q)
}

const filteredGroups = computed(() => {
  const q = query.value.toLowerCase().trim()
  const groups = []

  // Monitors
  const mItems = q
    ? monitorItems.value.filter((i) => matchesQuery(i, q))
    : monitorItems.value.slice(0, 5)
  if (mItems.length > 0) {
    groups.push({ label: 'Monitors', items: mItems })
  }

  // Navigation
  const nItems = q
    ? navItems.filter((i) => matchesQuery(i, q))
    : navItems
  if (nItems.length > 0) {
    groups.push({ label: 'Navigation', items: nItems })
  }

  // Actions
  const aItems = q
    ? actionItems.filter((i) => matchesQuery(i, q))
    : actionItems
  if (aItems.length > 0) {
    groups.push({ label: 'Actions', items: aItems })
  }

  return groups
})

const totalCount = computed(() =>
  filteredGroups.value.reduce((sum, g) => sum + g.items.length, 0)
)

function isActive(gi, ii) {
  return activeGroup.value === gi && activeItem.value === ii
}

function setActive(gi, ii) {
  activeGroup.value = gi
  activeItem.value = ii
}

function clampActive() {
  const groups = filteredGroups.value
  if (groups.length === 0) {
    activeGroup.value = 0
    activeItem.value = 0
    return
  }
  if (activeGroup.value >= groups.length) {
    activeGroup.value = groups.length - 1
  }
  if (activeItem.value >= groups[activeGroup.value].items.length) {
    activeItem.value = groups[activeGroup.value].items.length - 1
  }
}

watch(query, () => {
  activeGroup.value = 0
  activeItem.value = 0
})

function moveDown() {
  const groups = filteredGroups.value
  if (groups.length === 0) return
  let gi = activeGroup.value
  let ii = activeItem.value + 1
  if (ii >= groups[gi].items.length) {
    gi++
    ii = 0
  }
  if (gi < groups.length) {
    activeGroup.value = gi
    activeItem.value = ii
  }
  scrollActiveIntoView()
}

function moveUp() {
  const groups = filteredGroups.value
  if (groups.length === 0) return
  let gi = activeGroup.value
  let ii = activeItem.value - 1
  if (ii < 0) {
    gi--
    if (gi >= 0) {
      ii = groups[gi].items.length - 1
    } else {
      return
    }
  }
  activeGroup.value = gi
  activeItem.value = ii
  scrollActiveIntoView()
}

function scrollActiveIntoView() {
  nextTick(() => {
    const el = document.querySelector('.palette__item--active')
    if (el) el.scrollIntoView({ block: 'nearest' })
  })
}

function activate(item) {
  close()
  if (item.route) {
    const to = item.query ? { path: item.route, query: item.query } : item.route
    router.push(to)
  }
}

function activateCurrent() {
  clampActive()
  const groups = filteredGroups.value
  if (groups.length === 0) return
  const item = groups[activeGroup.value]?.items[activeItem.value]
  if (item) activate(item)
}

function onKeydown(e) {
  if (e.key === 'Escape') {
    e.preventDefault()
    close()
  } else if (e.key === 'ArrowDown') {
    e.preventDefault()
    moveDown()
  } else if (e.key === 'ArrowUp') {
    e.preventDefault()
    moveUp()
  } else if (e.key === 'Enter') {
    e.preventDefault()
    activateCurrent()
  }
}
</script>

<style scoped>
.palette {
  width: 100%;
  max-width: 540px;
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.5), 0 0 0 1px rgba(255, 255, 255, 0.03);
  overflow: hidden;
  margin-top: -8vh;
}

.palette__search {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 16px;
  border-bottom: 1px solid var(--border);
  color: var(--text-3);
}

.palette__search input {
  flex: 1;
  background: none;
  border: none;
  outline: none;
  color: var(--text-1);
  font-size: 14px;
  font-family: inherit;
}

.palette__search input::placeholder {
  color: var(--text-3);
}

.palette__kbd {
  font-size: 10px;
  font-family: inherit;
  color: var(--text-3);
  background: var(--bg-base);
  border: 1px solid var(--border);
  border-radius: 4px;
  padding: 1px 6px;
  line-height: 1.6;
  flex-shrink: 0;
}

.palette__results {
  max-height: 360px;
  overflow-y: auto;
  padding: 6px 0;
}

.palette__group {
  padding: 0 6px;
}

.palette__group + .palette__group {
  margin-top: 4px;
}

.palette__group-label {
  font-size: 10.5px;
  font-weight: 600;
  color: var(--text-3);
  text-transform: uppercase;
  letter-spacing: 0.04em;
  padding: 6px 10px 4px;
}

.palette__item {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  padding: 8px 10px;
  border: none;
  background: none;
  color: var(--text-2);
  font-size: 13px;
  font-family: inherit;
  border-radius: calc(var(--radius) - 2px);
  cursor: pointer;
  text-align: left;
  transition: background 0.1s, color 0.1s;
}

.palette__item:hover,
.palette__item--active {
  background: rgba(59, 130, 246, 0.08);
  color: var(--text-1);
}

.palette__item--active {
  background: rgba(59, 130, 246, 0.12);
}

.palette__item-name {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.palette__hint {
  font-size: 11px;
  color: var(--text-3);
  flex-shrink: 0;
}

.palette__arrow {
  color: var(--text-3);
  opacity: 0;
  flex-shrink: 0;
  transition: opacity 0.1s;
}

.palette__item--active .palette__arrow,
.palette__item:hover .palette__arrow {
  opacity: 1;
}

.palette__empty {
  padding: 24px 16px;
  text-align: center;
  color: var(--text-3);
  font-size: 13px;
}

/* Transition (inherits from global modal-overlay transition) */
.modal-enter-active { transition: opacity 0.15s ease; }
.modal-leave-active { transition: opacity 0.12s ease; }
.modal-enter-from, .modal-leave-to { opacity: 0; }
.modal-enter-active .palette { animation: palette-in 0.15s ease-out; }
.modal-leave-active .palette { animation: palette-out 0.12s ease-in; }
@keyframes palette-in {
  from { opacity: 0; transform: scale(0.97) translateY(-8px); }
  to   { opacity: 1; transform: scale(1) translateY(0); }
}
@keyframes palette-out {
  from { opacity: 1; transform: scale(1) translateY(0); }
  to   { opacity: 0; transform: scale(0.97) translateY(-8px); }
}
</style>
