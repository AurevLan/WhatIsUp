<template>
  <div class="app-shell">
    <a href="#main-content" class="skip-to-content">Skip to content</a>

    <!-- Mobile overlay -->
    <div v-if="sidebarOpen" class="sidebar-overlay lg:hidden" @click="sidebarOpen = false" aria-hidden="true" />

    <!-- Sidebar -->
    <nav
      class="sidebar"
      :class="{ 'sidebar--open': sidebarOpen }"
      aria-label="Main navigation"
    >
      <!-- Logo -->
      <div class="sidebar__logo">
        <div class="sidebar__logo-icon">
          <Activity :size="15" color="white" :stroke-width="2.5" />
        </div>
        <div>
          <div class="sidebar__logo-name">WhatIsUp</div>
          <div class="sidebar__logo-sub">Monitoring</div>
        </div>
      </div>

      <!-- Nav -->
      <div class="sidebar__nav">
        <div class="nav-section">{{ t('nav.overview') }}</div>
        <NavLink to="/"         :icon="LayoutDashboard" :label="t('nav.dashboard')" :exact="true" />
        <NavLink to="/monitors" :icon="Activity"        :label="t('nav.monitors')" :badge="downCount" />
        <NavLink to="/groups"   :icon="Layers"          :label="t('nav.groups')" />

        <div class="nav-section">{{ t('nav.infrastructure') }}</div>
        <NavLink to="/probes"          :icon="MapPin"        :label="t('nav.probes')" />
        <NavLink to="/alerts"          :icon="Bell"          :label="t('nav.alerts')" />
        <NavLink to="/maintenance"     :icon="CalendarClock" :label="t('nav.maintenance')" />
        <NavLink to="/incidents"       :icon="Clock"         :label="t('nav.incidents')" :badge="openIncidentCount" />
        <NavLink to="/templates"       :icon="Copy"          :label="t('nav.templates')" />

        <div class="nav-section">{{ t('nav.account') }}</div>
        <NavLink to="/api-keys" :icon="KeyRound"      :label="t('nav.apiKeys')" />
        <NavLink to="/audit"    :icon="ClipboardList" :label="t('nav.audit')" />
        <NavLink to="/settings" :icon="Settings"      :label="t('nav.settings')" />

        <template v-if="auth.isSuperadmin">
          <div class="nav-section">Admin</div>
          <NavLink to="/admin" :icon="ShieldCheck" label="Administration" />
        </template>
      </div>

      <!-- User footer -->
      <div class="sidebar__user">
        <div class="sidebar__user-avatar">
          {{ auth.user?.username?.[0]?.toUpperCase() || 'U' }}
        </div>
        <div class="sidebar__user-info">
          <div class="sidebar__user-name">{{ auth.user?.username }}</div>
          <div class="sidebar__user-role">{{ auth.isSuperadmin ? 'Admin' : 'User' }}</div>
        </div>
        <button @click="handleLogout" :title="t('auth.logout')" class="sidebar__logout">
          <LogOut :size="14" />
        </button>
      </div>
    </nav>

    <!-- Main area -->
    <div class="main">
      <!-- Topbar -->
      <header class="topbar">
        <!-- Hamburger (mobile) -->
        <button class="topbar__hamburger" @click="sidebarOpen = !sidebarOpen" :aria-label="'Toggle menu'">
          <span class="hamburger-line" :class="{ 'hamburger-line--open-1': sidebarOpen }" />
          <span class="hamburger-line" :class="{ 'hamburger-line--open-2': sidebarOpen }" />
          <span class="hamburger-line" :class="{ 'hamburger-line--open-3': sidebarOpen }" />
        </button>

        <!-- WS reconnecting banner -->
        <Transition name="badge-fade">
          <div v-if="ws.showReconnecting" class="topbar__ws-badge">
            <WifiOff :size="11" />
            {{ t('ws.reconnecting') }}
          </div>
        </Transition>

        <!-- Search trigger (opens CommandPalette) -->
        <button class="topbar__search" @click="showPalette = true">
          <Search :size="13" />
          <span class="topbar__search-text">{{ t('common.search') }}...</span>
          <span class="topbar__search-kbd">
            <kbd class="kbd">{{ isMac ? '⌘' : 'Ctrl' }}</kbd>
            <kbd class="kbd">K</kbd>
          </span>
        </button>

        <div class="topbar__right">
          <!-- Global status indicator -->
          <div v-if="!monitorStore.loading && monitorStore.monitors.length > 0" class="topbar__status" :class="downCount > 0 ? 'topbar__status--down' : 'topbar__status--up'">
            <span class="topbar__status-dot" />
            {{ downCount > 0 ? t('dashboard.n_down', { n: downCount }) : t('dashboard.all_operational') }}
          </div>

          <!-- Language toggle -->
          <button @click="toggleLang" :title="t('settings.language')" class="topbar__lang-btn">
            {{ currentLang === 'en' ? 'FR' : 'EN' }}
          </button>

          <!-- Theme toggle -->
          <button @click="toggleTheme" :title="isDark ? 'Light mode' : 'Dark mode'" class="topbar__theme-btn" aria-label="Toggle theme">
            <Sun v-if="isDark" :size="14" />
            <Moon v-else :size="14" />
          </button>
        </div>
      </header>

      <!-- Content -->
      <main id="main-content" class="content" @click="sidebarOpen && (sidebarOpen = false)">
        <router-view v-slot="{ Component }">
          <Transition name="page" mode="out-in">
            <component :is="Component" />
          </Transition>
        </router-view>
      </main>
    </div>

    <!-- Global components -->
    <ToastContainer />
    <ConfirmModal />
    <CommandPalette v-model="showPalette" />
  </div>
