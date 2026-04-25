<template>
  <BaseModal :title="t('monitors.add')" size="lg" @close="$emit('close')">
    <!-- Step indicator -->
    <div class="wizard__steps">
      <div
        v-for="(label, i) in stepLabels"
        :key="i"
        class="wizard__step"
        :class="{
          'wizard__step--current': step === i + 1,
          'wizard__step--done': step > i + 1,
        }"
      >
        <span class="wizard__step-num">{{ i + 1 }}</span>
        <span class="wizard__step-label">{{ label }}</span>
      </div>
    </div>

    <div class="wizard__body">
      <!-- ── Step 1: type ──────────────────────────────────────────── -->
      <section v-show="step === 1" class="space-y-4">
        <div>
          <label class="block text-sm font-medium text-gray-300 mb-2">
            {{ t('create_monitor.check_type') }}
          </label>
          <div class="grid grid-cols-2 sm:grid-cols-4 gap-2">
            <button
              v-for="ct in supportedTypes" :key="ct.value" type="button"
              @click="form.check_type = ct.value"
              class="wizard__type-card"
              :class="{ 'wizard__type-card--selected': form.check_type === ct.value }"
            >
              <div class="text-2xl mb-1">{{ ct.icon }}</div>
              <div class="text-sm font-semibold">{{ ct.label }}</div>
              <div class="text-xs text-gray-500 mt-1">{{ ct.description }}</div>
            </button>
          </div>
          <p v-if="!form.check_type" class="text-xs text-gray-500 mt-2">
            {{ t('wizard.pick_type_hint') }}
          </p>
          <button
            type="button"
            class="mt-3 text-xs text-blue-400 hover:text-blue-300 underline"
            @click="$emit('switch-advanced')"
          >
            {{ t('wizard.advanced_link') }}
          </button>
        </div>
      </section>

      <!-- ── Step 2: target ───────────────────────────────────────── -->
      <section v-show="step === 2" class="space-y-4">
        <div>
          <label class="block text-sm font-medium text-gray-300 mb-1">{{ t('common.name') }} *</label>
          <input v-model="form.name" class="input w-full" :placeholder="currentType?.namePlaceholder" required />
        </div>

        <div v-if="form.check_type === 'http'">
          <label class="block text-sm font-medium text-gray-300 mb-1">{{ t('create_monitor.url') }} *</label>
          <input v-model="form.url" type="url" class="input w-full" placeholder="https://example.com/health" />
        </div>

        <div v-else-if="form.check_type === 'tcp'" class="grid grid-cols-2 gap-3">
          <div>
            <label class="block text-sm font-medium text-gray-300 mb-1">{{ t('create_monitor.host') }} *</label>
            <input v-model="form.url" class="input w-full" placeholder="db.example.com" />
          </div>
          <div>
            <label class="block text-sm font-medium text-gray-300 mb-1">{{ t('create_monitor.port') }} *</label>
            <input v-model.number="form.tcp_port" type="number" min="1" max="65535" class="input w-full" placeholder="5432" />
          </div>
        </div>

        <div v-else-if="form.check_type === 'dns'">
          <label class="block text-sm font-medium text-gray-300 mb-1">{{ t('create_monitor.dns_hostname') }} *</label>
          <input v-model="form.url" class="input w-full" placeholder="example.com" />
        </div>

        <div v-else-if="form.check_type === 'heartbeat'" class="space-y-2">
          <label class="block text-sm font-medium text-gray-300 mb-1">{{ t('create_monitor.heartbeat_slug') }} *</label>
          <input v-model="form.heartbeat_slug" class="input w-full" pattern="[a-z0-9\-]+" placeholder="cron-backup" />
          <p class="text-xs text-gray-500">
            <code class="font-mono text-blue-400">POST /api/v1/ping/{{ form.heartbeat_slug || 'your-slug' }}</code>
          </p>
        </div>

        <div v-if="['http', 'tcp', 'dns'].includes(form.check_type)" class="grid grid-cols-2 gap-3">
          <div>
            <label class="block text-xs text-gray-400 mb-1">{{ t('create_monitor.interval') }}</label>
            <input v-model.number="form.interval_seconds" type="number" min="30" class="input w-full" />
          </div>
          <div>
            <label class="block text-xs text-gray-400 mb-1">{{ t('create_monitor.timeout') }}</label>
            <input v-model.number="form.timeout_seconds" type="number" min="1" max="60" class="input w-full" />
          </div>
        </div>
      </section>

      <!-- ── Step 3: notifications + review ───────────────────────── -->
      <section v-show="step === 3" class="space-y-4">
        <h3 class="text-sm font-medium text-white">{{ t('wizard.review_title') }}</h3>
        <div class="rounded-lg border border-gray-800 p-3 text-xs text-gray-300 space-y-1">
          <p><span class="text-gray-500">{{ t('common.name') }}:</span> {{ form.name || '—' }}</p>
          <p><span class="text-gray-500">{{ t('create_monitor.check_type') }}:</span> {{ currentType?.label }}</p>
          <p v-if="form.check_type === 'tcp'">
            <span class="text-gray-500">{{ t('create_monitor.host') }}:</span> {{ form.url }}:{{ form.tcp_port }}
          </p>
          <p v-else-if="form.check_type === 'heartbeat'">
            <span class="text-gray-500">slug:</span> {{ form.heartbeat_slug }}
          </p>
          <p v-else>
            <span class="text-gray-500">target:</span> {{ form.url }}
          </p>
        </div>

        <div>
          <h3 class="text-sm font-medium text-white mb-2">{{ t('monitors.alert_setup.title') }}</h3>
          <div v-if="alertChannels.length === 0" class="text-xs text-amber-400 bg-amber-900/20 border border-amber-800/40 rounded-lg px-3 py-2">
            {{ t('monitors.alert_setup.no_channels') }}
          </div>
          <div v-else class="space-y-1.5">
            <label
              v-for="ch in alertChannels" :key="ch.id"
              class="flex items-center gap-2 px-3 py-2 rounded-lg border cursor-pointer transition-colors"
              :class="selectedChannelIds.includes(ch.id)
                ? 'border-blue-600/60 bg-blue-950/30'
                : 'border-gray-800 hover:border-gray-700'"
            >
              <input type="checkbox" :value="ch.id" v-model="selectedChannelIds"
                class="rounded bg-gray-800 border-gray-600 text-blue-500" />
              <span class="text-sm text-gray-300">{{ ch.name }}</span>
              <span class="text-xs text-gray-600 ml-auto">{{ ch.type }}</span>
            </label>
          </div>
        </div>

        <div v-if="error" class="bg-red-900/40 border border-red-700 rounded p-3 text-xs text-red-300">
          {{ error }}
        </div>
      </section>
    </div>

    <template #footer>
      <button v-if="step > 1" type="button" @click="step--" class="btn-secondary">
        {{ t('wizard.back') }}
      </button>
      <button v-if="step < 3" type="button" @click="goNext" :disabled="!canAdvance" class="btn-primary flex-1 disabled:opacity-50">
        {{ t('wizard.next') }}
      </button>
      <button v-else type="button" @click="submit" :disabled="loading" class="btn-primary flex-1 disabled:opacity-50">
        {{ loading ? t('common.loading') : t('monitors.add') }}
      </button>
    </template>
  </BaseModal>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useMonitorStore } from '../../stores/monitors'
