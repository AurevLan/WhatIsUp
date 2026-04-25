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
              <div class="palette__group-header">
                <p class="palette__group-label">
                  <History v-if="group.label === 'Recent'" :size="10" />
                  {{ group.label }}
                </p>
                <button
                  v-if="group.label === 'Recent'"
                  type="button"
                  class="palette__group-clear"
                  @click="clearRecents"
                  title="Clear recents"
                >
                  <X :size="11" />
                </button>
              </div>
              <button
                v-for="(item, ii) in group.items"
                :key="item.id"
                class="palette__item"
                :class="{ 'palette__item--active': isActive(gi, ii) }"
                @click="activate(item)"
                @mouseenter="setActive(gi, ii)"
              >
                <component :is="item.icon" :size="14" />
                <span class="palette__item-name">{{ item.name }}</span>
                <span v-if="item.status && item.status !== 'up'" class="palette__status-dot" :class="`palette__status-dot--${item.status}`" />
                <span v-if="item.hint" class="palette__hint">{{ item.hint }}</span>

                <!-- Inline actions on hover/active -->
                <span
                  v-if="item.kind === 'monitor'"
                  class="palette__action-btn"
                  :title="item.enabled ? 'Pause' : 'Resume'"
                  @click="togglePauseFromItem(item, $event)"
                >
                  <Pause v-if="item.enabled" :size="11" />
                  <Play v-else :size="11" />
                </span>
                <span
                  v-else-if="item.kind === 'incident'"
                  class="palette__action-btn"
                  title="Acknowledge"
                  @click="ackIncidentFromItem(item, $event)"
                >
                  <CheckCheck :size="11" />
                </span>

                <ArrowRight :size="11" class="palette__arrow" />
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
  Sun,
  Moon,
  Globe,
  Zap,
  Copy,
  KeyRound,
  ClipboardList,
  Play,
  Pause,
  CheckCheck,
  History,
  AlertCircle,
  X,
} from 'lucide-vue-next'
import { useMonitorStore } from '../stores/monitors'
import { useCommandPaletteStore } from '../stores/commandPalette'
import { useToast } from '../composables/useToast'
import { incidentUpdatesApi } from '../api/incidentUpdates'
import { fuzzyFilter } from '../lib/fuzzy'
import { setLocale, getLocale } from '../i18n/index.js'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
})
const emit = defineEmits(['update:modelValue'])

const router = useRouter()
const monitorStore = useMonitorStore()
const paletteStore = useCommandPaletteStore()
const { success: toastSuccess, error: toastError } = useToast()

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
  { id: 'nav-templates',    name: 'Templates',         icon: Copy,           route: '/templates' },
  { id: 'nav-api-keys',     name: 'API Keys',          icon: KeyRound,       route: '/api-keys' },
  { id: 'nav-audit',        name: 'Audit Log',         icon: ClipboardList,  route: '/audit' },
  { id: 'nav-settings',     name: 'Settings',         icon: Settings,        route: '/settings' },
]

// Action items
const actionItems = computed(() => [
  { id: 'action-new-monitor', name: 'New Monitor', icon: Plus, route: '/monitors', query: { create: 'true' }, hint: 'Create' },
  { id: 'action-toggle-theme', name: isDark.value ? 'Switch to Light Mode' : 'Switch to Dark Mode', icon: isDark.value ? Sun : Moon, action: 'toggle-theme', hint: 'Theme' },
  { id: 'action-toggle-lang', name: currentLang.value === 'en' ? 'Passer en Français' : 'Switch to English', icon: Globe, action: 'toggle-lang', hint: currentLang.value === 'en' ? 'FR' : 'EN' },
])

// Theme / Lang state for actions
const isDark = ref(document.documentElement.getAttribute('data-theme') !== 'light')
const currentLang = ref(getLocale())

// Build monitor items from store — down monitors first
const STATUS_PRIORITY = { down: 0, error: 1, timeout: 2, up: 3 }
const monitorItems = computed(() =>
  [...monitorStore.monitors]
    .sort((a, b) => (STATUS_PRIORITY[a._lastStatus] ?? 4) - (STATUS_PRIORITY[b._lastStatus] ?? 4))
    .map((m) => ({
      kind: 'monitor',
      raw: m,
      id: `monitor-${m.id}`,
      name: m.name,
      icon: Monitor,
      route: `/monitors/${m.id}`,
      hint: m.check_type,
      status: m._lastStatus,
      enabled: m.enabled,
    }))
)

// Open incidents — derived from monitors carrying an open incident.
const incidentItems = computed(() =>
  monitorStore.monitors
    .filter((m) => m._hasOpenIncident && m._openIncidentId)
    .map((m) => ({
      kind: 'incident',
      raw: m,
      id: `incident-${m._openIncidentId}`,
      name: m.name,
      icon: AlertCircle,
      route: `/monitors/${m.id}`,
      hint: 'open',
      status: 'down',
      incidentId: m._openIncidentId,
    }))
)

