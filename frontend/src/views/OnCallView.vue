<template>
  <div class="page-body">
    <div class="flex items-start justify-between mb-6 flex-wrap gap-2">
      <div>
        <h1 class="font-display text-xl font-bold" style="color:var(--text-1)">{{ t('oncall.title') }}</h1>
        <p class="mt-0.5 text-xs" style="color:var(--text-3)">{{ t('oncall.subtitle') }}</p>
      </div>
      <div class="flex gap-2 flex-wrap">
        <button class="btn-secondary" @click="openPolicy()">+ {{ t('oncall.add_policy') }}</button>
        <button class="btn-primary" @click="openSchedule()">+ {{ t('oncall.add_schedule') }}</button>
      </div>
    </div>

    <!-- Who is on duty, right now. First thing on the page because it is the
         one question this feature exists to answer. -->
    <div v-if="!loading && onCallNow.length" class="card mb-6">
      <h2 class="text-sm font-semibold text-(--text-2) mb-3">{{ t('oncall.now_title') }}</h2>
      <div class="oncall-now">
        <div v-for="entry in onCallNow" :key="entry.schedule_id" class="oncall-now__item">
          <span class="oncall-now__schedule">{{ entry.schedule_name }}</span>
          <span v-if="entry.user_id" class="oncall-now__person">
            {{ entry.username || entry.user_email }}
            <span v-if="entry.via_override" class="oncall-now__override" :title="t('oncall.via_override_help')">
              {{ t('oncall.via_override') }}
            </span>
          </span>
          <!-- Never a blank cell: an uncovered rotation must not read like a
               covered one. -->
          <span v-else class="oncall-now__nobody">{{ t('oncall.nobody') }}</span>
        </div>
      </div>
    </div>

    <div v-if="loading" class="card"><SkeletonRow v-for="i in 4" :key="i" /></div>

    <template v-else>
      <!-- Schedules -->
      <h2 class="text-sm font-semibold text-(--text-2) mb-2">{{ t('oncall.schedules') }}</h2>
      <EmptyState
        v-if="!schedules.length"
        :title="t('oncall.empty_schedules_title')"
        :text="t('oncall.empty_schedules_text')"
        :cta-label="t('oncall.add_schedule')"
        inline
        @cta="openSchedule()"
      >
        <template #icon><CalendarClock :size="22" /></template>
      </EmptyState>
      <div v-else class="card p-0 overflow-hidden mb-6">
        <div v-for="s in schedules" :key="s.id" class="oncall-row">
          <div class="oncall-row__main">
            <div class="oncall-row__head">
              <span class="oncall-row__name">{{ s.name }}</span>
              <span v-if="!s.enabled" class="badge-unknown text-xs">{{ t('oncall.disabled') }}</span>
            </div>
            <p class="oncall-row__meta">
              {{ rotationLabel(s) }} · {{ t('oncall.handoff_at', { time: s.handoff_time }) }}
              ({{ s.timezone }}) · {{ t('oncall.n_participants', { n: s.participants?.length ?? 0 }) }}
            </p>
          </div>
          <div class="flex items-center gap-1">
            <button class="btn-ghost btn-sm" @click="openSchedule(s)">{{ t('common.edit') }}</button>
            <button class="btn-icon" :title="t('common.delete')" :aria-label="t('common.delete')"
              @click="removeSchedule(s)"><Trash2 :size="14" /></button>
          </div>
        </div>
      </div>

      <!-- Escalation policies -->
      <h2 class="text-sm font-semibold text-(--text-2) mb-2">{{ t('oncall.policies') }}</h2>
      <EmptyState
        v-if="!policies.length"
        :title="t('oncall.empty_policies_title')"
        :text="t('oncall.empty_policies_text')"
        :cta-label="t('oncall.add_policy')"
        inline
        @cta="openPolicy()"
      >
        <template #icon><ChevronsUp :size="22" /></template>
      </EmptyState>
      <div v-else class="card p-0 overflow-hidden">
        <div v-for="p in policies" :key="p.id" class="oncall-row">
          <div class="oncall-row__main">
            <div class="oncall-row__head">
              <span class="oncall-row__name">{{ p.name }}</span>
              <span v-if="!p.enabled" class="badge-unknown text-xs">{{ t('oncall.disabled') }}</span>
            </div>
            <p class="oncall-row__meta">{{ ladderLabel(p) }}</p>
          </div>
          <div class="flex items-center gap-1">
            <button class="btn-ghost btn-sm" @click="openPolicy(p)">{{ t('common.edit') }}</button>
            <button class="btn-icon" :title="t('common.delete')" :aria-label="t('common.delete')"
              @click="removePolicy(p)"><Trash2 :size="14" /></button>
          </div>
        </div>
      </div>
    </template>

    <OnCallScheduleModal
      v-if="showSchedule"
      :schedule="editingSchedule"
      @close="showSchedule = false"
      @saved="onSaved"
    />
    <EscalationPolicyModal
      v-if="showPolicy"
      :policy="editingPolicy"
      :schedules="schedules"
      @close="showPolicy = false"
      @saved="onSaved"
    />
  </div>
