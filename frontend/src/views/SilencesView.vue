<template>
  <div class="page-body">
    <div class="flex items-start justify-between mb-6">
      <div>
        <h1 class="text-xl font-bold" style="color:var(--text-1)">{{ t('silences.title') }}</h1>
        <p class="mt-0.5 text-xs" style="color:var(--text-3)">{{ t('silences.subtitle') }}</p>
      </div>
      <button class="btn-primary" @click="openCreate">+ {{ t('silences.add') }}</button>
    </div>

    <div v-if="loading" class="card">
      <SkeletonRow v-for="i in 4" :key="i" />
    </div>

    <EmptyState
      v-else-if="silences.length === 0"
      :title="t('silences.empty_title')"
      :text="t('silences.empty_text')"
      :cta-label="t('silences.add')"
      @cta="openCreate"
    >
      <template #icon><BellOff :size="22" /></template>
    </EmptyState>

    <div v-else class="card p-0 overflow-hidden">
      <div v-for="s in silences" :key="s.id" class="silence-row">
        <div class="silence-row__main">
          <div class="silence-row__head">
            <span class="silence-row__name">{{ s.name }}</span>
            <span class="silence-row__badge" :class="badgeClass(s)">{{ badgeLabel(s) }}</span>
          </div>
          <p class="silence-row__meta">
            <FormattedDate :date="s.starts_at" /> → <FormattedDate :date="s.ends_at" />
            · {{ scopeLabel(s) }}
            <span v-if="s.reason" class="silence-row__reason">— {{ s.reason }}</span>
          </p>
        </div>
        <button @click="onDelete(s)" class="btn-ghost text-xs" :title="t('common.delete')">
          <Trash2 :size="14" />
        </button>
      </div>
    </div>

    <BaseModal v-if="showCreate" @close="showCreate = false" :title="t('silences.add')">
      <div class="space-y-3">
        <label class="block text-xs">
          <span class="text-gray-400">{{ t('common.name') }}</span>
          <input v-model="draft.name" class="input mt-1" :placeholder="t('silences.name_placeholder')" />
        </label>

        <label class="block text-xs">
          <span class="text-gray-400">{{ t('silences.scope_label') }}</span>
          <select v-model="draft.monitor_id" class="input mt-1">
            <option :value="null">{{ t('silences.scope_all') }}</option>
            <option v-for="m in monitors" :key="m.id" :value="m.id">{{ m.name }}</option>
          </select>
        </label>

        <div class="grid grid-cols-2 gap-3">
          <label class="block text-xs">
            <span class="text-gray-400">{{ t('silences.starts_at') }}</span>
            <input type="datetime-local" v-model="draft.starts_at" class="input mt-1" />
          </label>
          <label class="block text-xs">
            <span class="text-gray-400">{{ t('silences.ends_at') }}</span>
            <input type="datetime-local" v-model="draft.ends_at" class="input mt-1" />
          </label>
        </div>

        <div class="flex gap-1.5">
          <button v-for="p in presets" :key="p.label" type="button"
            class="btn-secondary text-xs"
            @click="applyPreset(p.minutes)">+{{ p.label }}</button>
        </div>

        <label class="block text-xs">
          <span class="text-gray-400">{{ t('silences.reason') }}</span>
          <input v-model="draft.reason" class="input mt-1" :placeholder="t('silences.reason_placeholder')" />
        </label>
      </div>
      <template #footer>
        <button @click="showCreate = false" class="btn-secondary flex-1">{{ t('common.cancel') }}</button>
        <button @click="save" :disabled="!canSave" class="btn-primary flex-1 disabled:opacity-50">
          {{ t('common.save') }}
        </button>
      </template>
    </BaseModal>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { BellOff, Trash2 } from 'lucide-vue-next'
import { silencesApi } from '../api/silences'
import { monitorsApi } from '../api/monitors'
import { useToast } from '../composables/useToast'
import { useConfirm } from '../composables/useConfirm'
import BaseModal from '../components/BaseModal.vue'
import EmptyState from '../components/shared/EmptyState.vue'
import SkeletonRow from '../components/shared/SkeletonRow.vue'
import FormattedDate from '../components/shared/FormattedDate.vue'

const { t } = useI18n()
const { success, error: toastError } = useToast()
const { confirm } = useConfirm()

const loading = ref(true)
const silences = ref([])
const monitors = ref([])
const showCreate = ref(false)

