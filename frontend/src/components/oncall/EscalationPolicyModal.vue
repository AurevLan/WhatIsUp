<template>
  <BaseModal :model-value="true" size="lg" :title="policy ? t('oncall.edit_policy') : t('oncall.add_policy')"
    @close="$emit('close')" @update:model-value="$emit('close')">
    <form class="space-y-4" @submit.prevent="save">
      <div>
        <label class="block text-sm font-medium text-(--text-2) mb-1">{{ t('common.name') }} *</label>
        <input v-model.trim="form.name" class="input w-full" required maxlength="200" />
      </div>

      <div>
        <label class="block text-sm font-medium text-(--text-2) mb-1">
          {{ t('oncall.repeat_count') }}
          <span class="text-(--text-3) font-normal">{{ t('oncall.repeat_hint') }}</span>
        </label>
        <input v-model.number="form.repeat_count" class="input w-full" type="number" min="0" max="10" />
      </div>

      <!-- The ladder itself -->
      <div>
        <label class="block text-sm font-medium text-(--text-2) mb-1">{{ t('oncall.levels') }}</label>
        <p v-if="!form.levels.length" class="text-xs text-(--down) mb-2">
          {{ t('oncall.no_levels_warning') }}
        </p>

        <div v-for="(level, i) in form.levels" :key="i" class="oncall-level">
          <div class="flex items-center gap-2 mb-2">
            <span class="text-xs text-(--text-3) w-10">L{{ i + 1 }}</span>
            <input v-model.number="level.delay_minutes" class="input w-24" type="number" min="0" max="1440"
              :aria-label="t('oncall.delay_minutes')" />
            <span class="text-xs text-(--text-3) whitespace-nowrap">{{ t('oncall.delay_suffix') }}</span>
            <button type="button" class="btn-icon ml-auto" :aria-label="t('common.delete')"
              @click="form.levels.splice(i, 1)"><Trash2 :size="14" /></button>
          </div>
          <div class="flex items-center gap-2 flex-wrap">
            <select v-model="level.target_type" class="input w-40" @change="onTargetTypeChange(level)">
              <option value="channel">{{ t('oncall.target_channel') }}</option>
              <option value="schedule">{{ t('oncall.target_schedule') }}</option>
              <option value="user">{{ t('oncall.target_user') }}</option>
            </select>

            <select v-if="level.target_type === 'channel'" v-model="level.target_channel_id" class="input flex-1" required>
              <option value="">{{ t('oncall.pick_channel') }}</option>
              <option v-for="c in channels" :key="c.id" :value="c.id">{{ c.name }}</option>
            </select>
            <select v-else-if="level.target_type === 'schedule'" v-model="level.target_schedule_id" class="input flex-1" required>
              <option value="">{{ t('oncall.pick_schedule') }}</option>
              <option v-for="s in schedules" :key="s.id" :value="s.id">{{ s.name }}</option>
            </select>
            <select v-else v-model="level.target_user_id" class="input flex-1" required>
              <option value="">{{ t('oncall.pick_user') }}</option>
              <option v-for="u in users" :key="u.id" :value="u.id">{{ u.username || u.email }}</option>
            </select>
          </div>
        </div>

        <button type="button" class="btn-secondary btn-sm" @click="addLevel">
          + {{ t('oncall.add_level') }}
        </button>
        <p class="text-xs text-(--text-3) mt-2">{{ t('oncall.delay_help') }}</p>
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
import api from '../../api/client'
import { oncallApi } from '../../api/oncall'
import { adminApi } from '../../api/admin'

const props = defineProps({
  policy: { type: Object, default: null },
  schedules: { type: Array, default: () => [] },
})
const emit = defineEmits(['close', 'saved'])
const { t } = useI18n()

const saving = ref(false)
const errorMessage = ref('')
const channels = ref([])
const users = ref([])

const form = reactive({
  name: props.policy?.name ?? '',
  repeat_count: props.policy?.repeat_count ?? 0,
  enabled: props.policy?.enabled ?? true,
  levels: (props.policy?.levels ?? [])
    .slice()
    .sort((a, b) => a.position - b.position)
    .map((l) => ({
      delay_minutes: l.delay_minutes,
      target_type: l.target_type,
      target_channel_id: l.target_channel_id ?? '',
      target_schedule_id: l.target_schedule_id ?? '',
      target_user_id: l.target_user_id ?? '',
    })),
})

function addLevel() {
  form.levels.push({
    // The first rung defaults to firing immediately; later ones wait, which is
    // what makes a ladder a ladder rather than a fan-out.
    delay_minutes: form.levels.length === 0 ? 0 : 15,
    target_type: 'channel',
    target_channel_id: '',
    target_schedule_id: '',
    target_user_id: '',
  })
}

// The server enforces — in a CHECK constraint — that exactly the FK matching
// `target_type` is set. Clearing the others here keeps a switched dropdown from
// submitting a level that would be rejected, or worse, page nobody.
function onTargetTypeChange(level) {
  level.target_channel_id = ''
  level.target_schedule_id = ''
  level.target_user_id = ''
}

async function save() {
  saving.value = true
  errorMessage.value = ''
  const payload = {
    name: form.name,
    repeat_count: form.repeat_count,
    enabled: form.enabled,
    // Positions from list order: the server requires them contiguous.
    levels: form.levels.map((l, i) => ({
      position: i,
      delay_minutes: l.delay_minutes ?? 0,
      target_type: l.target_type,
      target_channel_id: l.target_type === 'channel' ? l.target_channel_id || null : null,
      target_schedule_id: l.target_type === 'schedule' ? l.target_schedule_id || null : null,
      target_user_id: l.target_type === 'user' ? l.target_user_id || null : null,
    })),
  }
  try {
    if (props.policy) await oncallApi.policies.update(props.policy.id, payload)
    else await oncallApi.policies.create(payload)
    emit('saved')
  } catch (e) {
    errorMessage.value = e.response?.data?.detail || t('common.error')
  } finally {
    saving.value = false
  }
}

onMounted(async () => {
  const [ch, us] = await Promise.all([
    api.get('/alerts/channels').catch(() => ({ data: [] })),
    adminApi.listUsers().catch(() => ({ data: [] })),
  ])
  channels.value = ch.data
  users.value = us.data
})
</script>

<style scoped>
.oncall-level {
  border: 1px solid var(--border);
  border-radius: 0.5rem;
  padding: 0.6rem;
  margin-bottom: 0.5rem;
  background: var(--bg-surface-2);
}
</style>
