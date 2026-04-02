<template>
  <div class="page-body">
    <div class="flex items-center justify-between mb-8">
      <div>
        <h1 class="text-2xl font-bold text-white">{{ t('maintenance.title') }}</h1>
        <p class="text-gray-400 mt-1">{{ t('maintenance.subtitle') }}</p>
      </div>
      <button @click="showCreate = true" class="btn-primary">+ {{ t('maintenance.add') }}</button>
    </div>

    <!-- Error banner -->
    <div v-if="errorMsg" class="mb-4 px-4 py-3 rounded-lg bg-red-900/50 border border-red-700 text-red-300 text-sm">
      {{ errorMsg }}
    </div>

    <!-- Loading skeleton -->
    <div v-if="loading" class="space-y-3">
      <div v-for="i in 3" :key="i" class="card">
        <div class="flex items-start justify-between">
          <div class="flex-1 space-y-2">
            <div class="skeleton-line w-1/3" />
            <div class="skeleton-line w-2/3" style="height:.5rem" />
            <div class="skeleton-line w-1/2" style="height:.5rem" />
          </div>
          <div class="skeleton-line w-16" style="height:1.5rem;border-radius:99px" />
        </div>
      </div>
    </div>

    <!-- Empty state -->
    <div v-else-if="windows.length === 0" class="empty-state">
      <div class="empty-state__icon"><CalendarClock :size="22" /></div>
      <p class="empty-state__title">{{ t('maintenance.no_windows') }}</p>
      <p class="empty-state__text">{{ t('maintenance.empty_desc') }}</p>
      <button @click="showCreate = true" class="btn-primary mt-2">+ {{ t('maintenance.add') }}</button>
    </div>

    <!-- List -->
    <div v-else class="space-y-3">
      <div v-for="(w, idx) in windows" :key="w.id"
        class="card stagger-item"
        :style="{ animationDelay: idx * 40 + 'ms' }">
        <div class="flex items-start justify-between">
          <div>
            <div class="flex items-center gap-2">
              <span class="w-2 h-2 rounded-full" :class="isActive(w) ? 'bg-amber-400' : 'bg-gray-600'"></span>
              <h3 class="font-semibold" style="color:var(--text-1)">{{ w.name }}</h3>
              <span v-if="isActive(w)" class="text-xs px-2 py-0.5 rounded-full bg-amber-900/50 text-amber-400">{{ t('maintenance.active') }}</span>
            </div>
            <p v-if="w.description" class="text-sm mt-1" style="color:var(--text-3)">{{ w.description }}</p>
            <div class="mt-2 text-xs space-y-0.5" style="color:var(--text-3)">
              <div>{{ t('maintenance.starts') }}: {{ formatDt(w.starts_at) }}</div>
              <div>{{ t('maintenance.ends') }}: {{ formatDt(w.ends_at) }}</div>
              <div>{{ t('maintenance.alerts_suppressed') }}: {{ w.suppress_alerts ? t('common.yes') : t('common.no') }}</div>
            </div>
          </div>
          <button @click="deleteWindow(w)" class="btn-ghost px-2 py-1 text-xs" style="color:var(--down)">
            <Trash2 :size="14" />
          </button>
        </div>
      </div>
    </div>

    <!-- Create modal -->
    <div v-if="showCreate" class="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4">
      <div class="bg-gray-900 border border-gray-700 rounded-2xl w-full max-w-md p-6">
        <h2 class="text-lg font-semibold text-white mb-4">{{ t('maintenance.modal_title') }}</h2>
        <div class="space-y-4">
          <div>
            <label class="text-sm text-gray-400">{{ t('common.name') }}</label>
            <input v-model="form.name" class="input w-full mt-1" placeholder="e.g. Weekly deployment" />
          </div>
          <div>
            <label class="text-sm text-gray-400">Description ({{ t('common.optional') }})</label>
            <input v-model="form.description" class="input w-full mt-1" />
          </div>
          <div>
            <label class="text-sm text-gray-400">Monitor ID ({{ t('common.optional') }})</label>
            <input v-model="form.monitor_id" class="input w-full mt-1" placeholder="UUID of monitor" />
          </div>
          <div>
            <label class="text-sm text-gray-400">{{ t('maintenance.starts') }}</label>
            <input v-model="form.starts_at" type="datetime-local" class="input w-full mt-1" />
          </div>
          <div>
            <label class="text-sm text-gray-400">{{ t('maintenance.ends') }}</label>
            <input v-model="form.ends_at" type="datetime-local" class="input w-full mt-1" />
          </div>
          <div class="flex items-center gap-2">
            <input v-model="form.suppress_alerts" type="checkbox" id="suppress" />
            <label for="suppress" class="text-sm text-gray-300">{{ t('maintenance.suppress_alerts_label') }}</label>
          </div>
        </div>
        <div class="flex gap-3 mt-6">
          <button @click="showCreate = false" class="btn-secondary flex-1">{{ t('common.cancel') }}</button>
          <button @click="createWindow" class="btn-primary flex-1">{{ t('common.add') }}</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { CalendarClock, Trash2 } from 'lucide-vue-next'
import api from '../api/client'
import { useToast } from '../composables/useToast'
import { useConfirm } from '../composables/useConfirm'

const { t } = useI18n()
const { success, error: toastError } = useToast()
const { confirm } = useConfirm()

const windows = ref([])
const loading = ref(true)
const showCreate = ref(false)
const errorMsg = ref(null)

const form = ref({
  name: '',
  description: '',
  monitor_id: '',
  group_id: null,
  starts_at: '',
  ends_at: '',
  suppress_alerts: true,
})

function isActive(w) {
  const now = new Date()
  return new Date(w.starts_at) <= now && new Date(w.ends_at) >= now
}

function formatDt(dt) {
  return new Date(dt).toLocaleString()
}

function showError(msg) {
  errorMsg.value = msg
  setTimeout(() => { errorMsg.value = null }, 5000)
}

async function loadWindows() {
  try {
    const { data } = await api.get('/maintenance/')
    windows.value = data
  } catch (err) {
    showError(t('common.error'))
    if (import.meta.env.DEV) console.error(err)
  } finally {
    loading.value = false
  }
}

async function createWindow() {
  try {
    const payload = {
      name: form.value.name,
      description: form.value.description || null,
      monitor_id: form.value.monitor_id || null,
      group_id: form.value.group_id,
      starts_at: new Date(form.value.starts_at).toISOString(),
      ends_at: new Date(form.value.ends_at).toISOString(),
      suppress_alerts: form.value.suppress_alerts,
    }
    const { data } = await api.post('/maintenance/', payload)
    windows.value.unshift(data)
    showCreate.value = false
    success(t('common.success'))
  } catch (err) {
    toastError(t('common.error'))
    if (import.meta.env.DEV) console.error(err)
  }
}

async function deleteWindow(w) {
  const ok = await confirm({
    title: t('maintenance.confirm_delete'),
    message: t('maintenance.confirm_delete_detail'),
    confirmLabel: t('common.delete'),
  })
  if (!ok) return
  try {
    await api.delete(`/maintenance/${w.id}`)
    windows.value = windows.value.filter(x => x.id !== w.id)
    success(t('common.success'))
  } catch (err) {
    toastError(t('common.error'))
    if (import.meta.env.DEV) console.error(err)
  }
}

onMounted(loadWindows)
</script>