import api from '../../api/client'
import BaseModal from '../BaseModal.vue'

const { t } = useI18n()
const emit = defineEmits(['close', 'created', 'switch-advanced'])
const monitorStore = useMonitorStore()

const step = ref(1)
const loading = ref(false)
const error = ref('')

const stepLabels = computed(() => [
  t('wizard.step_type'),
  t('wizard.step_target'),
  t('wizard.step_notifications'),
])

const supportedTypes = computed(() => [
  { value: 'http',      icon: '🌐', label: 'HTTP',      description: t('create_monitor.type_http_desc'),      namePlaceholder: 'API status' },
  { value: 'tcp',       icon: '🔌', label: 'TCP',       description: t('create_monitor.type_tcp_desc'),       namePlaceholder: 'PostgreSQL' },
  { value: 'dns',       icon: '🌍', label: 'DNS',       description: t('create_monitor.type_dns_desc'),       namePlaceholder: 'example.com DNS' },
  { value: 'heartbeat', icon: '💓', label: 'Heartbeat', description: t('create_monitor.type_heartbeat_desc'), namePlaceholder: 'Nightly backup' },
])

const currentType = computed(() =>
  supportedTypes.value.find((t) => t.value === form.value.check_type) ?? null,
)

const form = ref({
  check_type: '',
  name: '',
  url: '',
  tcp_port: 443,
  heartbeat_slug: '',
  interval_seconds: 60,
  timeout_seconds: 10,
})

