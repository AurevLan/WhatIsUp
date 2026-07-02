<template>
  <div class="page-body">
    <h1 class="font-display text-2xl font-bold text-(--text-1) mb-8">{{ t('settings.title') }}</h1>

    <div class="max-w-xl space-y-6">
      <!-- Profile -->
      <div class="card">
        <h2 class="text-lg font-semibold text-(--text-1) mb-4">{{ t('settings.account') }}</h2>
        <div class="space-y-3">
          <div>
            <label class="block text-sm text-(--text-2) mb-1">{{ t('auth.username') }}</label>
            <p class="text-(--text-1)">{{ auth.user?.username }}</p>
          </div>
          <div>
            <label class="block text-sm text-(--text-2) mb-1">{{ t('auth.email') }}</label>
            <p class="text-(--text-1)">{{ auth.user?.email }}</p>
          </div>
          <div>
            <label class="block text-sm text-(--text-2) mb-1">Role</label>
            <p class="text-(--text-1)">{{ auth.isSuperadmin ? 'Super Administrator' : 'User' }}</p>
          </div>
        </div>
      </div>

      <!-- Security — Two-factor authentication + active sessions -->
      <div class="card">
        <h2 class="text-lg font-semibold text-(--text-1) mb-1">{{ t('settings.security.title') }}</h2>
        <p class="text-sm text-(--text-3) mb-4">{{ t('settings.security.desc') }}</p>

        <!-- 2FA status row -->
        <div class="flex items-center gap-2 mb-4">
          <span class="w-2 h-2 rounded-full flex-shrink-0"
            :class="auth.user?.totp_enabled ? 'bg-(--up)' : 'bg-(--bg-surface-3)'" />
          <span class="text-sm" :class="auth.user?.totp_enabled ? 'text-(--up)' : 'text-(--text-3)'">
            {{ auth.user?.totp_enabled ? t('settings.security.totp_on') : t('settings.security.totp_off') }}
          </span>
        </div>

        <div v-if="totp.error" class="mb-3 text-sm text-(--down)">{{ totp.error }}</div>

        <div class="flex gap-2 flex-wrap">
          <button v-if="!auth.user?.totp_enabled"
            @click="startTotpSetup"
            :disabled="totp.loading"
            class="btn-primary">
            {{ totp.loading ? t('common.loading') : t('settings.security.totp_enable') }}
          </button>
          <button v-else
            @click="openDisable"
            class="btn-ghost text-(--down)">
            {{ t('settings.security.totp_disable') }}
          </button>
        </div>

        <!-- Active sessions sub-section -->
        <div class="mt-6 pt-5 border-t border-(--border)">
          <h3 class="text-sm font-semibold text-(--text-1) mb-1">{{ t('settings.security.sessions_title') }}</h3>
          <p class="text-xs text-(--text-3) mb-3">{{ t('settings.security.sessions_desc') }}</p>

          <div v-if="sessions.loading" class="text-sm text-(--text-3)">{{ t('common.loading') }}</div>
          <div v-else-if="sessions.error" class="text-sm text-(--down)">{{ sessions.error }}</div>
          <div v-else-if="sessions.list.length === 0" class="text-sm text-(--text-3)">
            {{ t('settings.security.sessions_empty') }}
          </div>
          <ul v-else class="space-y-2">
            <li v-for="s in sessions.list" :key="s.id"
              class="flex items-center justify-between gap-3 bg-(--bg-surface-2) border border-(--border) rounded-lg px-3 py-2">
              <div class="min-w-0">
                <div class="flex items-center gap-2">
                  <Monitor :size="14" class="text-(--text-2) flex-shrink-0" />
                  <span class="text-sm text-(--text-1) truncate">{{ s.ua || t('settings.security.session_unknown_ua') }}</span>
                  <span v-if="s.current"
                    class="text-[10px] uppercase tracking-wide bg-[color-mix(in_srgb,var(--up)_15%,transparent)] text-(--up) px-1.5 py-0.5 rounded">
                    {{ t('settings.security.session_current') }}
                  </span>
                </div>
                <div class="text-xs text-(--text-3) mt-0.5">
                  {{ s.ip || '—' }} · {{ fmtDate(s.created_at) }}
                </div>
              </div>
              <button v-if="!s.current"
                @click="revokeSession(s.id)"
                class="btn-ghost btn-sm text-(--down) flex-shrink-0">
                {{ t('settings.security.session_revoke') }}
              </button>
            </li>
          </ul>

          <button v-if="sessions.list.length > 1"
            @click="revokeAllSessions"
            class="btn-secondary mt-3">
            {{ t('settings.security.sessions_revoke_all') }}
          </button>
        </div>
      </div>

      <!-- Preferences (T1-13) -->
      <div class="card">
        <h2 class="text-lg font-semibold text-(--text-1) mb-1">{{ t('settings.preferences_title') }}</h2>
        <p class="text-sm text-(--text-3) mb-4">{{ t('settings.preferences_desc') }}</p>

        <label class="block text-sm text-(--text-2) mb-1" for="tz-select">
          {{ t('settings.timezone_label') }}
        </label>
        <select
          id="tz-select"
          v-model="tzPref"
          @change="saveTimezone"
          class="input w-full"
          :aria-invalid="!!tzSaveError"
          :aria-describedby="tzSaveError ? 'tz-save-error' : undefined"
        >
          <option value="">{{ t('settings.timezone_auto', { tz: browserTz }) }}</option>
          <option v-for="tz in commonTimezones" :key="tz" :value="tz">{{ tz }}</option>
        </select>
        <p class="text-xs text-(--text-3) mt-1.5">
          {{ t('settings.timezone_current') }}
          <span class="text-(--text-2) font-mono">{{ activeTz }}</span>
          · {{ t('settings.timezone_now') }}
          <span class="text-(--text-2) font-mono">{{ tzPreview }}</span>
        </p>
        <p v-if="tzSaveError" id="tz-save-error" class="text-xs text-(--down) mt-1">{{ tzSaveError }}</p>
      </div>

      <!-- Mobile push notifications (Capacitor / FCM) -->
      <div v-if="mobilePush.isAvailable" class="card">
        <h2 class="text-lg font-semibold text-(--text-1) mb-1">{{ t('settings.mobile_push_title') }}</h2>
        <p class="text-sm text-(--text-3) mb-4">{{ t('settings.mobile_push_desc') }}</p>

        <div class="flex items-center gap-2 mb-4">
          <span class="w-2 h-2 rounded-full flex-shrink-0"
            :class="mobilePush.registered ? 'bg-(--up)' : 'bg-(--bg-surface-3)'" />
          <span class="text-sm" :class="mobilePush.registered ? 'text-(--up)' : 'text-(--text-3)'">
            {{ mobilePush.registered ? t('settings.mobile_push_on') : t('settings.mobile_push_off') }}
          </span>
        </div>

        <div v-if="mobilePush.error" class="mb-3 text-sm text-(--down)">
          {{ mobilePush.error }}
        </div>

        <div class="flex gap-2 flex-wrap">
          <button v-if="!mobilePush.registered"
            @click="enableMobilePush"
            :disabled="mobilePush.loading"
            class="btn-primary">
            {{ mobilePush.loading ? t('common.loading') : t('settings.mobile_push_enable') }}
          </button>
          <button v-else
            @click="disableMobilePush"
            :disabled="mobilePush.loading"
            class="btn-ghost text-(--down)">
            {{ t('settings.mobile_push_disable') }}
          </button>
        </div>
      </div>

      <!-- Web push notifications (browser only) -->
      <div v-if="!mobilePush.isAvailable" class="card">
        <h2 class="text-lg font-semibold text-(--text-1) mb-1">{{ t('settings.push_title') }}</h2>
        <p class="text-sm text-(--text-3) mb-4">{{ t('settings.push_desc') }}</p>

        <div v-if="!push.isSupported" class="text-sm text-(--warn)">
          {{ t('settings.push_not_supported') }}
        </div>
        <div v-else-if="!push.serverEnabled" class="text-sm text-(--text-3)">
          {{ t('settings.push_not_configured') }}
        </div>
        <template v-else>
          <div class="flex items-center gap-2 mb-4">
            <span class="w-2 h-2 rounded-full flex-shrink-0"
              :class="push.isSubscribed ? 'bg-(--up)' : 'bg-(--bg-surface-3)'" />
            <span class="text-sm" :class="push.isSubscribed ? 'text-(--up)' : 'text-(--text-3)'">
              {{ push.isSubscribed ? t('settings.push_subscribed') : t('settings.push_not_subscribed') }}
            </span>
          </div>

          <div v-if="push.error" class="mb-3 text-sm text-(--down)">
            {{ push.error === 'permission_denied' ? t('settings.push_permission_denied') : push.error }}
          </div>

          <div class="flex gap-2 flex-wrap">
            <button v-if="!push.isSubscribed"
              @click="push.subscribe()"
              :disabled="push.loading"
              class="btn-primary">
              {{ push.loading ? t('common.loading') : t('settings.push_subscribe') }}
            </button>
            <template v-else>
              <button @click="push.sendTest()" class="btn-secondary">
                {{ t('settings.push_test') }}
              </button>
              <button @click="push.unsubscribe()" :disabled="push.loading" class="btn-ghost text-(--down)">
                {{ t('settings.push_unsubscribe') }}
              </button>
            </template>
          </div>
        </template>
      </div>

      <!-- Biometric unlock (Capacitor native only) -->
      <div v-if="biometric.isAvailable" class="card">
        <h2 class="text-lg font-semibold text-(--text-1) mb-1">{{ t('settings.biometric_title') }}</h2>
        <p class="text-sm text-(--text-3) mb-4">{{ t('settings.biometric_desc') }}</p>

        <div class="flex items-center gap-2 mb-4">
          <span class="w-2 h-2 rounded-full flex-shrink-0"
            :class="biometric.enabled ? 'bg-(--up)' : 'bg-(--bg-surface-3)'" />
          <span class="text-sm" :class="biometric.enabled ? 'text-(--up)' : 'text-(--text-3)'">
            {{ biometric.enabled ? t('settings.biometric_on') : t('settings.biometric_off') }}
          </span>
        </div>

        <div v-if="biometric.error" class="mb-3 text-sm text-(--down)">
          {{ biometric.error }}
        </div>

        <div class="flex gap-2 flex-wrap">
          <button v-if="!biometric.enabled"
            @click="enableBiometricUnlock"
            :disabled="biometric.loading"
            class="btn-primary">
            {{ biometric.loading ? t('common.loading') : t('settings.biometric_enable') }}
          </button>
          <button v-else
            @click="disableBiometricUnlock"
            :disabled="biometric.loading"
            class="btn-ghost text-(--down)">
            {{ t('settings.biometric_disable') }}
          </button>
        </div>
      </div>

      <!-- Browser Extension -->
      <div class="card">
        <h2 class="text-lg font-semibold text-(--text-1) mb-1">{{ t('settings.extension_title') }}</h2>
        <p class="text-sm text-(--text-3) mb-4">{{ t('settings.extension_desc') }}</p>

        <div class="flex gap-2 flex-wrap mb-4">
          <button @click="downloadExtension" :disabled="extensionLoading" class="btn-primary">
            {{ extensionLoading ? t('settings.extension_downloading') : t('settings.extension_download') }}
          </button>
        </div>

        <details class="text-sm text-(--text-2)">
          <summary class="cursor-pointer text-(--text-2) hover:text-(--text-1) mb-2 select-none">
            {{ t('settings.extension_install_title') }}
          </summary>
          <ol class="list-decimal list-inside space-y-1 ml-1 mb-3">
            <li>{{ t('settings.extension_install_step1') }}</li>
            <li>{{ t('settings.extension_install_step2') }}</li>
            <li>
              <i18n-t keypath="settings.extension_install_step3" tag="span">
                <template #bold1><strong>{{ t('settings.extension_install_step3_bold1') }}</strong></template>
                <template #bold2><strong>{{ t('settings.extension_install_step3_bold2') }}</strong></template>
              </i18n-t>
            </li>
            <li>
              <i18n-t keypath="settings.extension_install_step4" tag="span">
                <template #bold><strong>{{ t('settings.extension_install_step4_bold') }}</strong></template>
              </i18n-t>
            </li>
            <li>
              <i18n-t keypath="settings.extension_install_step5" tag="span">
                <template #bold><strong>{{ t('settings.extension_install_step5_bold') }}</strong></template>
              </i18n-t>
            </li>
            <li>{{ t('settings.extension_install_step6') }}</li>
          </ol>
          <p class="text-xs text-(--text-3)">
            <strong class="text-(--text-2)">{{ t('settings.extension_features_title') }}:</strong>
            {{ t('settings.extension_features') }}
          </p>
        </details>
      </div>

      <!-- About -->
      <div class="card">
        <h2 class="text-lg font-semibold text-(--text-1) mb-4">About</h2>
        <div class="space-y-2 text-sm text-(--text-2)">
          <p>WhatIsUp v{{ APP_VERSION }}</p>
          <p>Web monitoring platform with multi-probe geographic correlation</p>
        </div>
      </div>
    </div>

    <!-- TOTP setup modal (QR + first code) -->
    <BaseModal
      :model-value="totp.setupOpen"
      :title="t('settings.security.setup_title')"
      :message="t('settings.security.setup_desc')"
      @close="closeTotpSetup">
      <div v-if="totp.qrDataUrl" class="flex justify-center mb-3">
        <img :src="totp.qrDataUrl" alt="TOTP QR code"
          class="rounded-lg bg-white p-2" width="192" height="192" />
      </div>
      <div v-else-if="totp.otpauthUrl" class="mb-3 text-sm text-(--warn)">
        {{ t('settings.security.setup_qr_fallback') }}
        <a :href="totp.otpauthUrl" class="text-(--accent) break-all underline">{{ totp.otpauthUrl }}</a>
      </div>

      <p class="text-xs text-(--text-3) mb-1">{{ t('settings.security.setup_manual') }}</p>
      <code class="block w-full bg-(--bg-surface-2) border border-(--border) rounded-lg px-3 py-2 text-sm text-(--up) font-mono break-all mb-4">
        {{ totp.secret }}
      </code>

      <label class="block text-sm text-(--text-2) mb-1">{{ t('settings.security.setup_code_label') }}</label>
      <input v-model="totp.code" class="input w-full" placeholder="123456"
        inputmode="numeric" autocomplete="one-time-code"
        @keydown.enter="confirmEnable" />

      <div v-if="totp.enableError" class="mt-2 text-sm text-(--down)">{{ totp.enableError }}</div>

      <template #footer>
        <button class="btn-secondary ml-auto" @click="closeTotpSetup">{{ t('common.cancel') }}</button>
        <button class="btn-primary" :disabled="!totp.code.trim() || totp.enabling" @click="confirmEnable">
          <Loader2 v-if="totp.enabling" class="w-4 h-4 mr-2 animate-spin" />
          {{ t('settings.security.setup_confirm') }}
        </button>
      </template>
    </BaseModal>

    <!-- Recovery codes reveal modal (shown once) -->
    <BaseModal
      :model-value="recoveryCodes.length > 0"
      @close="recoveryCodes = []">
      <template #header>
        <div class="flex items-center gap-3">
          <CheckCircle class="w-6 h-6 text-(--up) flex-shrink-0" />
          <h2 class="text-lg font-semibold text-(--text-1)">{{ t('settings.security.recovery_title') }}</h2>
        </div>
      </template>
      <p class="text-sm text-(--warn) mb-3">{{ t('settings.security.recovery_warning') }}</p>

      <div class="relative">
        <ul class="grid grid-cols-2 gap-2 bg-(--bg-surface-2) border border-(--border) rounded-lg p-3 pr-12">
          <li v-for="c in recoveryCodes" :key="c" class="text-sm text-(--up) font-mono">{{ c }}</li>
        </ul>
        <button class="absolute right-2 top-2 text-(--text-2) hover:text-(--text-1) transition-colors"
          :title="t('common.copy')" :aria-label="t('common.copy')" @click="copyRecoveryCodes">
          <Copy class="w-4 h-4" />
        </button>
      </div>

      <template #footer>
        <button class="btn-primary ml-auto" @click="recoveryCodes = []">{{ t('settings.security.recovery_saved') }}</button>
      </template>
    </BaseModal>

    <!-- Disable 2FA modal (password + code) -->
    <BaseModal
      :model-value="disable.open"
      :title="t('settings.security.disable_title')"
      :message="t('settings.security.disable_desc')"
      @close="disable.open = false">
      <label class="block text-sm text-(--text-2) mb-1">{{ t('auth.password') }}</label>
      <input v-model="disable.password" type="password" class="input w-full mb-3"
        autocomplete="current-password" />

      <label class="block text-sm text-(--text-2) mb-1">{{ t('settings.security.setup_code_label') }}</label>
      <input v-model="disable.code" class="input w-full" placeholder="123456"
        inputmode="text" autocomplete="one-time-code" @keydown.enter="confirmDisable" />

      <div v-if="disable.error" class="mt-2 text-sm text-(--down)">{{ disable.error }}</div>

      <template #footer>
        <button class="btn-secondary ml-auto" @click="disable.open = false">{{ t('common.cancel') }}</button>
        <button class="btn-danger"
          :disabled="!disable.password || !disable.code.trim() || disable.loading" @click="confirmDisable">
          <Loader2 v-if="disable.loading" class="w-4 h-4 mr-2 animate-spin" />
          {{ t('settings.security.disable_confirm') }}
        </button>
      </template>
    </BaseModal>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import QRCode from 'qrcode'
