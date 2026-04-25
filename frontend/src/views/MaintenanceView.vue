<template>
  <div class="page-body">
    <!-- Header -->
    <div class="flex items-center justify-between mb-8">
      <div>
        <h1 class="text-2xl font-bold text-white">{{ t('maintenance.title') }}</h1>
        <p class="text-gray-400 mt-1">{{ t('maintenance.subtitle') }}</p>
      </div>
      <div class="flex items-center gap-2">
        <button
          @click="calendarView = !calendarView"
          class="btn-secondary text-xs flex items-center gap-1.5"
          :class="calendarView ? 'ring-1 ring-blue-500/60' : ''"
        >
          <CalendarDays :size="14" />
          {{ t('maintenance.calendar_view') }}
        </button>
        <button @click="openCreate()" class="btn-primary flex items-center gap-1.5">
          <Plus :size="14" />
          {{ t('maintenance.add') }}
        </button>
      </div>
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

    <template v-else>
      <!-- Empty state -->
      <EmptyState
        v-if="windows.length === 0 && !calendarView"
        :title="t('maintenance.no_windows')"
        :text="t('empty.maintenance_text')"
        :cta-label="t('maintenance.add')"
        doc-href="https://github.com/AurevLan/whatisup#maintenance"
        @cta="openCreate()"
      >
        <template #icon><CalendarClock :size="22" /></template>
      </EmptyState>

      <!-- Calendar view -->
      <div v-else-if="calendarView" class="card mb-6">
        <div class="flex items-center justify-between mb-4">
          <button @click="prevMonth" class="btn-ghost p-1"><ChevronLeft :size="16" /></button>
          <span class="font-semibold text-gray-200">{{ calendarTitle }}</span>
          <button @click="nextMonth" class="btn-ghost p-1"><ChevronRight :size="16" /></button>
        </div>

        <!-- Day-of-week headers -->
        <div class="grid grid-cols-7 gap-1 mb-1">
          <div
            v-for="d in weekDays" :key="d"
            class="text-center text-[10px] font-medium text-gray-500 py-1"
          >{{ d }}</div>
        </div>

        <!-- Calendar grid -->
        <div class="grid grid-cols-7 gap-1">
          <div
            v-for="(cell, i) in calendarCells" :key="i"
            class="min-h-[72px] rounded-lg p-1.5 text-xs"
            :class="cell.currentMonth
              ? 'bg-gray-800/40 border border-gray-800'
              : 'bg-transparent border border-transparent opacity-40'"
          >
            <div
              class="font-mono text-[10px] mb-1"
              :class="cell.isToday ? 'text-blue-400 font-bold' : 'text-gray-500'"
            >{{ cell.day }}</div>
            <div v-for="(w, wi) in cell.windows" :key="wi" class="mb-0.5">
              <span
                class="inline-block w-full truncate rounded px-1 py-0.5 text-[10px] leading-tight"
                :class="calendarWindowClass(w)"
                :title="w.name"
              >{{ w.name }}</span>
            </div>
          </div>
        </div>

        <!-- Legend -->
        <div class="flex items-center gap-4 mt-3 text-[11px] text-gray-500">
          <span class="flex items-center gap-1.5">
            <span class="w-2.5 h-2.5 rounded bg-amber-700/70" />
            {{ t('maintenance.status_active') }}
          </span>
          <span class="flex items-center gap-1.5">
            <span class="w-2.5 h-2.5 rounded bg-blue-800/70" />
            {{ t('maintenance.status_scheduled') }}
          </span>
          <span class="flex items-center gap-1.5">
            <span class="w-2.5 h-2.5 rounded bg-gray-700" />
            {{ t('maintenance.status_completed') }}
          </span>
        </div>
      </div>

      <!-- List view -->
      <div v-else class="space-y-3">
        <!-- Active -->
        <template v-if="activeWindows.length">
          <p class="text-xs font-semibold text-amber-400/80 uppercase tracking-wider mb-1 px-1">
            {{ t('maintenance.status_active') }}
          </p>
          <div
            v-for="(w, idx) in activeWindows" :key="w.id"
            class="card stagger-item border-l-2 border-amber-500/50"
            :style="{ animationDelay: idx * 40 + 'ms' }"
          >
            <MaintenanceWindowCard :w="w" :monitors="allMonitors" @delete="deleteWindow" @edit="openEdit" />
          </div>
        </template>

        <!-- Scheduled -->
        <template v-if="scheduledWindows.length">
          <p class="text-xs font-semibold text-blue-400/80 uppercase tracking-wider mt-4 mb-1 px-1">
            {{ t('maintenance.status_scheduled') }}
          </p>
          <div
            v-for="(w, idx) in scheduledWindows" :key="w.id"
            class="card stagger-item"
            :style="{ animationDelay: (activeWindows.length + idx) * 40 + 'ms' }"
          >
            <MaintenanceWindowCard :w="w" :monitors="allMonitors" @delete="deleteWindow" @edit="openEdit" />
          </div>
        </template>

        <!-- Completed -->
        <template v-if="completedWindows.length">
          <p class="text-xs font-semibold text-gray-500 uppercase tracking-wider mt-4 mb-1 px-1">
            {{ t('maintenance.status_completed') }}
          </p>
          <div
            v-for="(w, idx) in completedWindows" :key="w.id"
            class="card stagger-item opacity-60"
            :style="{ animationDelay: (activeWindows.length + scheduledWindows.length + idx) * 40 + 'ms' }"
          >
            <MaintenanceWindowCard :w="w" :monitors="allMonitors" @delete="deleteWindow" @edit="openEdit" />
          </div>
        </template>
      </div>
    </template>

    <!-- Create / Edit modal -->
    <BaseModal
      v-model="showCreate"
      :title="editingWindow ? t('maintenance.modal_edit_title') : t('maintenance.modal_title')"
      size="lg"
    >
      <div class="space-y-4">
        <!-- Name -->
        <div>
          <label class="text-sm text-gray-400">{{ t('common.name') }} <span class="text-red-400">*</span></label>
          <input
            v-model="form.name"
            class="input w-full mt-1"
            :placeholder="t('maintenance.name_placeholder')"
          />
        </div>

        <!-- Description -->
        <div>
          <label class="text-sm text-gray-400">
            {{ t('maintenance.description_label') }}
            <span class="text-gray-600">({{ t('common.optional') }})</span>
          </label>
          <textarea
            v-model="form.description"
            class="input w-full mt-1 resize-none"
            rows="2"
            :placeholder="t('maintenance.description_placeholder')"
          />
        </div>

        <!-- Start / End pickers -->
        <div class="grid grid-cols-2 gap-4">
          <div>
            <label class="text-sm text-gray-400">{{ t('maintenance.starts') }} <span class="text-red-400">*</span></label>
            <input v-model="form.starts_at" type="datetime-local" class="input w-full mt-1" />
          </div>
          <div>
            <label class="text-sm text-gray-400">{{ t('maintenance.ends') }} <span class="text-red-400">*</span></label>
            <input v-model="form.ends_at" type="datetime-local" class="input w-full mt-1" />
          </div>
        </div>

        <!-- Monitor selector -->
        <div>
          <label class="text-sm text-gray-400">
            {{ t('maintenance.monitor_label') }}
            <span class="text-gray-600">({{ t('common.optional') }})</span>
          </label>
          <div class="relative mt-1">
            <button
              type="button"
              @click="showMonitorDropdown = !showMonitorDropdown"
              class="input w-full text-left flex items-center justify-between cursor-pointer"
            >
              <span v-if="selectedMonitorObj" class="text-gray-200 truncate">{{ selectedMonitorObj.name }}</span>
              <span v-else class="text-gray-500">{{ t('maintenance.monitor_placeholder') }}</span>
              <ChevronDown :size="14" class="text-gray-500 shrink-0 ml-2" />
            </button>
            <!-- Invisible backdrop to close dropdown on outside click -->
            <div
              v-if="showMonitorDropdown"
              class="fixed inset-0 z-10"
              @click="showMonitorDropdown = false"
            />
            <div
              v-if="showMonitorDropdown"
              class="absolute z-20 mt-1 w-full bg-gray-800 border border-gray-700 rounded-lg shadow-xl max-h-52 overflow-y-auto"
            >
              <button
                type="button"
                @click="form.monitor_id = null; showMonitorDropdown = false"
                class="w-full text-left px-3 py-2 text-sm text-gray-400 hover:bg-gray-700"
              >
                — {{ t('maintenance.monitor_none') }}
              </button>
              <button
                v-for="m in allMonitors" :key="m.id"
                type="button"
                @click="form.monitor_id = m.id; showMonitorDropdown = false"
                class="w-full text-left px-3 py-2 text-sm flex items-center gap-2 hover:bg-gray-700"
                :class="form.monitor_id === m.id ? 'text-blue-400' : 'text-gray-300'"
              >
                <span
                  class="w-1.5 h-1.5 rounded-full shrink-0"
                  :class="m.last_status === 'up' ? 'bg-emerald-400' : m.last_status === 'down' ? 'bg-red-500' : 'bg-gray-500'"
                />
                <span class="truncate flex-1">{{ m.name }}</span>
                <span class="ml-auto text-xs text-gray-600 shrink-0 uppercase">{{ m.check_type }}</span>
              </button>
            </div>
          </div>
        </div>

        <!-- Suppress alerts toggle -->
        <div class="flex items-center gap-3 py-1">
          <button
            type="button"
            @click="form.suppress_alerts = !form.suppress_alerts"
            class="relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200"
            :class="form.suppress_alerts ? 'bg-blue-600' : 'bg-gray-700'"
          >
            <span
              class="inline-block h-4 w-4 rounded-full bg-white shadow transform transition-transform duration-200"
              :class="form.suppress_alerts ? 'translate-x-4' : 'translate-x-0'"
            />
          </button>
          <span
            class="text-sm text-gray-300 cursor-pointer select-none"
            @click="form.suppress_alerts = !form.suppress_alerts"
          >
            {{ t('maintenance.suppress_alerts_label') }}
          </span>
        </div>
      </div>

      <template #footer>
        <button @click="showCreate = false" class="btn-secondary flex-1">{{ t('common.cancel') }}</button>
        <button @click="submitWindow" :disabled="saving" class="btn-primary flex-1 disabled:opacity-50">
          {{ saving ? t('common.loading') : (editingWindow ? t('common.save') : t('common.add')) }}
        </button>
      </template>
    </BaseModal>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { CalendarClock, CalendarDays, Plus, ChevronLeft, ChevronRight, ChevronDown } from 'lucide-vue-next'
