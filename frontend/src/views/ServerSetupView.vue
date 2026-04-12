<template>
  <div class="login">
    <div class="login__container">
      <div class="login__brand">
        <div class="login__logo">
          <Server :size="24" color="white" :stroke-width="2.5" />
        </div>
        <h1 class="login__title">WhatIsUp</h1>
        <p class="login__sub">{{ t('setup.subtitle') }}</p>
      </div>

      <div class="login__card">
        <form @submit.prevent="handleSave">
          <div class="login__field">
            <label class="login__label">{{ t('setup.url_label') }}</label>
            <input
              v-model="url"
              type="url"
              placeholder="https://monitoring.example.com"
              required
              autocomplete="url"
              inputmode="url"
              class="input"
            />
            <p class="login__hint">{{ t('setup.url_hint') }}</p>
          </div>

          <div v-if="error" class="login__error">
            <AlertCircle :size="15" class="flex-shrink-0 mt-px" />
            {{ error }}
          </div>

          <button type="submit" :disabled="loading" class="login__submit" :class="{ 'opacity-60': loading }">
            <span v-if="loading" class="login__spinner" />
            <Check v-else :size="15" />
            {{ loading ? t('setup.testing') : t('setup.connect') }}
          </button>

          <button
            v-if="error"
            type="button"
            class="login__submit"
            style="margin-top: 8px; background: transparent; border: 1px solid currentColor;"
            @click="skipValidation"
          >
            {{ t('setup.skip_validation') }}
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
import { Server, Check, AlertCircle } from 'lucide-vue-next'
import axios from 'axios'
import { setServerUrl, getServerUrl } from '../lib/serverConfig'

const { t } = useI18n()
const router = useRouter()
const route = useRoute()

const url = ref(getServerUrl() || '')
const loading = ref(false)
const error = ref('')

async function handleSave() {
  error.value = ''
  loading.value = true
  try {
    const trimmed = url.value.trim().replace(/\/+$/, '')
    if (!/^https?:\/\//i.test(trimmed)) {
      throw new Error(t('setup.error_scheme'))
    }
    // Probe the health endpoint to validate connectivity + that it's a WhatIsUp server.
    const res = await axios.get(`${trimmed}/api/health`, { timeout: 8000 })
    if (!res.data || typeof res.data !== 'object' || !('status' in res.data)) {
      throw new Error(t('setup.error_not_whatisup'))
    }
    setServerUrl(trimmed)
    const target = route.query.redirect || '/login'
    router.replace(target)
  } catch (e) {
    // Surface the real reason so users can diagnose CORS / network / cert issues.
    if (e.response) {
      error.value = `HTTP ${e.response.status} ${e.response.statusText || ''} — ${t('setup.error_not_whatisup')}`
    } else if (e.code === 'ECONNABORTED') {
      error.value = t('setup.error_timeout')
    } else if (e.message?.includes('Network Error')) {
      error.value = t('setup.error_network')
    } else {
      error.value = e.message || t('setup.error_unreachable')
    }
  } finally {
    loading.value = false
  }
}

function skipValidation() {
  try {
    const trimmed = url.value.trim().replace(/\/+$/, '')
    setServerUrl(trimmed)
    const target = route.query.redirect || '/login'
    router.replace(target)
  } catch (e) {
    error.value = e.message
  }
}
</script>