import { CheckCircle, Copy, Loader2, Monitor } from 'lucide-vue-next'
import BaseModal from '../components/BaseModal.vue'
import { useAuthStore } from '../stores/auth'
import { useWebPushStore } from '../stores/webPush'
import { useTimezone } from '../composables/useTimezone'
import { useToast } from '../composables/useToast'
import { useConfirm } from '../composables/useConfirm'
import { useDateFormat } from '../composables/useDateFormat'
import { authApi } from '../api/auth'
import api from '../api/client'
import {
  isPushAvailable,
  getRegisteredDeviceId,
  registerPushNotifications,
  unregisterPushNotifications,
} from '../lib/pushNotifications'
import {
  disableBiometric,
  enableBiometric,
  isBiometricAvailable,
  isBiometricEnabled,
} from '../lib/biometricAuth'
import { APP_VERSION } from '../lib/appVersion'

const { t, locale } = useI18n()
const { success, error: toastError } = useToast()
const { confirm } = useConfirm()
const { formatDate: fmtDate } = useDateFormat()
const auth = useAuthStore()
const push = useWebPushStore()
const extensionLoading = ref(false)

// ── Two-factor authentication ────────────────────────────────────────────────
const totp = reactive({
  loading: false,      // setup() in-flight
  error: '',           // status-row error
  setupOpen: false,
  secret: '',
  otpauthUrl: '',
  qrDataUrl: '',
  code: '',
  enabling: false,     // enable() in-flight
  enableError: '',
})
const recoveryCodes = ref([])
const disable = reactive({ open: false, password: '', code: '', loading: false, error: '' })