</template>

<script setup>
import { computed, ref, onMounted, onUnmounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import {
  Activity, Bell, CalendarClock, ClipboardList, Clock, Copy, GitMerge,
  KeyRound, LayoutDashboard, Layers, LogOut, MapPin, Moon, Search, Settings,
  ShieldCheck, Sun, WifiOff,
} from 'lucide-vue-next'
import { useAuthStore } from '../../stores/auth'
import { useWebSocketStore } from '../../stores/websocket'
import { useMonitorStore } from '../../stores/monitors'
import NavLink from '../../components/NavLink.vue'
import ToastContainer from '../../components/ToastContainer.vue'
import ConfirmModal from '../../components/ConfirmModal.vue'
import CommandPalette from '../../components/CommandPalette.vue'
import { setLocale, getLocale } from '../../i18n/index.js'

const { t } = useI18n()
const router = useRouter()
const auth = useAuthStore()
const ws = useWebSocketStore()
const monitorStore = useMonitorStore()
const sidebarOpen = ref(false)
const showPalette = ref(false)
const isMac = navigator.platform.toUpperCase().indexOf('MAC') >= 0

function onGlobalKeydown(e) {
  if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
    e.preventDefault()
    showPalette.value = !showPalette.value
  }
}
onMounted(() => window.addEventListener('keydown', onGlobalKeydown))
onUnmounted(() => {
  window.removeEventListener('keydown', onGlobalKeydown)
  document.body.style.overflow = ''
})

// Lock body scroll when the mobile drawer is open so background does not scroll under the menu.
watch(sidebarOpen, (open) => {
  document.body.style.overflow = open ? 'hidden' : ''
})
const currentLang = ref(getLocale())

// Theme management
function getInitialTheme() {
  const stored = localStorage.getItem('whatisup_theme')
  if (stored === 'light' || stored === 'dark') return stored
  return window.matchMedia?.('(prefers-color-scheme: light)').matches ? 'light' : 'dark'
}

const isDark = ref(getInitialTheme() !== 'light')

function applyTheme(dark) {
  document.documentElement.setAttribute('data-theme', dark ? 'dark' : 'light')
}

function toggleTheme() {
  isDark.value = !isDark.value
  localStorage.setItem('whatisup_theme', isDark.value ? 'dark' : 'light')
  applyTheme(isDark.value)
}

// Apply on mount
applyTheme(isDark.value)

const downCount = computed(() =>
  monitorStore.monitors.filter(m => ['down', 'error', 'timeout'].includes(m._lastStatus)).length
)
const openIncidentCount = computed(() =>
  monitorStore.monitors.filter(m => m._hasOpenIncident).length
)

function toggleLang() {
  const next = currentLang.value === 'en' ? 'fr' : 'en'
  setLocale(next)
  currentLang.value = next
}

async function handleLogout() {
  await auth.logout()
  router.push('/login')
}
</script>

