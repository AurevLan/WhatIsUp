<template>
  <div class="page-body">
    <h1 class="text-2xl font-bold text-white mb-8">{{ t('settings.title') }}</h1>

    <div class="max-w-xl space-y-6">
      <!-- Profile -->
      <div class="card">
        <h2 class="text-lg font-semibold text-white mb-4">{{ t('settings.account') }}</h2>
        <div class="space-y-3">
          <div>
            <label class="block text-sm text-gray-400 mb-1">{{ t('auth.username') }}</label>
            <p class="text-white">{{ auth.user?.username }}</p>
          </div>
          <div>
            <label class="block text-sm text-gray-400 mb-1">{{ t('auth.email') }}</label>
            <p class="text-white">{{ auth.user?.email }}</p>
          </div>
          <div>
            <label class="block text-sm text-gray-400 mb-1">Role</label>
            <p class="text-white">{{ auth.isSuperadmin ? 'Super Administrator' : 'User' }}</p>
          </div>
        </div>
      </div>

      <!-- Mobile push notifications (Capacitor / FCM) -->
      <div v-if="mobilePush.isAvailable" class="card">
        <h2 class="text-lg font-semibold text-white mb-1">{{ t('settings.mobile_push_title') }}</h2>
        <p class="text-sm text-gray-500 mb-4">{{ t('settings.mobile_push_desc') }}</p>

        <div class="flex items-center gap-2 mb-4">
          <span class="w-2 h-2 rounded-full flex-shrink-0"
            :class="mobilePush.registered ? 'bg-emerald-400' : 'bg-gray-600'" />
          <span class="text-sm" :class="mobilePush.registered ? 'text-emerald-400' : 'text-gray-500'">
            {{ mobilePush.registered ? t('settings.mobile_push_on') : t('settings.mobile_push_off') }}
          </span>
        </div>

        <div v-if="mobilePush.error" class="mb-3 text-sm text-red-400">
          {{ mobilePush.error }}
        </div>

        <div class="flex gap-2 flex-wrap">
          <button v-if="!mobilePush.registered"
            @click="enableMobilePush"
            :disabled="mobilePush.loading"
            class="btn-primary text-sm">
            {{ mobilePush.loading ? t('common.loading') : t('settings.mobile_push_enable') }}
          </button>
          <button v-else
            @click="disableMobilePush"
            :disabled="mobilePush.loading"
            class="btn-ghost text-sm text-red-400">
            {{ t('settings.mobile_push_disable') }}
          </button>
        </div>
      </div>

      <!-- Web push notifications (browser only) -->
      <div v-if="!mobilePush.isAvailable" class="card">
        <h2 class="text-lg font-semibold text-white mb-1">{{ t('settings.push_title') }}</h2>
        <p class="text-sm text-gray-500 mb-4">{{ t('settings.push_desc') }}</p>

        <div v-if="!push.isSupported" class="text-sm text-amber-400">
          {{ t('settings.push_not_supported') }}
        </div>
        <div v-else-if="!push.serverEnabled" class="text-sm text-gray-500">
          {{ t('settings.push_not_configured') }}
        </div>
        <template v-else>
          <div class="flex items-center gap-2 mb-4">
            <span class="w-2 h-2 rounded-full flex-shrink-0"
              :class="push.isSubscribed ? 'bg-emerald-400' : 'bg-gray-600'" />
            <span class="text-sm" :class="push.isSubscribed ? 'text-emerald-400' : 'text-gray-500'">
              {{ push.isSubscribed ? t('settings.push_subscribed') : t('settings.push_not_subscribed') }}
            </span>
          </div>

          <div v-if="push.error" class="mb-3 text-sm text-red-400">
            {{ push.error === 'permission_denied' ? t('settings.push_permission_denied') : push.error }}
          </div>

          <div class="flex gap-2 flex-wrap">
            <button v-if="!push.isSubscribed"
              @click="push.subscribe()"
              :disabled="push.loading"
              class="btn-primary text-sm">
              {{ push.loading ? t('common.loading') : t('settings.push_subscribe') }}
            </button>
            <template v-else>
              <button @click="push.sendTest()" class="btn-secondary text-sm">
                {{ t('settings.push_test') }}
              </button>
              <button @click="push.unsubscribe()" :disabled="push.loading" class="btn-ghost text-sm text-red-400">
                {{ t('settings.push_unsubscribe') }}
              </button>
            </template>
          </div>
        </template>
      </div>

      <!-- Browser Extension -->
      <div class="card">
        <h2 class="text-lg font-semibold text-white mb-1">{{ t('settings.extension_title') }}</h2>
        <p class="text-sm text-gray-500 mb-4">{{ t('settings.extension_desc') }}</p>

        <div class="flex gap-2 flex-wrap mb-4">
          <button @click="downloadExtension" :disabled="extensionLoading" class="btn-primary text-sm">
            {{ extensionLoading ? t('settings.extension_downloading') : t('settings.extension_download') }}
          </button>
        </div>

        <details class="text-sm text-gray-400">
          <summary class="cursor-pointer text-gray-300 hover:text-white mb-2 select-none">
            {{ t('settings.extension_install_title') }}
          </summary>
          <ol class="list-decimal list-inside space-y-1 ml-1 mb-3">
            <li v-html="t('settings.extension_install_step1')" />
            <li v-html="t('settings.extension_install_step2')" />
            <li v-html="t('settings.extension_install_step3')" />
            <li v-html="t('settings.extension_install_step4')" />
            <li v-html="t('settings.extension_install_step5')" />
            <li v-html="t('settings.extension_install_step6')" />
          </ol>
          <p class="text-xs text-gray-500">
            <strong class="text-gray-400">{{ t('settings.extension_features_title') }}:</strong>
            {{ t('settings.extension_features') }}
          </p>
        </details>
      </div>

      <!-- About -->
      <div class="card">
        <h2 class="text-lg font-semibold text-white mb-4">About</h2>
        <div class="space-y-2 text-sm text-gray-400">
          <p>WhatIsUp v0.1.0</p>
          <p>Web monitoring platform with multi-probe geographic correlation</p>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '../stores/auth'
