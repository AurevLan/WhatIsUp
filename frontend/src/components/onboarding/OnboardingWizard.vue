<template>
  <div class="onboarding">
    <div class="onboarding__card">

      <!-- Progress dots -->
      <div class="onboarding__progress">
        <div
          v-for="i in totalSteps"
          :key="i"
          class="onboarding__dot"
          :class="{ 'onboarding__dot--active': i === step, 'onboarding__dot--done': i < step }"
        />
      </div>

      <!-- Step 1: Welcome -->
      <div v-if="step === 1" class="onboarding__step">
        <div class="onboarding__icon">
          <Sparkles :size="28" />
        </div>
        <h2 class="onboarding__title">{{ t('onboarding.welcome_title') }}</h2>
        <p class="onboarding__text">{{ t('onboarding.welcome_text') }}</p>

        <div class="onboarding__field">
          <label class="onboarding__label">{{ t('onboarding.display_name') }}</label>
          <input v-model="displayName" type="text" class="input" :placeholder="t('onboarding.display_name_placeholder')" />
        </div>

        <div class="onboarding__actions">
          <button @click="skipAll" class="btn-ghost">{{ t('onboarding.skip') }}</button>
          <button @click="nextStep" class="btn-primary">{{ t('onboarding.next') }}</button>
        </div>
      </div>

      <!-- Step 2: First Monitor -->
      <div v-if="step === 2" class="onboarding__step">
        <div class="onboarding__icon">
          <Activity :size="28" />
        </div>
        <h2 class="onboarding__title">{{ t('onboarding.monitor_title') }}</h2>
        <p class="onboarding__text">{{ t('onboarding.monitor_text') }}</p>

        <!-- Preset cards -->
        <div class="onboarding__presets">
          <button
            v-for="preset in monitorPresets"
            :key="preset.type"
            class="onboarding__preset"
            :class="{ 'onboarding__preset--selected': selectedPreset === preset.type }"
            @click="selectedPreset = preset.type"
          >
            <component :is="preset.icon" :size="20" />
            <span class="onboarding__preset-name">{{ preset.label }}</span>
            <span class="onboarding__preset-desc">{{ preset.desc }}</span>
          </button>
        </div>

        <div class="onboarding__field">
          <label class="onboarding__label">{{ selectedPreset === 'ping' ? t('onboarding.host') : 'URL' }}</label>
          <input
            v-model="monitorUrl"
            type="text"
            class="input"
            :placeholder="selectedPreset === 'ping' ? 'server.example.com' : 'https://example.com'"
          />
        </div>

        <div class="onboarding__field">
          <label class="onboarding__label">{{ t('onboarding.monitor_name') }}</label>
          <input v-model="monitorName" type="text" class="input" :placeholder="t('onboarding.monitor_name_placeholder')" />
        </div>

        <div class="onboarding__actions">
          <button @click="step--" class="btn-ghost">{{ t('onboarding.back') }}</button>
          <button @click="createMonitor" :disabled="!monitorUrl || creatingMonitor" class="btn-primary">
            <span v-if="creatingMonitor" class="onboarding__spinner" />
            {{ creatingMonitor ? t('onboarding.creating') : t('onboarding.create_monitor') }}
          </button>
        </div>

        <button v-if="!creatingMonitor" @click="nextStep" class="onboarding__skip-link">
          {{ t('onboarding.skip_step') }}
        </button>
      </div>

      <!-- Step 3: First Alert -->
      <div v-if="step === 3" class="onboarding__step">
        <div class="onboarding__icon">
          <Bell :size="28" />
        </div>
        <h2 class="onboarding__title">{{ t('onboarding.alert_title') }}</h2>
        <p class="onboarding__text">{{ t('onboarding.alert_text') }}</p>

        <div class="onboarding__field">
          <label class="onboarding__label">{{ t('onboarding.alert_email') }}</label>
          <input v-model="alertEmail" type="email" class="input" :placeholder="t('onboarding.alert_email_placeholder')" />
        </div>

        <div class="onboarding__actions">
          <button @click="step--" class="btn-ghost">{{ t('onboarding.back') }}</button>
          <button @click="createAlertChannel" :disabled="!alertEmail || creatingAlert" class="btn-primary">
            <span v-if="creatingAlert" class="onboarding__spinner" />
            {{ creatingAlert ? t('onboarding.creating') : t('onboarding.create_alert') }}
          </button>
        </div>

        <button v-if="!creatingAlert" @click="nextStep" class="onboarding__skip-link">
          {{ t('onboarding.skip_step') }}
        </button>
      </div>

      <!-- Step 4: Done -->
      <div v-if="step === 4" class="onboarding__step">
        <div class="onboarding__icon onboarding__icon--success">
          <CheckCircle2 :size="28" />
        </div>
        <h2 class="onboarding__title">{{ t('onboarding.done_title') }}</h2>
        <p class="onboarding__text">{{ t('onboarding.done_text') }}</p>

        <div class="onboarding__summary">
          <div v-if="monitorCreated" class="onboarding__summary-item onboarding__summary-item--ok">
            <Check :size="14" /> {{ t('onboarding.monitor_created') }}
          </div>
          <div v-if="alertCreated" class="onboarding__summary-item onboarding__summary-item--ok">
            <Check :size="14" /> {{ t('onboarding.alert_created') }}
          </div>
        </div>

        <div class="onboarding__actions onboarding__actions--center">
          <button @click="finish" class="btn-primary">
            {{ t('onboarding.go_dashboard') }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { Activity, Bell, Check, CheckCircle2, Globe, Server, Sparkles } from 'lucide-vue-next'
import api from '../../api/client'
import { useMonitorStore } from '../../stores/monitors'
import { useAuthStore } from '../../stores/auth'

const { t } = useI18n()
const emit = defineEmits(['complete'])
const monitorStore = useMonitorStore()
const auth = useAuthStore()

const totalSteps = 4
const step = ref(1)

// Step 1
const displayName = ref(auth.user?.full_name || '')

// Step 2
const selectedPreset = ref('http')
const monitorUrl = ref('')
const monitorName = ref('')
const creatingMonitor = ref(false)
const monitorCreated = ref(false)

const monitorPresets = [
  { type: 'http', label: 'Website', desc: 'HTTP(S) status check', icon: Globe },
  { type: 'ping', label: 'Server', desc: 'ICMP ping check', icon: Server },
  { type: 'json_path', label: 'API', desc: 'JSON response check', icon: Activity },
]

// Step 3
const alertEmail = ref(auth.user?.email || '')
const creatingAlert = ref(false)
const alertCreated = ref(false)

function nextStep() {
  if (step.value < totalSteps) step.value++
}

async function skipAll() {
  await completeOnboarding()
  emit('complete')
}

async function createMonitor() {
  creatingMonitor.value = true
  try {
    const name = monitorName.value || new URL(monitorUrl.value).hostname || 'My Monitor'
    const url = selectedPreset.value === 'ping' && !monitorUrl.value.includes('://')
      ? `https://${monitorUrl.value}`
      : monitorUrl.value

    await api.post('/monitors', {
      name,
      url,
      check_type: selectedPreset.value,
      interval_seconds: 60,
      timeout_seconds: 10,
      expected_status_codes: [200],
    })
    monitorCreated.value = true
    monitorStore.fetchAll()
    nextStep()
  } catch (e) {
    // Silently continue on error — user can create monitors later
    nextStep()
  } finally {
    creatingMonitor.value = false
  }
}

async function createAlertChannel() {
  creatingAlert.value = true
  try {
    await api.post('/alerts/channels', {
      name: 'Email alerts',
      type: 'email',
      config: { to: [alertEmail.value] },
    })
    alertCreated.value = true

    // Auto-create default rules if a monitor was created
    if (monitorCreated.value) {
      try {
        const { data: monitors } = await api.get('/monitors')
        if (monitors.length > 0) {
          await api.post(`/alerts/auto-rules/${monitors[0].id}`)
        }
      } catch {}
    }
    nextStep()
  } catch {
    nextStep()
  } finally {
    creatingAlert.value = false
  }
}

async function completeOnboarding() {
  try {
    if (displayName.value && displayName.value !== auth.user?.full_name) {
      await api.patch('/auth/me', { full_name: displayName.value })
    }
    await api.post('/onboarding/complete')
  } catch {}
}

async function finish() {
  await completeOnboarding()
  emit('complete')
}
</script>

<style scoped>
.onboarding {
  display: flex;
  justify-content: center;
  padding: 2rem 1rem 3rem;
}

.onboarding__card {
  width: 100%;
  max-width: 480px;
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: 2rem;
  box-shadow: var(--shadow-card);
}

.onboarding__progress {
  display: flex;
  justify-content: center;
  gap: 8px;
  margin-bottom: 2rem;
}

.onboarding__dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--border);
  transition: background .2s, transform .2s;
}
.onboarding__dot--active {
  background: var(--accent);
  transform: scale(1.3);
}
.onboarding__dot--done {
  background: var(--up);
}