<style scoped>
/* ── Shell ── */
.app-shell {
  display: flex;
  min-height: 100vh;
  background: var(--bg-base);
}

/* ── Sidebar ── */
.sidebar {
  width: var(--sidebar-w);
  background: var(--bg-surface);
  border-right: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  flex-shrink: 0;
  position: fixed;
  top: 0;
  left: 0;
  height: 100vh;
  z-index: 50;
  transition: transform .22s cubic-bezier(.4,0,.2,1);
  overflow: hidden;
}

/* Desktop: always visible */
@media (min-width: 1024px) {
  .sidebar {
    position: sticky;
    transform: none !important;
  }
  .main { margin-left: 0; }
}

/* Mobile: hidden off-screen, drawer width adapts to viewport */
@media (max-width: 1023px) {
  .sidebar {
    transform: translateX(-100%);
    width: min(300px, 85vw);
  }
  .sidebar--open {
    transform: translateX(0);
    box-shadow: 4px 0 32px rgba(0,0,0,.5);
  }
  /* Larger touch targets inside the drawer */
  .sidebar__nav { padding: 10px 10px; gap: 2px; }
  .sidebar__user { padding: 14px 12px; gap: 12px; }
  .sidebar__user-avatar { width: 32px; height: 32px; font-size: 13px; }
  .sidebar__user-name { font-size: 13.5px; }
  .sidebar__user-role { font-size: 12px; }
  .sidebar__logout { padding: 10px; min-width: 40px; min-height: 40px; }
  .sidebar__logout svg { width: 18px; height: 18px; }
}

.sidebar__logo {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 12px;
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
}

.sidebar__logo-icon {
  width: 28px;
  height: 28px;
  background: var(--brand-gradient);
  border-radius: 7px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  box-shadow: 0 2px 8px rgba(59,130,246,.3);
}

.sidebar__logo-name {
  font-size: 12.5px;
  font-weight: 700;
  color: var(--text-1);
  line-height: 1.2;
  letter-spacing: -.01em;
}

.sidebar__logo-sub {
  font-size: 9.5px;
  color: var(--text-3);
  line-height: 1.2;
}

.sidebar__nav {
  flex: 1;
  padding: 6px 6px;
  display: flex;
  flex-direction: column;
  gap: 0px;
  overflow-y: auto;
  overflow-x: hidden;
}

.sidebar__user {
  padding: 8px 8px;
  border-top: 1px solid var(--border);
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

.sidebar__user-avatar {
  width: 24px;
  height: 24px;
  border-radius: 50%;
  background: var(--brand-gradient);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 11px;
  font-weight: 700;
  color: white;
  flex-shrink: 0;
}

.sidebar__user-info {
  flex: 1;
  min-width: 0;
}

.sidebar__user-name {
  font-size: 11.5px;
  font-weight: 600;
  color: var(--text-1);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  line-height: 1.3;
}

.sidebar__user-role {
  font-size: 10.5px;
  color: var(--text-3);
  line-height: 1.3;
}

.sidebar__logout {
  background: none;
  border: none;
  cursor: pointer;
  color: var(--text-3);
  padding: 5px;
  border-radius: 6px;
  display: flex;
  align-items: center;
  transition: color .15s, background .15s;
  flex-shrink: 0;
}
.sidebar__logout:hover {
  color: #fca5a5;
  background: rgba(248,113,113,.1);
}

/* ── Main ── */
.main {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
  /* On desktop, sidebar is sticky, so no offset needed */
}

/* ── Topbar ── */
.topbar {
  display: flex;
  align-items: center;
  padding: 0 12px;
  height: var(--topbar-h);
  border-bottom: 1px solid var(--border);
  background: var(--bg-surface);
  position: sticky;
  top: 0;
  z-index: 30;
  gap: 8px;
  flex-shrink: 0;
}

.topbar__hamburger {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 4px;
  background: none;
  border: none;
  cursor: pointer;
  width: 44px;
  height: 44px;
  border-radius: 8px;
  transition: background .15s;
  -webkit-tap-highlight-color: transparent;
}
.topbar__hamburger:hover { background: var(--bg-surface-2); }
.topbar__hamburger:active { background: var(--bg-surface-3); }
@media (min-width: 1024px) {
  .topbar__hamburger { display: none; }
}

.hamburger-line {
  display: block;
  width: 18px;
  height: 1.5px;
  background: var(--text-2);
  border-radius: 2px;
  transition: transform .2s, opacity .2s;
  transform-origin: center;
}
.hamburger-line--open-1 { transform: translateY(5.5px) rotate(45deg); }
.hamburger-line--open-2 { opacity: 0; transform: scaleX(0); }
.hamburger-line--open-3 { transform: translateY(-5.5px) rotate(-45deg); }

.topbar__ws-badge {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 11.5px;
  color: #fbbf24;
  background: rgba(251,191,36,.08);
  border: 1px solid rgba(251,191,36,.2);
  border-radius: 99px;
  padding: 3px 10px;
}

.badge-fade-enter-active, .badge-fade-leave-active {
  transition: opacity .25s ease, transform .25s ease;
}
.badge-fade-enter-from, .badge-fade-leave-to {
  opacity: 0;
  transform: translateY(-4px);
}

.topbar__status {
  display: flex;
  align-items: center;
  gap: 5px;
  font-size: 11.5px;
  font-weight: 500;
  border-radius: 99px;
  padding: 3px 10px;
  border: 1px solid transparent;
  white-space: nowrap;
}
.topbar__status--up {
  color: var(--up);
  background: rgba(52,211,153,.08);
  border-color: rgba(52,211,153,.2);
}
.topbar__status--down {
  color: var(--down);
  background: rgba(248,113,113,.08);
  border-color: rgba(248,113,113,.2);
}
.topbar__status-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: currentColor;
  flex-shrink: 0;
}
.topbar__status--down .topbar__status-dot {
  animation: pulse-ring 2s ease-out infinite;
}
@media (max-width: 640px) {
  .topbar__status { display: none; }
}

