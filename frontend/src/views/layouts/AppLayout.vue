<template>
  <div class="app-shell">

    <!-- Mobile overlay -->
    <div v-if="sidebarOpen" class="sidebar-overlay lg:hidden" @click="sidebarOpen = false" />

    <!-- Sidebar -->
    <nav
      class="sidebar"
      :class="{ 'sidebar--open': sidebarOpen }"
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
        <NavLink to="/incident-groups" :icon="GitMerge"      :label="t('nav.incidentGroups')" :badge="openIncidentCount" />
        <NavLink to="/incidents"       :icon="Clock"         :label="t('nav.incidents')" />
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

        <div class="topbar__right">
          <!-- Global status indicator -->
          <div v-if="!monitorStore.loading && monitorStore.monitors.length > 0" class="topbar__status" :class="downCount > 0 ? 'topbar__status--down' : 'topbar__status--up'">
            <span class="topbar__status-dot" />
            {{ downCount > 0 ? t('dashboard.n_down', { n: downCount }) : t('dashboard.all_operational') }}
          </div>

          <!-- Language toggle -->
          <button @click="toggleLang" :title="t('settings.language')" class="topbar__lang-btn">
            <span>{{ currentLang === 'en' ? '🇫🇷' : '🇬🇧' }}</span>
            <span>{{ currentLang === 'en' ? 'FR' : 'EN' }}</span>
          </button>
        </div>
      </header>

      <!-- Content -->
      <main class="content" @click="sidebarOpen && (sidebarOpen = false)">
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
import { computed, ref, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import {
  Activity, Bell, CalendarClock, ClipboardList, Clock, Copy, GitMerge,
  KeyRound, LayoutDashboard, Layers, LogOut, MapPin, Settings,
  ShieldCheck, WifiOff,
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

function onGlobalKeydown(e) {
  if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
    e.preventDefault()
    showPalette.value = !showPalette.value
  }
}
onMounted(() => window.addEventListener('keydown', onGlobalKeydown))
onUnmounted(() => window.removeEventListener('keydown', onGlobalKeydown))
const currentLang = ref(getLocale())

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

/* Mobile: hidden off-screen */
@media (max-width: 1023px) {
  .sidebar {
    transform: translateX(-100%);
  }
  .sidebar--open {
    transform: translateX(0);
    box-shadow: 4px 0 32px rgba(0,0,0,.5);
  }
}

.sidebar__logo {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 18px 16px;
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
}

.sidebar__logo-icon {
  width: 32px;
  height: 32px;
  background: var(--brand-gradient);
  border-radius: 9px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  box-shadow: 0 2px 8px rgba(59,130,246,.3);
}

.sidebar__logo-name {
  font-size: 13.5px;
  font-weight: 700;
  color: var(--text-1);
  line-height: 1.2;
  letter-spacing: -.01em;
}

.sidebar__logo-sub {
  font-size: 10.5px;
  color: var(--text-3);
  line-height: 1.2;
}

.sidebar__nav {
  flex: 1;
  padding: 10px 8px;
  display: flex;
  flex-direction: column;
  gap: 1px;
  overflow-y: auto;
  overflow-x: hidden;
}

.sidebar__user {
  padding: 10px 8px;
  border-top: 1px solid var(--border);
  display: flex;
  align-items: center;
  gap: 9px;
  flex-shrink: 0;
}

.sidebar__user-avatar {
  width: 28px;
  height: 28px;
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
  font-size: 12.5px;
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
  padding: 0 16px;
  height: var(--topbar-h);
  border-bottom: 1px solid var(--border);
  background: var(--bg-surface);
  position: sticky;
  top: 0;
  z-index: 30;
  gap: 10px;
  flex-shrink: 0;
}

.topbar__hamburger {
  display: flex;
  flex-direction: column;
  gap: 4px;
  background: none;
  border: none;
  cursor: pointer;
  padding: 6px 4px;
  border-radius: 6px;
  transition: background .15s;
}
.topbar__hamburger:hover { background: var(--bg-surface-2); }
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

.topbar__lang-btn {
  display: flex;
  align-items: center;
  gap: 5px;
  background: none;
  border: 1px solid var(--border);
  cursor: pointer;
  color: var(--text-3);
  padding: 4px 10px;
  border-radius: 6px;
  font-size: 11.5px;
  font-family: inherit;
  font-weight: 500;
  transition: border-color .15s, color .15s, background .15s;
}
.topbar__lang-btn:hover {
  border-color: var(--border-hover);
  color: var(--text-2);
  background: var(--bg-surface-2);
}
.topbar__lang-btn span:first-child { font-size: 13px; line-height: 1; }

/* ── Content ── */
.content {
  flex: 1;
  overflow-y: auto;
  overflow-x: hidden;
}
</style>