.onboarding__step {
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
}

.onboarding__icon {
  width: 56px;
  height: 56px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 16px;
  background: var(--accent-glow);
  color: var(--accent);
  margin-bottom: 1.25rem;
}
.onboarding__icon--success {
  background: rgba(52,211,153,.12);
  color: var(--up);
}

.onboarding__title {
  font-size: 1.125rem;
  font-weight: 700;
  color: var(--text-1);
  margin: 0 0 0.5rem;
}

.onboarding__text {
  font-size: 0.8125rem;
  color: var(--text-2);
  margin: 0 0 1.5rem;
  line-height: 1.6;
  max-width: 360px;
}

.onboarding__field {
  width: 100%;
  text-align: left;
  margin-bottom: 1rem;
}

.onboarding__label {
  display: block;
  font-size: 0.75rem;
  font-weight: 600;
  color: var(--text-2);
  margin-bottom: 0.375rem;
  text-transform: uppercase;
  letter-spacing: .04em;
}

.onboarding__presets {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 0.75rem;
  width: 100%;
  margin-bottom: 1.25rem;
}

.onboarding__preset {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.375rem;
  padding: 0.875rem 0.5rem;
  background: var(--bg-surface-2);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  cursor: pointer;
  transition: border-color .15s, background .15s;
  color: var(--text-2);
  font-family: inherit;
}
.onboarding__preset:hover {
  border-color: var(--border-hover);
  background: var(--bg-surface-3);
}
.onboarding__preset--selected {
  border-color: var(--accent-border);
  background: var(--accent-glow);
  color: var(--accent);
}