import { useWebPushStore } from '../stores/webPush'
import api from '../api/client'
import {
  isPushAvailable,
  getRegisteredDeviceId,
  registerPushNotifications,
  unregisterPushNotifications,
} from '../lib/pushNotifications'

const { t } = useI18n()
const auth = useAuthStore()
const push = useWebPushStore()
const extensionLoading = ref(false)

const mobilePush = reactive({
  isAvailable: isPushAvailable(),
  registered: !!getRegisteredDeviceId(),
  loading: false,
  error: '',
})

async function enableMobilePush() {
  mobilePush.loading = true
  mobilePush.error = ''
  try {
    const res = await registerPushNotifications()
    if (res.ok) {
      mobilePush.registered = true
    } else {
      mobilePush.error = res.reason === 'permission_denied'
        ? t('settings.push_permission_denied')
        : `${res.reason || 'failed'}${res.error ? ': ' + res.error : ''}`
    }
  } catch (e) {
    mobilePush.error = `unexpected: ${e?.message || e}`
  } finally {
    // Always release the loading flag so the button never stays stuck.
    mobilePush.loading = false
  }
}

async function disableMobilePush() {
  mobilePush.loading = true
  await unregisterPushNotifications()
  mobilePush.registered = false
  mobilePush.loading = false
}

onMounted(() => push.init())

async function downloadExtension() {
  extensionLoading.value = true
  try {
    const res = await api.get('/extension/download', { responseType: 'blob' })
    const url = URL.createObjectURL(res.data)
    const a = document.createElement('a')
    a.href = url
    a.download = 'whatisup-recorder.zip'
    a.click()
    URL.revokeObjectURL(url)
  } catch {
    // silently fail — user sees no download
  } finally {
    extensionLoading.value = false
  }
}
</script>
