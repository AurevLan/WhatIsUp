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
        <div style="font-size:10px;font-weight:700;color:#334155;text-transform:uppercase;letter-spacing:.08em;padding:0 8px;margin:0 0 6px;">Overview</div>
        <NavLink to="/"         :icon="LayoutDashboard" label="Dashboard" />
        <NavLink to="/monitors" :icon="Activity"        label="Monitors" />
        <NavLink to="/groups"   :icon="Layers"          label="Groups" />
        <div style="font-size:10px;font-weight:700;color:#334155;text-transform:uppercase;letter-spacing:.08em;padding:0 8px;margin:12px 0 6px;">Infrastructure</div>
        <NavLink to="/probes"   :icon="MapPin"          label="Probes" />
        <NavLink to="/alerts"   :icon="Bell"            label="Alerts" />
        <div style="font-size:10px;font-weight:700;color:#334155;text-transform:uppercase;letter-spacing:.08em;padding:0 8px;margin:12px 0 6px;">Account</div>
        <NavLink to="/settings" :icon="Settings"        label="Settings" />
      </div>

      <!-- User -->
      <div style="padding:12px 8px;border-top:1px solid #1e293b;">
        <div style="display:flex;align-items:center;gap:10px;padding:8px;border-radius:10px;cursor:pointer;" onmouseenter="this.style.background='#1e293b'" onmouseleave="this.style.background='transparent'">
          <div style="width:30px;height:30px;border-radius:50%;background:linear-gradient(135deg,#3b82f6,#8b5cf6);display:flex;align-items:center;justify-content:center;font-size:13px;font-weight:700;color:white;flex-shrink:0;">
            {{ auth.user?.username?.[0]?.toUpperCase() || 'U' }}
          </div>
          <div style="flex:1;min-width:0;">
            <div style="font-size:13px;font-weight:600;color:#e2e8f0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">{{ auth.user?.username }}</div>
            <div style="font-size:11px;color:#475569;">{{ auth.isSuperadmin ? 'Admin' : 'User' }}</div>
          </div>
          <button @click="handleLogout" title="Sign out" style="background:none;border:none;cursor:pointer;color:#475569;padding:4px;border-radius:6px;display:flex;align-items:center;" onmouseenter="this.style.color='#ef4444'" onmouseleave="this.style.color='#475569'">
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
        Reconnecting to real-time updates…
      </div>
      <main style="flex:1;overflow-y:auto;">
        <router-view />
      </main>
    </div>
  </div>
</template>

<script setup>
import { useRouter } from 'vue-router'
import { Activity, Bell, LayoutDashboard, Layers, LogOut, MapPin, Settings, WifiOff } from 'lucide-vue-next'
import { useAuthStore } from '../../stores/auth'
import { useWebSocketStore } from '../../stores/websocket'
import NavLink from '../../components/NavLink.vue'

const router = useRouter()
const auth = useAuthStore()
const ws = useWebSocketStore()

async function handleLogout() {
  await auth.logout()
  router.push('/login')
}
</script>