async function startTotpSetup() {
  totp.loading = true
  totp.error = ''
  try {
    const { data } = await authApi.totpSetup({ skipErrorToast: true })
    totp.secret = data.secret
    totp.otpauthUrl = data.otpauth_url
    totp.code = ''
    totp.enableError = ''
    totp.qrDataUrl = ''
    try {
      totp.qrDataUrl = await QRCode.toDataURL(data.otpauth_url, { width: 192, margin: 1 })
    } catch {
      // QR generation failed — modal falls back to the otpauth link + secret.
    }
    totp.setupOpen = true
  } catch (e) {
    totp.error = e.response?.data?.detail || t('settings.security.error_generic')
  } finally {
    totp.loading = false
  }
}

function closeTotpSetup() {
  totp.setupOpen = false
  totp.secret = ''
  totp.otpauthUrl = ''
  totp.qrDataUrl = ''
  totp.code = ''
  totp.enableError = ''
}

async function confirmEnable() {
  if (!totp.code.trim()) return
  totp.enabling = true
  totp.enableError = ''
  try {
    const { data } = await authApi.totpEnable(totp.code.trim(), { skipErrorToast: true })
    if (auth.user) auth.user.totp_enabled = true
    closeTotpSetup()
    recoveryCodes.value = data.recovery_codes || []
    success(t('settings.security.totp_enabled_toast'))
  } catch (e) {
    totp.enableError = e.response?.data?.detail || t('settings.security.invalid_code')
  } finally {
    totp.enabling = false
  }
}