.topbar__right {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: 8px;
}

.topbar__theme-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  background: none;
  border: 1px solid var(--border);
  cursor: pointer;
  color: var(--text-3);
  border-radius: 6px;
  transition: border-color .15s, color .15s, background .15s;
  -webkit-tap-highlight-color: transparent;
}
@media (max-width: 640px) {
  .topbar__theme-btn { width: 40px; height: 40px; }
  .topbar__theme-btn svg { width: 18px; height: 18px; }
}
.topbar__theme-btn:hover {
  border-color: var(--border-hover);
  color: var(--text-2);
  background: var(--bg-surface-2);
}
.topbar__theme-btn:focus-visible {
  box-shadow: var(--focus-ring);
  outline: none;
}

.topbar__lang-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  background: none;
  border: 1px solid var(--border);
  cursor: pointer;
  color: var(--text-3);
  padding: 3px 8px;
  border-radius: 4px;
  font-size: 10.5px;
  font-family: inherit;
  font-weight: 600;
  letter-spacing: .04em;
  transition: border-color .15s, color .15s, background .15s;
  -webkit-tap-highlight-color: transparent;
}
@media (max-width: 640px) {
  .topbar__lang-btn { min-width: 40px; height: 40px; padding: 0 10px; font-size: 12px; }
}
.topbar__lang-btn:hover {
  border-color: var(--border-hover);
  color: var(--text-2);
  background: var(--bg-surface-2);
}

/* ── Topbar search trigger ── */
.topbar__search {
  display: flex;
  align-items: center;
  gap: 8px;
  flex: 1;
  max-width: 320px;
  height: 28px;
  padding: 0 8px 0 10px;
  background: var(--bg-surface-2);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  cursor: pointer;
  transition: border-color .15s, background .15s;
  color: var(--text-3);
  font-family: inherit;
  font-size: 12px;
}
.topbar__search:hover {
  border-color: var(--border-hover);
  background: var(--bg-surface-3);
}
.topbar__search-text {
  flex: 1;
  text-align: left;
  white-space: nowrap;
  overflow: hidden;
}
.topbar__search-kbd {
  display: flex;
  align-items: center;
  gap: 2px;
  flex-shrink: 0;
}
@media (max-width: 640px) {
  .topbar__search-text { display: none; }
  .topbar__search-kbd { display: none; }
  .topbar__search { max-width: 36px; flex: 0; justify-content: center; padding: 0 8px; }
}

/* ── Content ── */
.content {
  flex: 1;
  overflow-y: auto;
  overflow-x: hidden;
}
</style>
