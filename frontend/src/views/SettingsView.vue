<template>
  <div class="p-8">
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

      <!-- Push notifications -->
      <div class="card">
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

          <div v-if="push.error === 'permission_denied'" class="mb-3 text-sm text-red-400">
            {{ t('settings.push_permission_denied') }}
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
import { onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '../stores/auth'
import { useWebPushStore } from '../stores/webPush'

const { t } = useI18n()
const auth = useAuthStore()
const push = useWebPushStore()

onMounted(() => push.init())
</script>