async function copyRecoveryCodes() {
  try {
    await navigator.clipboard.writeText(recoveryCodes.value.join('\n'))
    success(t('common.copied'))
  } catch {
    toastError(t('settings.security.copy_failed'))
  }
}

function openDisable() {
  disable.open = true
  disable.password = ''
  disable.code = ''
  disable.error = ''
}

async function confirmDisable() {
  if (!disable.password || !disable.code.trim()) return
  disable.loading = true
  disable.error = ''
  try {
    await authApi.totpDisable(disable.password, disable.code.trim(), { skipErrorToast: true })
    if (auth.user) auth.user.totp_enabled = false
    disable.open = false
    success(t('settings.security.totp_disabled_toast'))
  } catch (e) {
    disable.error = e.response?.data?.detail || t('settings.security.invalid_code')
  } finally {
    disable.loading = false
  }
}

// ── Active sessions ──────────────────────────────────────────────────────────
const sessions = reactive({ list: [], loading: false, error: '' })

async function loadSessions() {
  const refresh = localStorage.getItem('refresh_token')
  if (!refresh) return
  sessions.loading = true
  sessions.error = ''
  try {
    const { data } = await authApi.sessionsList(refresh, { skipErrorToast: true })
    sessions.list = data || []
  } catch (e) {
    sessions.error = e.response?.data?.detail || t('settings.security.sessions_error')
  } finally {
    sessions.loading = false
  }
}