</template>

<script setup>
// Plan V2, B-4 — the configuration surface for on-call.
//
// The engine has been walking ladders since B-1/B-2, but rotations and policies
// could only be created by calling the API by hand, which in practice meant
// nobody could use it. This page is what makes the feature reachable.
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { CalendarClock, ChevronsUp, Trash2 } from 'lucide-vue-next'
import { oncallApi } from '../api/oncall'
import { useToast } from '../composables/useToast'
import { useConfirm } from '../composables/useConfirm'
import EmptyState from '../components/shared/EmptyState.vue'
import SkeletonRow from '../components/shared/SkeletonRow.vue'
import OnCallScheduleModal from '../components/oncall/OnCallScheduleModal.vue'
import EscalationPolicyModal from '../components/oncall/EscalationPolicyModal.vue'

const { t } = useI18n()
const { success, error: toastError } = useToast()
const { confirm } = useConfirm()

const loading = ref(true)
const schedules = ref([])
const policies = ref([])
const onCallNow = ref([])

const showSchedule = ref(false)
const showPolicy = ref(false)
const editingSchedule = ref(null)
const editingPolicy = ref(null)

const scheduleNames = computed(() =>
  Object.fromEntries(schedules.value.map((s) => [s.id, s.name])),
)

function rotationLabel(s) {
  if (s.rotation_type === 'daily') return t('oncall.rotation_daily')
  if (s.rotation_type === 'weekly') return t('oncall.rotation_weekly')
  return t('oncall.rotation_custom', { n: s.rotation_length_days })
}

function ladderLabel(p) {
  const levels = p.levels ?? []
  if (!levels.length) {
    // Said out loud: a policy with no rungs escalates nothing, and the server
    // falls back to the rule's channels rather than staying silent.
    return t('oncall.no_levels')
  }
  return levels
    .map((l) => {
      const target =
        l.target_type === 'schedule'
          ? scheduleNames.value[l.target_schedule_id] || t('oncall.target_schedule')
          : t(`oncall.target_${l.target_type}`)
      return l.delay_minutes ? `+${l.delay_minutes}min → ${target}` : target
    })
    .join(' · ')
}

async function load() {
  loading.value = true
  try {
    const [sch, pol, now] = await Promise.all([
      oncallApi.schedules.list(),
      oncallApi.policies.list(),
      oncallApi.onCallNow({ skipErrorToast: true }).catch(() => ({ data: [] })),
    ])
    schedules.value = sch.data
    policies.value = pol.data
    onCallNow.value = now.data
  } finally {
    loading.value = false
  }
}

function openSchedule(schedule = null) {
  editingSchedule.value = schedule
  showSchedule.value = true
}
function openPolicy(policy = null) {
  editingPolicy.value = policy
  showPolicy.value = true
}

async function onSaved() {
  showSchedule.value = false
  showPolicy.value = false
  await load()
}

async function removeSchedule(s) {
  if (!(await confirm({ title: t('oncall.delete_schedule'), message: s.name }))) return
  try {
    await oncallApi.schedules.remove(s.id)
    success(t('oncall.schedule_deleted'))
    await load()
  } catch (e) {
    toastError(e.response?.data?.detail || t('common.error'))
  }
}

async function removePolicy(p) {
  if (!(await confirm({ title: t('oncall.delete_policy'), message: p.name }))) return
  try {
    await oncallApi.policies.remove(p.id)
    success(t('oncall.policy_deleted'))
    await load()
  } catch (e) {
    toastError(e.response?.data?.detail || t('common.error'))
  }
}

onMounted(load)
</script>

<style scoped>
.oncall-now {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  gap: 0.5rem;
}
.oncall-now__item {
  display: flex;
  flex-direction: column;
  gap: 0.15rem;
  padding: 0.5rem 0.75rem;
  border: 1px solid var(--border);
  border-radius: 0.5rem;
  background: var(--bg-surface-2);
}
.oncall-now__schedule {
  font-size: 0.7rem;
  color: var(--text-3);
}
.oncall-now__person {
  font-size: 0.85rem;
  color: var(--text-1);
  font-weight: 500;
}
.oncall-now__override {
  font-size: 0.65rem;
  color: var(--warn);
  margin-left: 0.35rem;
}
.oncall-now__nobody {
  font-size: 0.85rem;
  color: var(--down);
  font-weight: 500;
}
.oncall-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  padding: 0.7rem 0.9rem;
  border-bottom: 1px solid var(--border);
}
.oncall-row:last-child {
  border-bottom: 0;
}
.oncall-row__main {
  min-width: 0;
}
.oncall-row__head {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}
.oncall-row__name {
  color: var(--text-1);
  font-weight: 500;
}
.oncall-row__meta {
  margin-top: 0.15rem;
  font-size: 0.72rem;
  color: var(--text-3);
}
@media (max-width: 640px) {
  .oncall-row {
    flex-wrap: wrap;
  }
}
</style>
