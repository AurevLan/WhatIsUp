<template>
  <div class="incidents">

    <div class="incidents__header">
      <div>
        <h1 class="incidents__title">{{ t('incidents.title') }}</h1>
        <p class="incidents__sub">{{ t('incidents.subtitle') }}</p>
      </div>
    </div>

    <!-- Filters -->
    <div class="incidents__filters">
      <div class="filter-group">
        <button
          v-for="opt in statusOpts"
          :key="opt.value"
          class="filter-btn"
          :class="{ 'filter-btn--active': statusFilter === opt.value }"
          @click="statusFilter = opt.value"
        >{{ opt.label }}</button>
      </div>
      <div class="filter-group">
        <button
          v-for="opt in dayOpts"
          :key="opt.value"
          class="filter-btn"
          :class="{ 'filter-btn--active': daysFilter === opt.value }"
          @click="daysFilter = opt.value"
        >{{ opt.label }}</button>
      </div>
    </div>

    <!-- List -->
    <div class="card p-0 overflow-hidden">
      <div v-if="loading" class="incidents__empty">
        <div v-for="i in 8" :key="i" class="skeleton h-14 mb-2" />
      </div>

      <div v-else-if="incidents.length === 0" class="incidents__empty">
        <AlertCircle :size="28" class="incidents__empty-icon" />
        <p>{{ t('incidents.no_incidents') }}</p>
      </div>

      <div v-else>
        <!-- Table header -->
        <div class="inc-row inc-row--head">
          <span class="inc-col inc-col--status">{{ t('common.status') }}</span>
          <span class="inc-col inc-col--monitor">{{ t('incidents.monitor') }}</span>
          <span class="inc-col inc-col--type">{{ t('incidents.type') }}</span>
          <span class="inc-col inc-col--started">{{ t('incidents.started') }}</span>
          <span class="inc-col inc-col--duration">{{ t('incidents.duration') }}</span>
        </div>

        <router-link
          v-for="inc in incidents"
          :key="inc.id"
          :to="`/monitors/${inc.monitor_id}`"
          class="inc-row inc-row--data"
        >
          <span class="inc-col inc-col--status">
            <span class="inc-badge" :class="inc.is_resolved ? 'inc-badge--resolved' : 'inc-badge--open'">
              {{ inc.is_resolved ? t('incidents.resolved') : t('incidents.ongoing') }}
            </span>
          </span>
          <span class="inc-col inc-col--monitor">{{ inc.monitor_name }}</span>
          <span class="inc-col inc-col--type">{{ inc.monitor_check_type }}</span>
          <span class="inc-col inc-col--started">{{ formatDate(inc.started_at) }}</span>
          <span class="inc-col inc-col--duration">{{ formatDuration(inc) }}</span>
        </router-link>
      </div>
    </div>

  </div>
</template>

