<template>
  <div style="display:flex; min-height:100vh; background:#030712;">

    <!-- Sidebar -->
    <nav style="width:220px; background:#0a0f1e; border-right:1px solid #1e293b; display:flex; flex-direction:column; flex-shrink:0;">

      <!-- Logo -->
      <div style="padding:20px 16px; border-bottom:1px solid #1e293b;">
        <div style="display:flex; align-items:center; gap:10px;">
          <div style="width:34px;height:34px;background:linear-gradient(135deg,#3b82f6,#8b5cf6);border-radius:10px;display:flex;align-items:center;justify-content:center;flex-shrink:0;">
            <Activity :size="16" color="white" :stroke-width="2.5" />
          </div>
          <div>
            <div style="font-size:14px;font-weight:700;color:#f1f5f9;line-height:1.2;">WhatIsUp</div>
            <div style="font-size:11px;color:#475569;line-height:1.2;">Monitoring</div>
          </div>
        </div>
      </div>

      <!-- Nav -->
      <div style="flex:1;padding:12px 8px;display:flex;flex-direction:column;gap:2px;overflow-y:auto;">
        <div style="font-size:10px;font-weight:700;color:#334155;text-transform:uppercase;letter-spacing:.08em;padding:0 8px;margin:0 0 6px;">{{ t('nav.overview') }}</div>
        <NavLink to="/"         :icon="LayoutDashboard" :label="t('nav.dashboard')" :exact="true" />
        <NavLink to="/monitors" :icon="Activity"        :label="t('nav.monitors')" :badge="downCount" />
        <NavLink to="/groups"   :icon="Layers"          :label="t('nav.groups')" />
        <div style="font-size:10px;font-weight:700;color:#334155;text-transform:uppercase;letter-spacing:.08em;padding:0 8px;margin:12px 0 6px;">{{ t('nav.infrastructure') }}</div>
        <NavLink to="/probes"           :icon="MapPin"          :label="t('nav.probes')" />
        <NavLink to="/alerts"           :icon="Bell"            :label="t('nav.alerts')" />
        <NavLink to="/maintenance"      :icon="CalendarClock"   :label="t('nav.maintenance')" />
        <NavLink to="/incident-groups"  :icon="GitMerge"        :label="t('nav.incidentGroups')" :badge="openIncidentCount" />
        <NavLink to="/templates"        :icon="Copy"            label="Templates" />
        <div style="font-size:10px;font-weight:700;color:#334155;text-transform:uppercase;letter-spacing:.08em;padding:0 8px;margin:12px 0 6px;">{{ t('nav.account') }}</div>
        <NavLink to="/api-keys" :icon="KeyRound"        :label="t('nav.apiKeys')" />
        <NavLink to="/audit"    :icon="ClipboardList"   :label="t('nav.audit')" />
        <NavLink to="/settings" :icon="Settings"        :label="t('nav.settings')" />
      </div>

      <!-- User + lang toggle -->
      <div style="padding:12px 8px;border-top:1px solid #1e293b;">
        <!-- Language toggle -->
        <div style="display:flex;justify-content:center;margin-bottom:8px;">
          <button
            @click="toggleLang"
            :title="t('settings.language')"
            style="background:none;border:1px solid #1e293b;cursor:pointer;color:#475569;padding:4px 10px;border-radius:6px;display:flex;align-items:center;gap:6px;font-size:12px;transition:all .15s;"
            onmouseenter="this.style.borderColor='#334155';this.style.color='#94a3b8';"
            onmouseleave="this.style.borderColor='#1e293b';this.style.color='#475569';"
          >
            <span style="font-size:14px;line-height:1;">{{ currentLang === 'en' ? '🇫🇷' : '🇬🇧' }}</span>
            <span>{{ currentLang === 'en' ? 'FR' : 'EN' }}</span>
          </button>
        </div>

        <div style="display:flex;align-items:center;gap:10px;padding:8px;border-radius:10px;cursor:pointer;" onmouseenter="this.style.background='#1e293b'" onmouseleave="this.style.background='transparent'">
          <div style="width:30px;height:30px;border-radius:50%;background:linear-gradient(135deg,#3b82f6,#8b5cf6);display:flex;align-items:center;justify-content:center;font-size:13px;font-weight:700;color:white;flex-shrink:0;">
            {{ auth.user?.username?.[0]?.toUpperCase() || 'U' }}
          </div>
          <div style="flex:1;min-width:0;">
            <div style="font-size:13px;font-weight:600;color:#e2e8f0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">{{ auth.user?.username }}</div>
            <div style="font-size:11px;color:#475569;">{{ auth.isSuperadmin ? 'Admin' : 'User' }}</div>
          </div>
          <button @click="handleLogout" :title="t('auth.logout')" style="background:none;border:none;cursor:pointer;color:#475569;padding:4px;border-radius:6px;display:flex;align-items:center;" onmouseenter="this.style.color='#ef4444'" onmouseleave="this.style.color='#475569'">
            <LogOut :size="15" />
          </button>
        </div>
      </div>
    </nav>

    <!-- Main -->
    <div style="flex:1;display:flex;flex-direction:column;min-width:0;overflow:hidden;">
      <!-- WS banner -->
      <div v-if="!ws.connected" style="display:flex;align-items:center;gap:8px;padding:10px 24px;background:rgba(245,158,11,.1);border-bottom:1px solid rgba(245,158,11,.2);color:#fbbf24;font-size:13px;">
        <WifiOff :size="14" />
        {{ t('ws.reconnecting') }}
      </div>
      <main style="flex:1;overflow-y:auto;">
        <router-view />
      </main>
    </div>

    <!-- Global components -->
    <ToastContainer />
    <ConfirmModal />
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { Activity, Bell, CalendarClock, ClipboardList, Copy, GitMerge, KeyRound, LayoutDashboard, Layers, LogOut, MapPin, Settings, WifiOff } from 'lucide-vue-next'
import { useAuthStore } from '../../stores/auth'
import { useWebSocketStore } from '../../stores/websocket'
import { useMonitorStore } from '../../stores/monitors'
import NavLink from '../../components/NavLink.vue'
import ToastContainer from '../../components/ToastContainer.vue'
import ConfirmModal from '../../components/ConfirmModal.vue'
import { setLocale, getLocale } from '../../i18n/index.js'

const { t } = useI18n()
const router = useRouter()
const auth = useAuthStore()
const ws = useWebSocketStore()
const monitorStore = useMonitorStore()

const currentLang = ref(getLocale())

// Badge monitors DOWN
const downCount = computed(() =>
  monitorStore.monitors.filter(m => ['down', 'error', 'timeout'].includes(m._lastStatus)).length
)

// Badge incidents ouverts
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