// Recents from store, mapped to palette item shape; drop entries whose monitor
// vanished from the store (deleted) so they don't 404.
const recentItems = computed(() => {
  const monitorIds = new Set(monitorStore.monitors.map((m) => m.id))
  return paletteStore.recents
    .filter((r) => r.type !== 'monitor' || monitorIds.has(r.id))
    .map((r) => ({
      kind: 'recent',
      id: `recent-${r.type}-${r.id}`,
      name: r.name,
      icon: r.type === 'incident' ? AlertCircle : Monitor,
      route: r.route,
      hint: r.type,
    }))
})

const filteredGroups = computed(() => {
  const q = query.value.trim()
  const groups = []

  // When idle (no query), surface recents first.
  if (!q && recentItems.value.length > 0) {
    groups.push({ label: 'Recent', items: recentItems.value })
  }

  // Open incidents always come early when there are some.
  const incItems = fuzzyFilter(incidentItems.value, q)
  if (incItems.length > 0) {
    groups.push({ label: 'Open incidents', items: incItems })
  }

  // Monitors
  const mAll = q ? monitorItems.value : monitorItems.value.slice(0, 8)
  const mItems = q ? fuzzyFilter(monitorItems.value, q) : mAll
  if (mItems.length > 0) {
    groups.push({ label: 'Monitors', items: mItems })
  }

  // Navigation
  const nItems = fuzzyFilter(navItems, q)
  if (nItems.length > 0) {
    groups.push({ label: 'Navigation', items: nItems })
  }

  // Actions
  const aItems = fuzzyFilter(actionItems.value, q)
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
  if (item.action === 'toggle-theme') {
    isDark.value = !isDark.value
    localStorage.setItem('whatisup_theme', isDark.value ? 'dark' : 'light')
    document.documentElement.setAttribute('data-theme', isDark.value ? 'dark' : 'light')
    return
  }
  if (item.action === 'toggle-lang') {
    const next = currentLang.value === 'en' ? 'fr' : 'en'
    setLocale(next)
    currentLang.value = next
    return
  }
  if (item.kind === 'monitor' && item.raw) {
    paletteStore.recordVisit({
      type: 'monitor',
      id: item.raw.id,
      name: item.raw.name,
      route: item.route,
    })
  }
  if (item.kind === 'incident' && item.raw) {
    paletteStore.recordVisit({
      type: 'incident',
      id: item.incidentId,
      name: item.raw.name,
      route: item.route,
    })
  }
  if (item.route) {
    const to = item.query ? { path: item.route, query: item.query } : item.route
    router.push(to)
  }
}

async function togglePauseFromItem(item, e) {
  e?.stopPropagation()
  if (!item.raw) return
  const m = item.raw
  try {
    await monitorStore.update(m.id, { enabled: !m.enabled })
    toastSuccess(m.enabled ? `Paused ${m.name}` : `Resumed ${m.name}`)
  } catch {
    toastError('Failed to update monitor')
  }
}

async function ackIncidentFromItem(item, e) {
  e?.stopPropagation()
  if (!item.incidentId) return
  try {
    await incidentUpdatesApi.ack(item.incidentId)
    toastSuccess(`Acknowledged ${item.name}`)
    close()
  } catch {
    toastError('Failed to acknowledge')
  }
}

function clearRecents(e) {
  e?.stopPropagation()
  paletteStore.clearRecents()
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
  gap: 8px;
  padding: 10px 14px;
  border-bottom: 1px solid var(--border);
  color: var(--text-3);
}

.palette__search input {
  flex: 1;
  background: none;
  border: none;
  outline: none;
  color: var(--text-1);
  font-size: 13px;
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
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.palette__group-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding-right: 6px;
}

.palette__group-clear {
  background: none;
  border: none;
  color: var(--text-3);
  padding: 2px 4px;
  cursor: pointer;
  border-radius: 3px;
  transition: color 0.1s, background 0.1s;
}
.palette__group-clear:hover {
  color: var(--text-1);
  background: var(--bg-surface-2);
}

.palette__action-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  border-radius: 4px;
  color: var(--text-3);
  background: transparent;
  cursor: pointer;
  opacity: 0;
  transition: opacity 0.1s, background 0.1s, color 0.1s;
  flex-shrink: 0;
}
.palette__item--active .palette__action-btn,
.palette__item:hover .palette__action-btn {
  opacity: 1;
}
.palette__action-btn:hover {
  background: rgba(59, 130, 246, 0.18);
  color: var(--text-1);
}

.palette__item {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  padding: 6px 10px;
  border: none;
  background: none;
  color: var(--text-2);
  font-size: 12.5px;
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

.palette__status-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  flex-shrink: 0;
}
.palette__status-dot--down    { background: #f87171; box-shadow: 0 0 4px rgba(248,113,113,.5); }
.palette__status-dot--error   { background: #fb923c; }
.palette__status-dot--timeout { background: #fbbf24; }

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