<script setup>
import { computed, ref, watch, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { AlertCircle } from 'lucide-vue-next'
import api from '../api/client'

const { t, locale } = useI18n()

const loading = ref(false)
const incidents = ref([])
const statusFilter = ref('all')
const daysFilter = ref(30)

const statusOpts = computed(() => [
  { value: 'all',      label: t('incidents.filter_all') },
  { value: 'open',     label: t('incidents.filter_open') },
  { value: 'resolved', label: t('incidents.filter_resolved') },
])

const dayOpts = computed(() => [
  { value: 7,  label: t('incidents.last_7d') },
  { value: 30, label: t('incidents.last_30d') },
  { value: 90, label: t('incidents.last_90d') },
])

async function load() {
  loading.value = true
  try {
    const params = { days: daysFilter.value, limit: 500 }
    if (statusFilter.value === 'open')     params.resolved = 'false'
    if (statusFilter.value === 'resolved') params.resolved = 'true'
    const { data } = await api.get('/incidents/', { params })
    incidents.value = data
  } catch {
    incidents.value = []
  } finally {
    loading.value = false
  }
}

watch([statusFilter, daysFilter], load)
onMounted(load)

function formatDate(iso) {
  if (!iso) return '—'
  return new Date(iso).toLocaleString(locale.value, {
    month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
  })
}

function formatDuration(inc) {
  if (!inc.is_resolved) return '—'
  const secs = inc.duration_seconds
  if (secs == null) return '—'
  if (secs < 60) return `${secs}s`
  if (secs < 3600) return `${Math.round(secs / 60)}m`
  const h = Math.floor(secs / 3600)
  const m = Math.round((secs % 3600) / 60)
  return m > 0 ? `${h}h ${m}m` : `${h}h`
}
</script>

<style scoped>
.incidents {
  padding: 1.25rem 1rem 2rem;
  max-width: 64rem;
  margin: 0 auto;
}
@media (min-width: 640px)  { .incidents { padding: 1.5rem 1.5rem 2rem; } }
@media (min-width: 1024px) { .incidents { padding: 2rem 2rem 2.5rem; } }

.incidents__header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  margin-bottom: 1.25rem;
}
.incidents__title {
  font-size: 1.375rem;
  font-weight: 700;
  color: var(--text-1);
  letter-spacing: -.02em;
  line-height: 1.2;
}
.incidents__sub {
  font-size: .8125rem;
  color: var(--text-3);
  margin-top: .25rem;
}

.incidents__filters {
  display: flex;
  flex-wrap: wrap;
  gap: .5rem;
  margin-bottom: 1rem;
  align-items: center;
  justify-content: space-between;
}

.filter-group {
  display: flex;
  gap: 4px;
}

.filter-btn {
  padding: 4px 12px;
  border-radius: 6px;
  font-size: .75rem;
  font-weight: 500;
  border: 1px solid var(--border);
  background: none;
  color: var(--text-3);
  cursor: pointer;
  transition: all .15s;
  font-family: inherit;
}
.filter-btn:hover { border-color: var(--border-hover); color: var(--text-2); }
.filter-btn--active {
  background: var(--bg-surface-2);
  border-color: var(--border-hover);
  color: var(--text-1);
}

/* Table */
.inc-row {
  display: grid;
  grid-template-columns: 90px 1fr 80px 150px 80px;
  gap: .75rem;
  align-items: center;
  padding: .625rem 1.125rem;
}
@media (max-width: 640px) {
  .inc-row { grid-template-columns: 80px 1fr 100px; }
  .inc-col--type, .inc-col--started { display: none; }
}

.inc-row--head {
  border-bottom: 1px solid var(--border);
  background: var(--bg-surface-2);
}
.inc-row--head .inc-col {
  font-size: .65rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: .06em;
  color: var(--text-3);
}

.inc-row--data {
  border-bottom: 1px solid var(--border);
  text-decoration: none;
  transition: background .15s;
}
.inc-row--data:last-child { border-bottom: none; }
.inc-row--data:hover { background: rgba(255,255,255,.025); }

.inc-col { font-size: .8125rem; color: var(--text-2); }
.inc-col--monitor { font-weight: 500; color: var(--text-1); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.inc-col--type {
  font-size: .6875rem;
  font-family: "JetBrains Mono", monospace;
  color: var(--text-3);
}
.inc-col--duration { font-family: "JetBrains Mono", monospace; font-size: .75rem; }

.inc-badge {
  display: inline-block;
  font-size: .65rem;
  font-weight: 700;
  padding: 2px 8px;
  border-radius: 99px;
  text-transform: uppercase;
  letter-spacing: .04em;
  white-space: nowrap;
}
.inc-badge--open {
  background: rgba(248,113,113,.12);
  color: #f87171;
  border: 1px solid rgba(248,113,113,.25);
}
.inc-badge--resolved {
  background: rgba(52,211,153,.1);
  color: #34d399;
  border: 1px solid rgba(52,211,153,.2);
}

.incidents__empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 3rem 1.5rem;
  gap: .75rem;
  color: var(--text-3);
  font-size: .875rem;
}
.incidents__empty-icon { color: var(--text-3); opacity: .6; }
</style>