async function revokeSession(id) {
  const ok = await confirm({
    title: t('settings.security.session_revoke'),
    message: t('settings.security.session_revoke_confirm'),
    confirmLabel: t('settings.security.session_revoke'),
  })
  if (!ok) return
  try {
    await authApi.sessionRevoke(id, { skipErrorToast: true })
    sessions.list = sessions.list.filter((s) => s.id !== id)
    success(t('settings.security.session_revoked_toast'))
  } catch (e) {
    toastError(e.response?.data?.detail || t('settings.security.error_generic'))
  }
}

async function revokeAllSessions() {
  const ok = await confirm({
    title: t('settings.security.sessions_revoke_all'),
    message: t('settings.security.sessions_revoke_all_confirm'),
    confirmLabel: t('settings.security.sessions_revoke_all'),
  })
  if (!ok) return
  const refresh = localStorage.getItem('refresh_token')
  if (!refresh) return
  try {
    await authApi.sessionsRevokeAll(refresh, { skipErrorToast: true })
    await loadSessions()
    success(t('settings.security.sessions_revoked_all_toast'))
  } catch (e) {
    toastError(e.response?.data?.detail || t('settings.security.error_generic'))
  }
}

// ── Timezone preference (T1-13) ───────────────────────────────────────────────
const { timezone: activeTz, format: tzFormat } = useTimezone()
const tzPref = ref(auth.user?.timezone || '')
const tzSaveError = ref('')
const browserTz = (() => {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC'
  } catch {
    return 'UTC'
  }
})()
// A curated short list covers > 95% of usage without overwhelming the user
// with the 600+ IANA zones. Free-form typing in a <select> isn't great either.
const commonTimezones = [
  'UTC',
  'Europe/Paris', 'Europe/London', 'Europe/Berlin', 'Europe/Madrid', 'Europe/Rome',
  'Europe/Amsterdam', 'Europe/Brussels', 'Europe/Zurich', 'Europe/Lisbon', 'Europe/Warsaw',
  'Europe/Moscow', 'Europe/Athens', 'Europe/Dublin', 'Europe/Stockholm',
  'America/New_York', 'America/Chicago', 'America/Denver', 'America/Los_Angeles',
  'America/Toronto', 'America/Vancouver', 'America/Mexico_City', 'America/Sao_Paulo',
  'America/Argentina/Buenos_Aires',
  'Asia/Tokyo', 'Asia/Shanghai', 'Asia/Hong_Kong', 'Asia/Singapore', 'Asia/Seoul',
  'Asia/Kolkata', 'Asia/Dubai', 'Asia/Tel_Aviv', 'Asia/Bangkok', 'Asia/Jakarta',
  'Australia/Sydney', 'Australia/Melbourne', 'Pacific/Auckland',
  'Africa/Cairo', 'Africa/Johannesburg', 'Africa/Lagos',
]
const tzPreview = computed(() => tzFormat(new Date(), { hour: '2-digit', minute: '2-digit', timeZoneName: 'short' }, locale.value))