const alertChannels = ref([])
const selectedChannelIds = ref([])

onMounted(async () => {
  try {
    const { data } = await api.get('/alerts/channels')
    alertChannels.value = data
  } catch { /* ignore */ }
})

const canAdvance = computed(() => {
  if (step.value === 1) return !!form.value.check_type
  if (step.value === 2) {
    if (!form.value.name.trim()) return false
    if (form.value.check_type === 'tcp') return !!form.value.url && !!form.value.tcp_port
    if (form.value.check_type === 'heartbeat') return /^[a-z0-9-]+$/.test(form.value.heartbeat_slug)
    return !!form.value.url
  }
  return true
})

function goNext() {
  if (canAdvance.value) step.value++
}

async function submit() {
  loading.value = true
  error.value = ''
  const payload = {
    name: form.value.name.trim(),
    check_type: form.value.check_type,
    interval_seconds: form.value.interval_seconds,
    timeout_seconds: form.value.timeout_seconds,
  }
  if (form.value.check_type === 'tcp') {
    payload.url = form.value.url
    payload.tcp_port = form.value.tcp_port
  } else if (form.value.check_type === 'heartbeat') {
    payload.url = ''
    payload.heartbeat_slug = form.value.heartbeat_slug
  } else {
    payload.url = form.value.url
  }

  try {
    const created = await monitorStore.create(payload)
    // Wire selected channels via auto-alert helper if any.
    if (selectedChannelIds.value.length && created?.id) {
      try {
        await api.post(`/alerts/auto-rules/${created.id}`, null, {
          params: { channel_ids: selectedChannelIds.value },
        })
      } catch { /* non-fatal */ }
    }
    emit('created', created)
    emit('close')
  } catch (e) {
    error.value = e?.response?.data?.detail || t('common.error')
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.wizard__steps {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin-bottom: 1.25rem;
  border-bottom: 1px solid var(--border);
  padding-bottom: 0.75rem;
}
.wizard__step {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  font-size: 0.7rem;
  color: var(--text-3);
  flex: 1;
}
.wizard__step + .wizard__step::before {
  content: '';
  display: inline-block;
  width: 1rem;
  height: 1px;
  background: var(--border);
  margin-right: 0.4rem;
}
.wizard__step-num {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 1.4rem;
  height: 1.4rem;
  border-radius: 50%;
  background: var(--bg-surface-2);
  border: 1px solid var(--border);
  font-size: 0.7rem;
  font-weight: 600;
}
.wizard__step--current {
  color: var(--text-1);
}
.wizard__step--current .wizard__step-num {
  background: rgba(59, 130, 246, 0.18);
  border-color: rgba(96, 165, 250, 0.6);
  color: #93c5fd;
}
.wizard__step--done .wizard__step-num {
  background: rgba(16, 185, 129, 0.15);
  border-color: rgba(16, 185, 129, 0.4);
  color: #6ee7b7;
}

.wizard__body {
  max-height: min(72vh, 36rem);
  overflow-y: auto;
  padding-right: 0.25rem;
}

.wizard__type-card {
  text-align: left;
  padding: 0.75rem;
  border-radius: 0.5rem;
  border: 1px solid var(--border);
  background: transparent;
  color: var(--text-2);
  transition: border-color 0.15s, background 0.15s;
}
.wizard__type-card:hover { border-color: var(--text-3); }
.wizard__type-card--selected {
  border-color: rgba(96, 165, 250, 0.7);
  background: rgba(59, 130, 246, 0.10);
  color: var(--text-1);
}

@media (max-width: 640px) {
  .wizard__step-label { display: none; }
  .wizard__body { max-height: 60vh; }
}
</style>
