<template>
  <div class="page-body" v-if="group">
    <!-- Header -->
    <div class="flex items-center gap-4 mb-8">
      <nav class="breadcrumbs">
        <router-link to="/groups">{{ t('nav.groups') }}</router-link>
        <span class="breadcrumbs__sep">/</span>
        <span class="breadcrumbs__current">{{ group.name }}</span>
      </nav>
      <div class="flex-1">
        <h1 class="font-display text-2xl font-bold text-(--text-1)">{{ group.name }}</h1>
        <p v-if="group.description" class="text-(--text-2) text-sm mt-1">{{ group.description }}</p>
      </div>
      <a v-if="group.public_slug" :href="`/status/${group.public_slug}`" target="_blank"
        class="text-xs text-(--accent) hover:underline font-mono">
        /status/{{ group.public_slug }} ↗
      </a>
    </div>

    <!-- Stats -->
    <div class="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
      <div class="card text-center">
        <p class="text-xs text-(--text-3)">{{ t('monitors.title') }}</p>
        <p class="text-2xl font-bold mt-1 text-(--text-1)">{{ monitors.length }}</p>
      </div>
      <div class="card text-center">
        <p class="text-xs text-(--text-3)">UP</p>
        <p class="text-2xl font-bold mt-1 text-(--up)">{{ upCount }}</p>
      </div>
      <div class="card text-center">
        <p class="text-xs text-(--text-3)">{{ t('group_detail.down_alert') }}</p>
        <p class="text-2xl font-bold mt-1 text-(--down)">{{ downCount }}</p>
      </div>
      <div class="card text-center">
        <p class="text-xs text-(--text-3)">{{ t('group_detail.avg_uptime_24h') }}</p>
        <p class="text-2xl font-bold mt-1 text-(--accent)">{{ avgUptime !== null ? avgUptime.toFixed(1) + '%' : '—' }}</p>
      </div>
    </div>

    <!-- Status page customization -->
    <div v-if="group.public_slug" class="card mb-6">
      <h2 class="text-sm font-semibold text-(--text-2) mb-4">{{ t('groups.status_page_customization') }}</h2>
      <div class="space-y-4">
        <div>
          <label class="block text-xs text-(--text-2) mb-1">{{ t('groups.custom_logo_url') }}</label>
          <input v-model="customization.custom_logo_url" type="url" class="input w-full" placeholder="https://example.com/logo.png" />
        </div>
        <div>
          <label class="block text-xs text-(--text-2) mb-1">{{ t('groups.accent_color') }}</label>
          <div class="flex items-center gap-3">
            <input v-model="customization.accent_color" type="text" class="input flex-1" placeholder="#3B82F6" maxlength="7" />
            <input type="color" :value="customization.accent_color || '#3B82F6'" @input="customization.accent_color = $event.target.value" class="w-10 h-10 rounded cursor-pointer border border-(--border) bg-transparent" />
          </div>
        </div>
        <div>
          <label class="block text-xs text-(--text-2) mb-1">{{ t('groups.announcement_banner') }}</label>
          <textarea v-model="customization.announcement_banner" class="input w-full" rows="2" :placeholder="t('groups.announcement_banner_hint')"></textarea>
        </div>
        <div class="flex justify-end">
          <button @click="saveCustomization" :disabled="savingCustomization" class="btn-primary btn-sm">
            {{ savingCustomization ? t('common.loading') : t('common.save') }}
          </button>
        </div>
      </div>
    </div>

    <!-- SLA Reports -->
    <div class="card mb-6">
      <h2 class="text-sm font-semibold text-(--text-2) mb-4">{{ t('groups.sla_reports') }}</h2>
      <div class="space-y-4">
        <div>
          <label class="block text-xs text-(--text-2) mb-1">{{ t('groups.report_schedule') }}</label>
          <select v-model="reportConfig.report_schedule" class="input w-full">
            <option :value="null">{{ t('groups.report_schedule_none') }}</option>
            <option value="weekly">{{ t('groups.report_schedule_weekly') }}</option>
            <option value="monthly">{{ t('groups.report_schedule_monthly') }}</option>
          </select>
        </div>
        <div v-if="reportConfig.report_schedule">
          <label class="block text-xs text-(--text-2) mb-1">{{ t('groups.report_emails') }}</label>
          <input v-model="reportConfig.report_emails_raw" type="text" class="input w-full"
            :placeholder="t('groups.report_emails_hint')" />
          <p class="text-xs text-(--text-3) mt-1">{{ t('groups.report_emails_desc') }}</p>
        </div>
        <div class="flex justify-end">
          <button @click="saveReportConfig" :disabled="savingReport" class="btn-primary btn-sm">
            {{ savingReport ? t('common.loading') : t('common.save') }}
          </button>
        </div>
      </div>
    </div>

    <!-- Monitors list -->
    <div class="card mb-6">
      <div class="flex items-center justify-between mb-4">
        <h2 class="text-sm font-semibold text-(--text-2)">{{ t('group_detail.group_monitors') }}</h2>
        <button @click="showAddMonitor = true" class="btn-primary btn-sm">+ {{ t('group_detail.add_monitor') }}</button>
      </div>

      <div v-if="monitors.length === 0" class="text-center text-(--text-3) py-8 text-sm">
        {{ t('group_detail.no_monitors') }}
      </div>

      <div v-else class="overflow-x-auto">
      <table class="w-full text-sm min-w-[40rem]">
        <thead>
          <tr class="text-xs text-(--text-3) border-b border-(--border)">
            <th class="pb-2 text-left">{{ t('common.name') }}</th>
            <th class="pb-2 text-left">{{ t('incidents.type') }}</th>
            <th class="pb-2 text-left">{{ t('group_detail.url_host') }}</th>
            <th class="pb-2 text-left">{{ t('common.status') }}</th>
            <th class="pb-2 text-left">{{ t('monitors.uptime_24h') }}</th>
            <th class="pb-2"></th>
          </tr>
        </thead>
        <tbody class="divide-y divide-(--border)">
          <tr v-for="m in monitors" :key="m.id">
            <td class="py-2">
              <router-link :to="`/monitors/${m.id}`" class="font-medium text-(--text-1) hover:text-(--accent)">
                {{ m.name }}
              </router-link>
            </td>
            <td class="py-2">
              <span class="text-xs px-2 py-0.5 rounded-full bg-(--bg-surface-2) text-(--text-2) font-mono uppercase">
                {{ m.check_type }}
              </span>
            </td>
            <td class="py-2 text-(--text-2) text-xs font-mono truncate max-w-xs">
              {{ m.url?.replace(/^https?:\/\//, '') }}
            </td>
            <td class="py-2">
              <StatusBadge :status="m.last_status" :dot="false" />
            </td>
            <td class="py-2 text-(--text-2) text-xs">
              {{ m.uptime_24h != null ? m.uptime_24h.toFixed(1) + '%' : '—' }}
            </td>
            <td class="py-2 text-right">
              <button @click="removeFromGroup(m)" class="text-(--text-3) hover:text-(--down) text-xs transition-colors">
                {{ t('group_detail.remove') }}
              </button>
            </td>
          </tr>
        </tbody>
      </table>
      </div>
    </div>

    <!-- Error banner -->
    <div v-if="errorMsg" class="bg-[color-mix(in_srgb,var(--down)_15%,transparent)] border border-[color-mix(in_srgb,var(--down)_35%,transparent)] rounded p-3 text-sm text-(--down) mb-4">
      {{ errorMsg }}
    </div>

    <!-- Add monitor modal -->
    <BaseModal v-model="showAddMonitor" :title="t('group_detail.add_monitor_title')"
      :message="t('group_detail.select_monitor_hint')">
      <select v-model="selectedMonitorId" class="input w-full">
        <option value="">{{ t('group_detail.choose_monitor') }}</option>
        <option v-for="m in availableMonitors" :key="m.id" :value="m.id">
          {{ m.name }} ({{ m.check_type }})
        </option>
      </select>
      <template #footer>
        <button @click="showAddMonitor = false" class="flex-1 px-4 py-2 border border-(--border) text-(--text-2) rounded-lg hover:bg-(--bg-surface-2)">
          {{ t('common.cancel') }}
        </button>
        <button @click="addMonitor" :disabled="!selectedMonitorId" class="flex-1 btn-primary">
          {{ t('common.add') }}
        </button>
      </template>
    </BaseModal>
  </div>
  <div v-else class="p-8 text-(--text-2)">{{ t('common.loading') }}</div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { groupsApi, monitorsApi } from '../api/monitors'
import BaseModal from '../components/BaseModal.vue'
import StatusBadge from '../components/shared/StatusBadge.vue'

const { t } = useI18n()
const route = useRoute()
const group = ref(null)
const monitors = ref([])
const allMonitors = ref([])
const showAddMonitor = ref(false)
const selectedMonitorId = ref('')
const errorMsg = ref('')
const savingCustomization = ref(false)
const savingReport = ref(false)
const customization = reactive({
  custom_logo_url: '',
  accent_color: '',
  announcement_banner: '',
})
const reportConfig = reactive({
  report_schedule: null,
  report_emails_raw: '',
})

const upCount = computed(() => monitors.value.filter(m => m.last_status === 'up').length)
const downCount = computed(() => monitors.value.filter(m => m.last_status && m.last_status !== 'up').length)
const avgUptime = computed(() => {
  const vals = monitors.value.map(m => m.uptime_24h).filter(v => v != null)
  return vals.length ? vals.reduce((a, b) => a + b, 0) / vals.length : null
})

const availableMonitors = computed(() =>
  allMonitors.value.filter(m => !monitors.value.some(gm => gm.id === m.id))
)

function showError(msg) {
  errorMsg.value = msg
  setTimeout(() => { errorMsg.value = '' }, 5000)
}

async function load() {
  const id = route.params.id
  try {
    const [groupResp, monitorsResp] = await Promise.all([
      groupsApi.get(id),
      monitorsApi.list({ group_id: id }),  // list_monitors enrichit last_status + uptime_24h
    ])
    group.value = groupResp.data
    monitors.value = monitorsResp.data
    customization.custom_logo_url = group.value.custom_logo_url || ''
    customization.accent_color = group.value.accent_color || ''
    customization.announcement_banner = group.value.announcement_banner || ''
    reportConfig.report_schedule = group.value.report_schedule || null
    reportConfig.report_emails_raw = (group.value.report_emails || []).join(', ')
  } catch {
    showError(t('group_detail.error_load'))
  }
  try {
    const { data } = await monitorsApi.list()
    allMonitors.value = data
  } catch {}
}

async function saveCustomization() {
  savingCustomization.value = true
  try {
    await groupsApi.update(route.params.id, {
      custom_logo_url: customization.custom_logo_url || null,
      accent_color: customization.accent_color || null,
      announcement_banner: customization.announcement_banner || null,
    })
    group.value.custom_logo_url = customization.custom_logo_url || null
    group.value.accent_color = customization.accent_color || null
    group.value.announcement_banner = customization.announcement_banner || null
  } catch {
    showError(t('group_detail.error_save_customization'))
  } finally {
    savingCustomization.value = false
  }
}

async function saveReportConfig() {
  savingReport.value = true
  try {
    const emails = reportConfig.report_schedule && reportConfig.report_emails_raw.trim()
      ? reportConfig.report_emails_raw.split(',').map(e => e.trim()).filter(Boolean)
      : null
    await groupsApi.update(route.params.id, {
      report_schedule: reportConfig.report_schedule || null,
      report_emails: emails,
    })
    group.value.report_schedule = reportConfig.report_schedule || null
    group.value.report_emails = emails
  } catch {
    showError(t('group_detail.error_save_report'))
  } finally {
    savingReport.value = false
  }
}

async function removeFromGroup(monitor) {
  try {
    await monitorsApi.update(monitor.id, { group_id: null })
    monitors.value = monitors.value.filter(m => m.id !== monitor.id)
  } catch {
    showError(t('group_detail.error_remove'))
  }
}

async function addMonitor() {
  if (!selectedMonitorId.value) return
  try {
    await monitorsApi.update(selectedMonitorId.value, { group_id: route.params.id })
    showAddMonitor.value = false
    selectedMonitorId.value = ''
    await load()
  } catch {
    showError(t('group_detail.error_add'))
  }
}

onMounted(load)
</script>
