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
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '../stores/auth'

const { t } = useI18n()
const auth = useAuthStore()
</script>