import BaseModal from '../components/BaseModal.vue'
import MaintenanceWindowCard from '../components/maintenance/MaintenanceWindowCard.vue'
import EmptyState from '../components/shared/EmptyState.vue'
import { maintenanceApi } from '../api/maintenance'
import { monitorsApi } from '../api/monitors'
import { useToast } from '../composables/useToast'
import { useConfirm } from '../composables/useConfirm'

// ── Composables ────────────────────────────────────────────────────────────
const { t } = useI18n()
const { success, error: toastError } = useToast()
const { confirm } = useConfirm()

// ── Props (for pre-filling from MonitorDetailView) ─────────────────────────
const props = defineProps({
  prefilledMonitorId: { type: String, default: null },
})

// ── State ──────────────────────────────────────────────────────────────────
const windows            = ref([])
const allMonitors        = ref([])
const loading            = ref(true)
const saving             = ref(false)
const errorMsg           = ref(null)
const showCreate         = ref(false)
const showMonitorDropdown = ref(false)
const calendarView       = ref(false)
const editingWindow      = ref(null)
const calendarDate       = ref(new Date())

const form = ref(defaultForm())

function defaultForm() {
  return {
    name:            '',
    description:     '',
    monitor_id:      null,
    group_id:        null,
    starts_at:       '',
    ends_at:         '',
    suppress_alerts: true,
  }
}

