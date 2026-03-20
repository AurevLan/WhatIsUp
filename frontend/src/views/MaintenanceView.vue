<template>
  <div class="p-8">
    <div class="flex items-center justify-between mb-8">
      <div>
        <h1 class="text-2xl font-bold text-white">{{ t('maintenance.title') }}</h1>
        <p class="text-gray-400 mt-1">Schedule downtime windows to suppress alerts</p>
      </div>
      <button @click="showCreate = true" class="btn-primary">+ {{ t('maintenance.add') }}</button>
    </div>

    <!-- Error banner -->
    <div v-if="errorMsg" class="mb-4 px-4 py-3 rounded-lg bg-red-900/50 border border-red-700 text-red-300 text-sm">
      {{ errorMsg }}
    </div>

    <!-- List -->
    <div class="space-y-3">
      <div v-for="w in windows" :key="w.id" class="card">
        <div class="flex items-start justify-between">
          <div>
            <div class="flex items-center gap-2">
              <span class="w-2 h-2 rounded-full" :class="isActive(w) ? 'bg-amber-400' : 'bg-gray-600'"></span>
              <h3 class="font-semibold text-white">{{ w.name }}</h3>
              <span v-if="isActive(w)" class="text-xs px-2 py-0.5 rounded-full bg-amber-900/50 text-amber-400">{{ t('maintenance.active') }}</span>
            </div>
            <p v-if="w.description" class="text-sm text-gray-400 mt-1">{{ w.description }}</p>
            <div class="mt-2 text-xs text-gray-500 space-y-0.5">
              <div>{{ t('maintenance.starts') }}: {{ formatDt(w.starts_at) }}</div>
              <div>{{ t('maintenance.ends') }}: {{ formatDt(w.ends_at) }}</div>
              <div>Alerts suppressed: {{ w.suppress_alerts ? t('common.yes') : t('common.no') }}</div>
            </div>
          </div>
          <button @click="deleteWindow(w)" class="text-xs text-red-400 hover:text-red-300">{{ t('common.delete') }}</button>
        </div>
      </div>
      <div v-if="windows.length === 0" class="text-center text-gray-500 py-16">
        {{ t('maintenance.no_windows') }}
      </div>
    </div>

    <!-- Create modal -->
    <div v-if="showCreate" class="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4">
      <div class="bg-gray-900 border border-gray-700 rounded-2xl w-full max-w-md p-6">
        <h2 class="text-lg font-semibold text-white mb-4">New maintenance window</h2>
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
            <label for="suppress" class="text-sm text-gray-300">Suppress alerts during window</label>
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
import api from '../api/client'
import { useToast } from '../composables/useToast'
import { useConfirm } from '../composables/useConfirm'

const { t } = useI18n()
const { success, error: toastError } = useToast()
const { confirm } = useConfirm()

const windows = ref([])
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
  return new Date(dt).toLocaleString('fr-FR')
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
    showError('Failed to load maintenance windows.')
    console.error(err)
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
    success(`Fenêtre "${data.name}" créée`)
  } catch (err) {
    toastError('Erreur lors de la création')
    console.error(err)
  }
}

async function deleteWindow(w) {
  const ok = await confirm({
    title: `Supprimer "${w.name}" ?`,
    message: 'Cette fenêtre de maintenance sera définitivement supprimée.',
    confirmLabel: 'Supprimer',
  })
  if (!ok) return
  try {
    await api.delete(`/maintenance/${w.id}`)
    windows.value = windows.value.filter(x => x.id !== w.id)
    success(`Fenêtre "${w.name}" supprimée`)
  } catch (err) {
    toastError('Erreur lors de la suppression')
    console.error(err)
  }
}

onMounted(loadWindows)
</script>