function emptyDraft() {
  const now = new Date()
  const endLocal = new Date(now.getTime() + 60 * 60 * 1000)
  return {
    name: '',
    monitor_id: null,
    starts_at: toLocalInput(now),
    ends_at: toLocalInput(endLocal),
    reason: '',
  }
}
const draft = ref(emptyDraft())

function toLocalInput(d) {
  const pad = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`
}

const presets = [
  { label: '15m', minutes: 15 },
  { label: '1h',  minutes: 60 },
  { label: '4h',  minutes: 240 },
  { label: '1d',  minutes: 1440 },
]

function applyPreset(minutes) {
  const start = new Date()
  const end = new Date(start.getTime() + minutes * 60 * 1000)
  draft.value.starts_at = toLocalInput(start)
  draft.value.ends_at = toLocalInput(end)
}

const canSave = computed(() =>
  draft.value.name.trim().length > 0 &&
  draft.value.starts_at &&
  draft.value.ends_at &&
  new Date(draft.value.ends_at) > new Date(draft.value.starts_at),
)

function isActive(s) {
  const now = Date.now()
  return new Date(s.starts_at).getTime() <= now && new Date(s.ends_at).getTime() > now
}
function isPast(s) {
  return new Date(s.ends_at).getTime() <= Date.now()
}
function badgeLabel(s) {
  if (isActive(s)) return t('silences.badge_active')
  if (isPast(s)) return t('silences.badge_past')
  return t('silences.badge_scheduled')
}
function badgeClass(s) {
  if (isActive(s)) return 'silence-row__badge--active'
  if (isPast(s)) return 'silence-row__badge--past'
  return 'silence-row__badge--scheduled'
}
function scopeLabel(s) {
  if (!s.monitor_id) return t('silences.scope_all')
  const m = monitors.value.find((mm) => mm.id === s.monitor_id)
  return m ? m.name : `monitor ${s.monitor_id.slice(0, 8)}…`
}

async function load() {
  loading.value = true
  try {
    const [s, m] = await Promise.all([silencesApi.list(), monitorsApi.list()])
    silences.value = s.data
    monitors.value = m.data
  } catch {
    toastError(t('common.error'))
  } finally {
    loading.value = false
  }
}

function openCreate() {
  draft.value = emptyDraft()
  showCreate.value = true
}

async function save() {
  try {
    const payload = {
      name: draft.value.name.trim(),
      monitor_id: draft.value.monitor_id || null,
      starts_at: new Date(draft.value.starts_at).toISOString(),
      ends_at: new Date(draft.value.ends_at).toISOString(),
      reason: draft.value.reason || null,
    }
    await silencesApi.create(payload)
    showCreate.value = false
    success(t('silences.create_success'))
    await load()
  } catch {
    toastError(t('common.error'))
  }
}

async function onDelete(s) {
  const ok = await confirm({
    title: t('silences.confirm_delete_title'),
    message: t('silences.confirm_delete_message', { name: s.name }),
    confirmLabel: t('common.delete'),
  })
  if (!ok) return
  try {
    await silencesApi.delete(s.id)
    success(t('silences.delete_success'))
    silences.value = silences.value.filter((x) => x.id !== s.id)
  } catch {
    toastError(t('common.error'))
  }
}

onMounted(load)
</script>

<style scoped>
.silence-row {
  display: flex;
  align-items: flex-start;
  gap: 0.75rem;
  padding: 0.85rem 1rem;
  border-bottom: 1px solid var(--border);
}
.silence-row:last-child { border-bottom: 0; }
.silence-row__main { flex: 1; min-width: 0; }
.silence-row__head { display: flex; align-items: center; gap: 0.5rem; }
.silence-row__name { font-weight: 600; color: var(--text-1); font-size: 0.85rem; }
.silence-row__badge {
  font-size: 0.62rem;
  font-weight: 700;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  padding: 0.1rem 0.45rem;
  border-radius: 0.375rem;
}
.silence-row__badge--active    { background: rgba(16, 185, 129, 0.18); color: #6ee7b7; }
.silence-row__badge--scheduled { background: rgba(96, 165, 250, 0.18); color: #93c5fd; }
.silence-row__badge--past      { background: rgba(148, 163, 184, 0.18); color: #cbd5e1; }
.silence-row__meta { font-size: 0.72rem; color: var(--text-3); margin-top: 0.2rem; }
.silence-row__reason { color: var(--text-2); }
</style>