// ── Window status helpers ──────────────────────────────────────────────────
function windowStatus(w) {
  const now = new Date()
  if (new Date(w.starts_at) <= now && new Date(w.ends_at) >= now) return 'active'
  if (new Date(w.starts_at) > now) return 'scheduled'
  return 'completed'
}

function calendarWindowClass(w) {
  const s = windowStatus(w)
  return {
    active:    'bg-amber-700/60 text-amber-100',
    scheduled: 'bg-blue-800/60 text-blue-100',
    completed: 'bg-gray-700/60 text-gray-300',
  }[s]
}

// ── Sorted lists ───────────────────────────────────────────────────────────
const activeWindows = computed(() =>
  windows.value.filter(w => windowStatus(w) === 'active')
)
const scheduledWindows = computed(() =>
  windows.value
    .filter(w => windowStatus(w) === 'scheduled')
    .sort((a, b) => new Date(a.starts_at) - new Date(b.starts_at))
)
const completedWindows = computed(() =>
  windows.value
    .filter(w => windowStatus(w) === 'completed')
    .sort((a, b) => new Date(b.ends_at) - new Date(a.ends_at))
)

const selectedMonitorObj = computed(() =>
  form.value.monitor_id ? allMonitors.value.find(m => m.id === form.value.monitor_id) : null
)

// ── Calendar ───────────────────────────────────────────────────────────────
const weekDays = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

const calendarTitle = computed(() =>
  calendarDate.value.toLocaleDateString(undefined, { year: 'numeric', month: 'long' })
)

