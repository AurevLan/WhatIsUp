<template>
  <div class="login">
    <button @click="toggleTheme" class="login__theme-toggle" :aria-label="isDark ? 'Light mode' : 'Dark mode'">
      <Sun v-if="isDark" :size="16" />
      <Moon v-else :size="16" />
    </button>
    <div class="login__container">

      <!-- Logo -->
      <div class="login__brand">
        <div class="login__logo">
          <Activity :size="24" color="white" :stroke-width="2.5" />
        </div>
        <h1 class="login__title">WhatIsUp</h1>
        <p class="login__sub">{{ t('auth.subtitle') }}</p>
      </div>

      <!-- Card -->
      <div class="login__card">
        <form @submit.prevent="handleLogin">

          <div class="login__field">
            <label class="login__label">{{ t('auth.email') }}</label>
            <input v-model="email" type="email" placeholder="you@example.com" required autocomplete="email" class="input" />
          </div>

          <div class="login__field">
            <label class="login__label">{{ t('auth.password') }}</label>
            <input v-model="password" type="password" placeholder="••••••••" required autocomplete="current-password" class="input" />
          </div>

          <!-- Error -->
          <div v-if="error" class="login__error">
            <AlertCircle :size="15" class="flex-shrink-0 mt-px" />
            {{ error }}
          </div>

          <button type="submit" :disabled="loading" class="login__submit" :class="{ 'opacity-60': loading }">
            <span v-if="loading" class="login__spinner" />
            <LogIn v-else :size="15" />
            {{ loading ? t('auth.signing_in') : t('auth.sign_in') }}
          </button>
        </form>

        <!-- OIDC SSO button -->
        <div v-if="oidcEnabled" class="login__sso">
          <div class="login__divider">
            <div class="login__divider-line" />
            <span class="login__divider-text">ou</span>
            <div class="login__divider-line" />
          </div>
          <a href="/api/v1/auth/oidc/login" class="login__sso-btn">
            <Shield :size="15" />
            {{ t('auth.sso_login') }}
          </a>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { Activity, AlertCircle, LogIn, Moon, Shield, Sun } from 'lucide-vue-next'
import { useAuthStore } from '../stores/auth'
import { useWebSocketStore } from '../stores/websocket'
import axios from 'axios'

const { t } = useI18n()
const router = useRouter()
const route  = useRoute()
const auth   = useAuthStore()
const ws     = useWebSocketStore()

const email    = ref('')
const password = ref('')
const error    = ref('')
const loading  = ref(false)
const oidcEnabled = ref(false)

// Theme
const isDark = ref(document.documentElement.getAttribute('data-theme') !== 'light')
function toggleTheme() {
  isDark.value = !isDark.value
  const theme = isDark.value ? 'dark' : 'light'
  localStorage.setItem('whatisup_theme', theme)
  document.documentElement.setAttribute('data-theme', theme)
}

onMounted(async () => {
  try {
    const { data } = await axios.get('/api/v1/auth/oidc/config')
    oidcEnabled.value = data.enabled
  } catch (e) {
    // OIDC config not available — button stays hidden
  }
})

async function handleLogin() {
  loading.value = true
  error.value = ''
  try {
    await auth.login(email.value, password.value)
    ws.connect()
    const redirect = route.query.redirect
    const safe = typeof redirect === 'string' && redirect.startsWith('/') && !redirect.startsWith('//')
    router.push(safe ? redirect : '/')
  } catch (err) {
    error.value = err.response?.data?.detail || t('auth.invalid_credentials')
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--bg-base);
  padding: 1rem;
  position: relative;
}
.login__theme-toggle {
  position: absolute;
  top: 1rem;
  right: 1rem;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 34px;
  height: 34px;
  background: var(--bg-surface);
  border: 1px solid var(--border);
  cursor: pointer;
  color: var(--text-3);
  border-radius: 8px;
  transition: border-color .15s, color .15s, background .15s;
}
.login__theme-toggle:hover {
  border-color: var(--border-hover);
  color: var(--text-2);
  background: var(--bg-surface-2);
}
.login__theme-toggle:focus-visible {
  box-shadow: var(--focus-ring);
  outline: none;
}
.login__container { width: 100%; max-width: 380px; }
.login__brand { text-align: center; margin-bottom: 2rem; }
.login__logo {
  width: 52px; height: 52px;
  background: var(--brand-gradient);
  border-radius: 1rem;
  display: flex; align-items: center; justify-content: center;
  margin: 0 auto 1rem;
  box-shadow: 0 8px 24px rgba(59,130,246,.35);
}
.login__title { font-size: 1.375rem; font-weight: 700; color: var(--text-1); margin: 0 0 0.375rem; }
.login__sub { font-size: 0.8125rem; color: var(--text-3); margin: 0; }

.login__card {
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: 1.75rem;
  box-shadow: var(--shadow-modal);
}
.login__field { margin-bottom: 1.125rem; }
.login__label { display: block; font-size: 0.8125rem; font-weight: 500; color: var(--text-2); margin-bottom: 0.375rem; }

.login__error {
  display: flex; align-items: flex-start; gap: 0.5rem;
  background: rgba(239,68,68,.1);
  border: 1px solid rgba(239,68,68,.2);
  border-radius: var(--radius-sm);
  padding: 0.75rem;
  margin-bottom: 1.125rem;
  font-size: 0.8125rem;
  color: var(--down);
}

.login__submit {
  width: 100%;
  display: flex; align-items: center; justify-content: center; gap: 0.5rem;
  background: var(--brand-gradient);
  color: white;
  font-size: 0.875rem;
  font-weight: 600;
  padding: 0.6875rem;
  border-radius: var(--radius-sm);
  border: none;
  cursor: pointer;
  box-shadow: 0 4px 14px rgba(37,99,235,.4);
  transition: opacity .15s, box-shadow .15s;
}
.login__submit:hover { box-shadow: 0 6px 20px rgba(37,99,235,.5); }
.login__submit:active { transform: translateY(1px); }
.login__submit:focus-visible { box-shadow: var(--focus-ring); }

.login__spinner {
  width: 16px; height: 16px;
  border: 2px solid rgba(255,255,255,.3);
  border-top-color: white;
  border-radius: 50%;
  animation: spin 1s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }

.login__sso { margin-top: 1rem; }
.login__divider { display: flex; align-items: center; gap: 0.625rem; margin-bottom: 1rem; }
.login__divider-line { flex: 1; height: 1px; background: var(--border); }
.login__divider-text { font-size: 0.75rem; color: var(--text-3); }
.login__sso-btn {
  display: flex; align-items: center; justify-content: center; gap: 0.5rem;
  width: 100%; padding: 0.6875rem;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  color: var(--text-2);
  font-size: 0.875rem; font-weight: 500;
  text-decoration: none;
  transition: border-color .15s, color .15s;
}
.login__sso-btn:hover { border-color: var(--border-hover); color: var(--text-1); }
</style>
