<template>
  <div class="rounded-lg bg-gray-900/50 border border-gray-800 p-3 space-y-3">
    <label class="flex items-center gap-2 text-xs text-gray-300">
      <input
        type="checkbox"
        class="accent-blue-500"
        :checked="enabled"
        @change="onToggle($event.target.checked)"
      />
      <span class="font-medium">{{ t('alert_matrix.schedule.enable') }}</span>
      <span class="text-gray-500">{{ t('alert_matrix.schedule.enable_hint') }}</span>
    </label>

    <div v-if="enabled" class="grid grid-cols-1 md:grid-cols-3 gap-3 text-xs">
      <label class="flex flex-col gap-1">
        <span class="text-gray-400">{{ t('alert_matrix.schedule.timezone') }}</span>
        <input
          v-model="local.timezone"
          @change="emitChange"
          type="text"
          list="tz-list"
          placeholder="Europe/Paris"
          class="input py-1"
        />
        <datalist id="tz-list">
          <option v-for="tz in COMMON_TIMEZONES" :key="tz" :value="tz" />
        </datalist>
      </label>

      <label class="flex flex-col gap-1">
        <span class="text-gray-400">{{ t('alert_matrix.schedule.start') }}</span>
        <input
          v-model="local.start"
          @change="emitChange"
          type="time"
          class="input py-1"
        />
      </label>

      <label class="flex flex-col gap-1">
        <span class="text-gray-400">{{ t('alert_matrix.schedule.end') }}</span>
        <input
          v-model="local.end"
          @change="emitChange"
          type="time"
          class="input py-1"
        />
      </label>
    </div>

    <div v-if="enabled" class="flex flex-wrap gap-1.5 text-xs">
      <button
        v-for="(label, idx) in DAY_LABELS"
        :key="idx"
        type="button"
        @click="toggleDay(idx)"
        class="px-2.5 py-1 rounded-md border font-medium transition-colors"
        :class="local.days.includes(idx)
          ? 'border-blue-400 bg-blue-500/20 text-blue-300'
          : 'border-gray-700 text-gray-500 hover:text-gray-300'"
      >
        {{ label }}
      </button>
    </div>

    <p v-if="enabled" class="text-[11px] text-gray-500">
      {{ t('alert_matrix.schedule.summary', {
        days: local.days.length,
        start: local.start,
        end: local.end,
        tz: local.timezone,
      }) }}
    </p>
  </div>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import { useI18n } from 'vue-i18n'

const props = defineProps({
  modelValue: { type: Object, default: null },
})
const emit = defineEmits(['update:modelValue'])
const { t } = useI18n()

const DAY_LABELS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
const COMMON_TIMEZONES = [
  'UTC',
  'Europe/Paris',
  'Europe/London',
  'Europe/Berlin',
  'America/New_York',
  'America/Los_Angeles',
  'Asia/Tokyo',
  'Asia/Singapore',
  'Australia/Sydney',
]

function defaults() {
  return {
    timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC',
    days: [0, 1, 2, 3, 4],
    start: '09:00',
    end: '18:00',
    offhours_suppress: true,
  }
}

const local = ref({ ...defaults(), ...(props.modelValue || {}) })

const enabled = computed(
  () => props.modelValue != null && props.modelValue.offhours_suppress === true
)

function emitChange() {
  emit('update:modelValue', { ...local.value, offhours_suppress: true })
}

function onToggle(on) {
  if (on) {
    local.value = { ...defaults(), ...(props.modelValue || {}), offhours_suppress: true }
    emitChange()
  } else {
    emit('update:modelValue', null)
  }
}

function toggleDay(idx) {
  const days = [...local.value.days]
  const i = days.indexOf(idx)
  if (i >= 0) days.splice(i, 1)
  else days.push(idx)
  days.sort()
  local.value.days = days
  emitChange()
}

watch(
  () => props.modelValue,
  (v) => {
    if (v) local.value = { ...defaults(), ...v }
  },
  { deep: true },
)
</script>