const calendarCells = computed(() => {
  const year  = calendarDate.value.getFullYear()
  const month = calendarDate.value.getMonth()
  const first = new Date(year, month, 1)
  // Monday-based offset (0=Mon … 6=Sun)
  const startOffset = (first.getDay() + 6) % 7
  const totalDays   = new Date(year, month + 1, 0).getDate()
  const today       = new Date()
  const cells       = []

  // Padding before
  for (let i = 0; i < startOffset; i++) {
    const d = new Date(year, month, 1 - startOffset + i)
    cells.push({ day: d.getDate(), currentMonth: false, isToday: false, windows: [] })
  }
  // Current month
  for (let d = 1; d <= totalDays; d++) {
    const cellDate = new Date(year, month, d)
    const isToday  = cellDate.toDateString() === today.toDateString()
    const dayStart = cellDate.getTime()
    const dayEnd   = new Date(year, month, d, 23, 59, 59).getTime()
    const wins     = windows.value.filter(w => {
      const ws = new Date(w.starts_at).getTime()
      const we = new Date(w.ends_at).getTime()
      return ws <= dayEnd && we >= dayStart
    })
    cells.push({ day: d, currentMonth: true, isToday, windows: wins })
  }
  // Padding after
  const remaining = (7 - (cells.length % 7)) % 7
  for (let i = 0; i < remaining; i++) {
    const d = new Date(year, month + 1, i + 1)
    cells.push({ day: d.getDate(), currentMonth: false, isToday: false, windows: [] })
  }
  return cells
})

function prevMonth() {
  const d = new Date(calendarDate.value)
  d.setMonth(d.getMonth() - 1)
  calendarDate.value = d
}
function nextMonth() {
  const d = new Date(calendarDate.value)
  d.setMonth(d.getMonth() + 1)
  calendarDate.value = d
}

// ── Data loading ───────────────────────────────────────────────────────────
function showError(msg) {
  errorMsg.value = msg
  setTimeout(() => { errorMsg.value = null }, 5000)
}

async function loadWindows() {
  try {
    const { data } = await maintenanceApi.list()
    windows.value = data
  } catch (err) {
    showError(t('common.error'))
    if (import.meta.env.DEV) console.error(err)
  } finally {
    loading.value = false
  }
}

async function loadMonitors() {
  try {
    const { data } = await monitorsApi.list()
    allMonitors.value = Array.isArray(data) ? data : (data.items ?? [])
  } catch (err) {
    if (import.meta.env.DEV) console.error(err)
  }
}

// ── CRUD ───────────────────────────────────────────────────────────────────
function toLocalDt(iso) {
  if (!iso) return ''
  const d   = new Date(iso)
  const pad = n => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`
}

function openCreate(prefillMonitorId = null) {
  editingWindow.value = null
  form.value = defaultForm()
  if (prefillMonitorId) form.value.monitor_id = prefillMonitorId
  showCreate.value = true
}

function openEdit(w) {
  editingWindow.value = w
  form.value = {
    name:            w.name,
    description:     w.description || '',
    monitor_id:      w.monitor_id || null,
    group_id:        w.group_id || null,
    starts_at:       toLocalDt(w.starts_at),
    ends_at:         toLocalDt(w.ends_at),
    suppress_alerts: w.suppress_alerts,
  }
  showCreate.value = true
}

async function submitWindow() {
  if (!form.value.name.trim() || !form.value.starts_at || !form.value.ends_at) {
    toastError(t('maintenance.error_required'))
    return
  }
  saving.value = true
  try {
    const payload = {
      name:            form.value.name.trim(),
      description:     form.value.description || null,
      monitor_id:      form.value.monitor_id || null,
      group_id:        form.value.group_id || null,
      starts_at:       new Date(form.value.starts_at).toISOString(),
      ends_at:         new Date(form.value.ends_at).toISOString(),
      suppress_alerts: form.value.suppress_alerts,
    }
    if (editingWindow.value) {
      const { data } = await maintenanceApi.update(editingWindow.value.id, payload)
      const idx = windows.value.findIndex(w => w.id === editingWindow.value.id)
      if (idx !== -1) windows.value[idx] = data
    } else {
      const { data } = await maintenanceApi.create(payload)
      windows.value.unshift(data)
    }
    showCreate.value = false
    success(t('common.success'))
  } catch (err) {
    toastError(t('common.error'))
    if (import.meta.env.DEV) console.error(err)
  } finally {
    saving.value = false
  }
}

async function deleteWindow(w) {
  const ok = await confirm({
    title:        t('maintenance.confirm_delete'),
    message:      t('maintenance.confirm_delete_detail'),
    confirmLabel: t('common.delete'),
  })
  if (!ok) return
  try {
    await maintenanceApi.remove(w.id)
    windows.value = windows.value.filter(x => x.id !== w.id)
    success(t('common.success'))
  } catch (err) {
    toastError(t('common.error'))
    if (import.meta.env.DEV) console.error(err)
  }
}

// ── Expose for external callers ────────────────────────────────────────────
defineExpose({ openCreate })

onMounted(async () => {
  await Promise.all([loadWindows(), loadMonitors()])
  if (props.prefilledMonitorId) openCreate(props.prefilledMonitorId)
})
</script>