.onboarding__preset-name {
  font-size: 0.8125rem;
  font-weight: 600;
}
.onboarding__preset-desc {
  font-size: 0.6875rem;
  color: var(--text-3);
}
.onboarding__preset--selected .onboarding__preset-desc {
  color: var(--accent);
  opacity: 0.7;
}

.onboarding__actions {
  display: flex;
  justify-content: space-between;
  width: 100%;
  margin-top: 0.5rem;
  gap: 0.75rem;
}
.onboarding__actions--center {
  justify-content: center;
}

.onboarding__skip-link {
  background: none;
  border: none;
  cursor: pointer;
  color: var(--text-3);
  font-size: 0.75rem;
  font-family: inherit;
  margin-top: 1rem;
  padding: 0;
  transition: color .15s;
}
.onboarding__skip-link:hover {
  color: var(--text-2);
}

.onboarding__summary {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  margin-bottom: 1.5rem;
  width: 100%;
}
.onboarding__summary-item {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.625rem 0.875rem;
  border-radius: var(--radius-sm);
  font-size: 0.8125rem;
}
.onboarding__summary-item--ok {
  background: rgba(52,211,153,.08);
  color: var(--up);
  border: 1px solid rgba(52,211,153,.2);
}

.onboarding__spinner {
  width: 14px;
  height: 14px;
  border: 2px solid transparent;
  border-top-color: currentColor;
  border-radius: 50%;
  animation: spin .6s linear infinite;
  display: inline-block;
}
@keyframes spin {
  to { transform: rotate(360deg); }
}
</style>