async function saveTimezone() {
  tzSaveError.value = ''
  try {
    const { data } = await api.patch('/auth/me', { timezone: tzPref.value || null }, { skipErrorToast: true })
    // Update the auth store so the rest of the app reacts immediately.
    if (auth.user) auth.user.timezone = data.timezone
  } catch (e) {
    tzSaveError.value = e.response?.data?.detail?.[0]?.msg || 'Failed to save timezone'
    tzPref.value = auth.user?.timezone || ''
  }
}

const mobilePush = reactive({
  isAvailable: isPushAvailable(),
  registered: !!getRegisteredDeviceId(),
  loading: false,
  error: '',
})

const biometric = reactive({
  isAvailable: false,
  enabled: isBiometricEnabled(),
  loading: false,
  error: '',
})

async function enableBiometricUnlock() {
  biometric.loading = true
  biometric.error = ''
  try {
    const refresh = localStorage.getItem('refresh_token')
    if (!refresh) {
      biometric.error = t('settings.biometric_no_session')
      return
    }
    const ok = await enableBiometric(refresh, { reason: t('settings.biometric_reason_enable') })
    if (!ok) {
      biometric.error = t('settings.biometric_enroll_failed')
      return
    }
    biometric.enabled = true
  } finally {
    biometric.loading = false
  }
}

async function disableBiometricUnlock() {
  biometric.loading = true
  await disableBiometric()
  biometric.enabled = false
  biometric.loading = false
}

async function enableMobilePush() {
  mobilePush.loading = true
  mobilePush.error = ''
  try {
    const res = await registerPushNotifications()
    if (res.ok) {
      mobilePush.registered = true
    } else if (res.reason === 'permission_denied') {
      mobilePush.error = t('settings.push_permission_denied')
    } else if (res.reason === 'fcm_unavailable' || res.reason === 'fcm_error' || res.reason === 'register_call_failed') {
      mobilePush.error = t('settings.mobile_push_fcm_unavailable')
    } else {
      mobilePush.error = `${res.reason || 'failed'}${res.error ? ': ' + res.error : ''}`
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

onMounted(async () => {
  push.init()
  biometric.isAvailable = await isBiometricAvailable()
  loadSessions()
})

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
