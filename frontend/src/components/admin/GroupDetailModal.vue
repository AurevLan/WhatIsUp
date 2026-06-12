<template>
  <BaseModal
    :model-value="modelValue && !!detailGroup"
    :title="detailGroup?.name || ''"
    size="lg"
    @update:model-value="$event || close()"
  >
        <!-- Probes section -->
        <div class="mb-6">
          <div class="flex items-center justify-between mb-3">
            <h3 class="text-sm font-medium text-gray-300">{{ t('admin.section_probes') }}</h3>
          </div>
          <div v-if="detailGroup.probe_ids.length === 0" class="text-gray-600 text-sm">{{ t('admin.no_probes_in_group') }}</div>
          <div v-else class="space-y-1 mb-3">
            <div
              v-for="probeId in detailGroup.probe_ids"
              :key="probeId"
              class="flex items-center justify-between py-1.5 px-3 rounded bg-gray-800/60 border border-gray-700/50"
            >
              <span class="text-gray-300 text-sm">{{ probeNameById(probeId) }}</span>
              <button @click="removeProbeFromDetailGroup(probeId)" class="text-gray-600 hover:text-red-400 transition-colors" :disabled="submitting" :aria-label="t('a11y.remove')">
                <X class="w-4 h-4" />
              </button>
            </div>
          </div>
          <!-- Add probes -->
          <div class="flex gap-2 mt-2">
            <select v-model="addProbeSelection" class="input flex-1 text-sm">
              <option value="">{{ t('admin.add_probe_placeholder') }}</option>
              <option
                v-for="probe in availableProbesForGroup"
                :key="probe.id"
                :value="probe.id"
              >{{ probe.name }} ({{ probe.location_name }})</option>
            </select>
            <button @click="addProbeToDetailGroup" class="btn-primary text-sm" :disabled="!addProbeSelection || submitting">{{ t('admin.add_btn') }}</button>
          </div>
        </div>

        <!-- Users section -->
        <div>
          <div class="flex items-center justify-between mb-3">
            <h3 class="text-sm font-medium text-gray-300">{{ t('admin.section_users') }}</h3>
          </div>
          <div v-if="detailGroup.user_ids.length === 0" class="text-gray-600 text-sm">{{ t('admin.no_users_in_group') }}</div>
          <div v-else class="space-y-1 mb-3">
            <div
              v-for="userId in detailGroup.user_ids"
              :key="userId"
              class="flex items-center justify-between py-1.5 px-3 rounded bg-gray-800/60 border border-gray-700/50"
            >
              <span class="text-gray-300 text-sm">{{ userNameById(userId) }}</span>
              <button @click="revokeUserFromDetailGroup(userId)" class="text-gray-600 hover:text-red-400 transition-colors" :disabled="submitting" :aria-label="t('a11y.remove')">
                <X class="w-4 h-4" />
              </button>
            </div>
          </div>
          <!-- Add user -->
          <div class="flex gap-2 mt-2">
            <select v-model="addUserSelection" class="input flex-1 text-sm">
              <option value="">{{ t('admin.add_user_placeholder') }}</option>
              <option
                v-for="user in availableUsersForGroup"
                :key="user.id"
                :value="user.id"
              >{{ user.username }}</option>
            </select>
            <button @click="grantUserToDetailGroup" class="btn-primary text-sm" :disabled="!addUserSelection || submitting">{{ t('admin.add_btn') }}</button>
          </div>
        </div>

        <div v-if="detailError" class="mt-4 text-red-400 text-sm">{{ detailError }}</div>
  </BaseModal>
</template>

<script setup>
import { ref, watch, computed } from 'vue'
import { X } from 'lucide-vue-next'
import { useI18n } from 'vue-i18n'
import { adminApi } from '../../api/admin'
import BaseModal from '../BaseModal.vue'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  group: { type: Object, default: null },
  probes: { type: Array, default: () => [] },
  users: { type: Array, default: () => [] },
})
const emit = defineEmits(['update:modelValue', 'changed'])

const { t } = useI18n()

const submitting = ref(false)
const detailGroup = ref(null)
const detailError = ref('')
const addProbeSelection = ref('')
const addUserSelection = ref('')

const availableProbesForGroup = computed(() => {
  if (!detailGroup.value) return props.probes
  return props.probes.filter(p => !detailGroup.value.probe_ids.includes(p.id))
})

const availableUsersForGroup = computed(() => {
  if (!detailGroup.value) return props.users
  return props.users.filter(u => !detailGroup.value.user_ids.includes(u.id))
})

watch(() => props.modelValue, (open) => {
  if (open && props.group) {
    detailGroup.value = { ...props.group, probe_ids: [...props.group.probe_ids], user_ids: [...props.group.user_ids] }
    addProbeSelection.value = ''
    addUserSelection.value = ''
    detailError.value = ''
  }
})

function close() {
  emit('update:modelValue', false)
}

function probeNameById(probeId) {
  const p = props.probes.find(p => p.id === probeId)
  return p ? `${p.name} (${p.location_name})` : probeId
}

function userNameById(userId) {
  const u = props.users.find(u => u.id === userId)
  return u ? u.username : userId
}

async function addProbeToDetailGroup() {
  if (!addProbeSelection.value) return
  submitting.value = true
  detailError.value = ''
  try {
    const { data } = await adminApi.addProbesToGroup(detailGroup.value.id, [addProbeSelection.value])
    detailGroup.value = { ...data, probe_ids: data.probe_ids, user_ids: data.user_ids }
    addProbeSelection.value = ''
    emit('changed')
  } catch (e) {
    detailError.value = e.response?.data?.detail || t('common.error')
  } finally {
    submitting.value = false
  }
}

async function removeProbeFromDetailGroup(probeId) {
  submitting.value = true
  detailError.value = ''
  try {
    await adminApi.removeProbeFromGroup(detailGroup.value.id, probeId)
    detailGroup.value.probe_ids = detailGroup.value.probe_ids.filter(id => id !== probeId)
    emit('changed')
  } catch (e) {
    detailError.value = e.response?.data?.detail || t('common.error')
  } finally {
    submitting.value = false
  }
}

async function grantUserToDetailGroup() {
  if (!addUserSelection.value) return
  submitting.value = true
  detailError.value = ''
  try {
    const { data } = await adminApi.grantGroupAccess(detailGroup.value.id, [addUserSelection.value])
    detailGroup.value = { ...data, probe_ids: data.probe_ids, user_ids: data.user_ids }
    addUserSelection.value = ''
    emit('changed')
  } catch (e) {
    detailError.value = e.response?.data?.detail || t('common.error')
  } finally {
    submitting.value = false
  }
}

async function revokeUserFromDetailGroup(userId) {
  submitting.value = true
  detailError.value = ''
  try {
    await adminApi.revokeGroupAccess(detailGroup.value.id, userId)
    detailGroup.value.user_ids = detailGroup.value.user_ids.filter(id => id !== userId)
    emit('changed')
  } catch (e) {
    detailError.value = e.response?.data?.detail || t('common.error')
  } finally {
    submitting.value = false
  }
}
</script>
