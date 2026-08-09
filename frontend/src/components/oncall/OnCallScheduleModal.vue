<template>
  <BaseModal :model-value="true" size="lg" :title="schedule ? t('oncall.edit_schedule') : t('oncall.add_schedule')"
    @close="$emit('close')" @update:model-value="$emit('close')">
    <form class="space-y-4" @submit.prevent="save">
      <div>
        <label class="block text-sm font-medium text-(--text-2) mb-1">{{ t('common.name') }} *</label>
        <input v-model.trim="form.name" class="input w-full" required maxlength="200" />
      </div>

      <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <div>
          <label class="block text-sm font-medium text-(--text-2) mb-1">{{ t('oncall.rotation') }}</label>
          <select v-model="form.rotation_type" class="input w-full">
            <option value="daily">{{ t('oncall.rotation_daily') }}</option>
            <option value="weekly">{{ t('oncall.rotation_weekly') }}</option>
            <option value="custom_days">{{ t('oncall.rotation_custom_label') }}</option>
          </select>
        </div>
        <div v-if="form.rotation_type === 'custom_days'">
          <label class="block text-sm font-medium text-(--text-2) mb-1">{{ t('oncall.rotation_length') }}</label>
          <input v-model.number="form.rotation_length_days" class="input w-full" type="number" min="1" max="365" />
        </div>
      </div>

      <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <div>
          <label class="block text-sm font-medium text-(--text-2) mb-1">{{ t('oncall.handoff_time') }}</label>
          <input v-model="form.handoff_time" class="input w-full" type="time" required />
        </div>
        <div>
          <label class="block text-sm font-medium text-(--text-2) mb-1">{{ t('oncall.timezone') }}</label>
          <select v-model="form.timezone" class="input w-full">
            <option v-for="tz in timezones" :key="tz" :value="tz">{{ tz }}</option>
          </select>
        </div>
      </div>
      <!-- The handoff is local to this zone on purpose, and the rotation maths
           counts calendar days so it does not drift across DST. Worth saying:
           it is the difference between "09:00" and "09:00 most of the year". -->
      <p class="text-xs text-(--text-3)">{{ t('oncall.handoff_help') }}</p>

      <div>
        <label class="block text-sm font-medium text-(--text-2) mb-1">{{ t('oncall.start_at') }}</label>
        <input v-model="form.start_at" class="input w-full" type="datetime-local" required />
        <p class="text-xs text-(--text-3) mt-1">{{ t('oncall.start_at_help') }}</p>
      </div>

      <!-- Participants, in shift order -->
      <div>
        <label class="block text-sm font-medium text-(--text-2) mb-1">{{ t('oncall.participants') }}</label>
        <p v-if="!form.participants.length" class="text-xs text-(--down) mb-2">
          {{ t('oncall.no_participants_warning') }}
        </p>
        <div v-for="(p, i) in form.participants" :key="i" class="flex items-center gap-2 mb-2">
          <span class="text-xs text-(--text-3) w-6">{{ i + 1 }}.</span>
          <select v-model="p.user_id" class="input flex-1" required>
            <option value="">{{ t('oncall.pick_user') }}</option>
            <option v-for="u in users" :key="u.id" :value="u.id">{{ u.username || u.email }}</option>
          </select>
          <button type="button" class="btn-icon" :aria-label="t('oncall.move_up')" :disabled="i === 0"
            @click="move(i, -1)">↑</button>
          <button type="button" class="btn-icon" :aria-label="t('oncall.move_down')"
            :disabled="i === form.participants.length - 1" @click="move(i, 1)">↓</button>
          <button type="button" class="btn-icon" :aria-label="t('common.delete')" @click="form.participants.splice(i, 1)">
            <Trash2 :size="14" />
          </button>
        </div>
        <button type="button" class="btn-secondary btn-sm" @click="form.participants.push({ user_id: '' })">
          + {{ t('oncall.add_participant') }}
        </button>
      </div>

      <label class="flex items-center gap-2 text-sm text-(--text-2)">
        <input v-model="form.enabled" type="checkbox" /> {{ t('oncall.enabled') }}
      </label>

      <p v-if="errorMessage" class="text-xs text-(--down)">{{ errorMessage }}</p>

      <div class="flex justify-end gap-2 pt-2">
        <button type="button" class="btn-secondary" @click="$emit('close')">{{ t('common.cancel') }}</button>
        <button type="submit" class="btn-primary" :disabled="saving">
          {{ saving ? t('common.loading') : t('common.save') }}
        </button>
      </div>
    </form>
  </BaseModal>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { Trash2 } from 'lucide-vue-next'
import BaseModal from '../BaseModal.vue'
import { oncallApi } from '../../api/oncall'
import { adminApi } from '../../api/admin'

const props = defineProps({ schedule: { type: Object, default: null } })
const emit = defineEmits(['close', 'saved'])
const { t } = useI18n()

const saving = ref(false)
const errorMessage = ref('')
const users = ref([])

// A short, curated list rather than the full IANA database: the picker is for
// choosing where the handoff happens, not for browsing 600 zone names.
const timezones = [
  'UTC', 'Europe/Paris', 'Europe/London', 'Europe/Berlin', 'Europe/Madrid',
  'America/New_York', 'America/Chicago', 'America/Denver', 'America/Los_Angeles',
  'America/Sao_Paulo', 'Asia/Tokyo', 'Asia/Shanghai', 'Asia/Kolkata', 'Asia/Dubai',
  'Australia/Sydney',
]

function toLocalInput(iso) {
  if (!iso) return new Date().toISOString().slice(0, 16)
  return new Date(iso).toISOString().slice(0, 16)
}

const form = reactive({
  name: props.schedule?.name ?? '',
  timezone: props.schedule?.timezone ?? 'UTC',
  rotation_type: props.schedule?.rotation_type ?? 'weekly',
  rotation_length_days: props.schedule?.rotation_length_days ?? 7,
  handoff_time: props.schedule?.handoff_time ?? '09:00',
  start_at: toLocalInput(props.schedule?.start_at),
  enabled: props.schedule?.enabled ?? true,
  participants: (props.schedule?.participants ?? [])
    .slice()
    .sort((a, b) => a.position - b.position)
    .map((p) => ({ user_id: p.user_id })),
})

function move(index, delta) {
  const target = index + delta
  if (target < 0 || target >= form.participants.length) return
  const [item] = form.participants.splice(index, 1)
  form.participants.splice(target, 0, item)
}

async function save() {
  saving.value = true
  errorMessage.value = ''
  const payload = {
    name: form.name,
    timezone: form.timezone,
    rotation_type: form.rotation_type,
    rotation_length_days: form.rotation_length_days,
    handoff_time: form.handoff_time,
    start_at: new Date(form.start_at).toISOString(),
    enabled: form.enabled,
    // Positions are assigned from the list order — the server requires them
    // contiguous, and making the operator type them would only invite gaps.
    participants: form.participants
      .filter((p) => p.user_id)
      .map((p, i) => ({ user_id: p.user_id, position: i })),
  }
  try {
    if (props.schedule) await oncallApi.schedules.update(props.schedule.id, payload)
    else await oncallApi.schedules.create(payload)
    emit('saved')
  } catch (e) {
    errorMessage.value = e.response?.data?.detail || t('common.error')
  } finally {
    saving.value = false
  }
}

onMounted(async () => {
  try {
    const { data } = await adminApi.listUsers()
    users.value = data
  } catch {
    // A non-admin cannot list users; they can still rotate over themselves,
    // which is what the server's _assert_can_page_users allows anyway.
    users.value = []
  }
})
</script>
