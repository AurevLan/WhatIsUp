<template>
  <div style="min-height:100vh;display:flex;align-items:center;justify-content:center;background:#030712;">
    <div style="text-align:center;color:#94a3b8;font-size:14px;">
      <div v-if="error" style="color:#f87171;">
        <p style="font-size:18px;font-weight:600;margin-bottom:8px;">{{ t('oidc.login_failed') }}</p>
        <p>{{ errorMessage }}</p>
        <a href="/login" style="display:inline-block;margin-top:16px;color:#3b82f6;">{{ t('oidc.back_to_login') }}</a>
      </div>
      <div v-else>
        <div style="width:32px;height:32px;border:3px solid rgba(59,130,246,.3);border-top-color:#3b82f6;border-radius:50%;animation:spin 1s linear infinite;margin:0 auto 16px;"></div>
        {{ t('oidc.signing_in') }}
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '../stores/auth'
import { useWebSocketStore } from '../stores/websocket'
import api from '../api/client'

const { t } = useI18n()

const router = useRouter()
const route  = useRoute()
const auth   = useAuthStore()
const ws     = useWebSocketStore()

const error = ref(false)
const errorMessage = ref('')

onMounted(async () => {
  // Check query params for error (server may redirect with ?error=...)
  const queryParams = new URLSearchParams(window.location.search)
  const errorParam = queryParams.get('error')

  if (errorParam) {
    error.value = true
    errorMessage.value = errorParam.replace(/_/g, ' ')
    return
  }

  // Tokens are passed via URL fragment (#) to avoid leakage in server logs/Referer
  const fragment = window.location.hash.substring(1)
  const params = new URLSearchParams(fragment)
  const accessToken  = params.get('access_token')
  const refreshToken = params.get('refresh_token')

  if (!accessToken || !refreshToken) {
    error.value = true
    errorMessage.value = t('oidc.missing_params')
    return
  }

  // Store tokens and clear fragment from URL to prevent leakage via browser history
  localStorage.setItem('access_token', accessToken)
  localStorage.setItem('refresh_token', refreshToken)
  auth.accessToken = accessToken
  window.history.replaceState({}, '', window.location.pathname)

  // Fetch user profile (access_token is already in localStorage — interceptor attaches it)
  try {
    const { data } = await api.get('/auth/me')
    auth.user = data
  } catch {
    error.value = true
    errorMessage.value = t('oidc.profile_error')
    return
  }

  ws.connect()
  router.replace('/')
})
</script>

<style>
@keyframes spin { to { transform: rotate(360deg); } }
</style>
