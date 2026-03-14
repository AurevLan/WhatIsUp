<template>
  <div style="min-height:100vh;display:flex;align-items:center;justify-content:center;background:#030712;padding:16px;">
    <div style="width:100%;max-width:380px;">

      <!-- Logo -->
      <div style="text-align:center;margin-bottom:32px;">
        <div style="width:52px;height:52px;background:linear-gradient(135deg,#3b82f6,#8b5cf6);border-radius:16px;display:flex;align-items:center;justify-content:center;margin:0 auto 16px;box-shadow:0 8px 24px rgba(59,130,246,.35);">
          <Activity :size="24" color="white" :stroke-width="2.5" />
        </div>
        <h1 style="font-size:22px;font-weight:700;color:#f1f5f9;margin:0 0 6px;">WhatIsUp</h1>
        <p style="font-size:13px;color:#475569;margin:0;">{{ t('auth.subtitle') }}</p>
      </div>

      <!-- Card -->
      <div style="background:#0a0f1e;border:1px solid #1e293b;border-radius:16px;padding:28px;box-shadow:0 24px 48px rgba(0,0,0,.5);">
        <form @submit.prevent="handleLogin">

          <div style="margin-bottom:18px;">
            <label style="display:block;font-size:13px;font-weight:500;color:#94a3b8;margin-bottom:6px;">{{ t('auth.email') }}</label>
            <input v-model="email" type="email" placeholder="you@example.com" required autocomplete="email" class="input" />
          </div>

          <div style="margin-bottom:20px;">
            <label style="display:block;font-size:13px;font-weight:500;color:#94a3b8;margin-bottom:6px;">{{ t('auth.password') }}</label>
            <input v-model="password" type="password" placeholder="••••••••" required autocomplete="current-password" class="input" />
          </div>

          <!-- Error -->
          <div v-if="error" style="display:flex;align-items:flex-start;gap:8px;background:rgba(239,68,68,.1);border:1px solid rgba(239,68,68,.2);border-radius:10px;padding:12px;margin-bottom:18px;font-size:13px;color:#f87171;">
            <AlertCircle :size="15" style="flex-shrink:0;margin-top:1px;" />
            {{ error }}
          </div>

          <button type="submit" :disabled="loading" style="width:100%;display:flex;align-items:center;justify-content:center;gap:8px;background:linear-gradient(135deg,#2563eb,#3b82f6);color:white;font-size:14px;font-weight:600;padding:11px;border-radius:10px;border:none;cursor:pointer;box-shadow:0 4px 14px rgba(37,99,235,.4);transition:opacity .15s;" :style="{opacity: loading ? .6 : 1}">
            <span v-if="loading" style="width:16px;height:16px;border:2px solid rgba(255,255,255,.3);border-top-color:white;border-radius:50%;animation:spin 1s linear infinite;" />
            <LogIn v-else :size="15" />
            {{ loading ? t('auth.signing_in') : t('auth.sign_in') }}
          </button>
        </form>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { Activity, AlertCircle, LogIn } from 'lucide-vue-next'
import { useAuthStore } from '../stores/auth'
import { useWebSocketStore } from '../stores/websocket'

const { t } = useI18n()
const router = useRouter()
const route  = useRoute()
const auth   = useAuthStore()
const ws     = useWebSocketStore()

const email    = ref('')
const password = ref('')
const error    = ref('')
const loading  = ref(false)

async function handleLogin() {
  loading.value = true
  error.value = ''
  try {
    await auth.login(email.value, password.value)
    ws.connect()
    router.push(route.query.redirect || '/')
  } catch (err) {
    error.value = err.response?.data?.detail || t('auth.invalid_credentials')
  } finally {
    loading.value = false
  }
}
</script>

<style>
@keyframes spin { to { transform: rotate(360deg); } }
</style>
