<template>
  <!-- ===== MODAL TEAM DETAIL ===== -->
  <BaseModal
    :model-value="modelValue && !!team"
    :title="team?.name || ''"
    size="lg"
    @update:model-value="$event || close()"
  >
    <template #header>
      <div class="flex justify-between items-center flex-1 mr-2">
        <div>
          <h2 class="text-lg font-semibold text-(--text-1)">{{ team.name }}</h2>
          <span class="text-xs text-(--text-3) font-mono">{{ team.slug }}</span>
        </div>
        <div class="flex items-center gap-2">
          <button @click="openEditTeamModal" class="p-1.5 text-(--text-3) hover:text-(--accent) transition-colors rounded" :title="t('common.edit')" :aria-label="t('common.edit')">
            <Pencil class="w-4 h-4" />
          </button>
          <button @click="confirmDeleteTeam" class="p-1.5 text-(--text-3) hover:text-(--down) transition-colors rounded" :title="t('common.delete')" :aria-label="t('common.delete')">
            <Trash2 class="w-4 h-4" />
          </button>
        </div>
      </div>
    </template>

        <!-- Members section -->
        <div class="mb-4 flex items-center justify-between">
          <h3 class="text-sm font-medium text-(--text-2)">{{ t('admin.members_count', { n: teamMembers.length }) }}</h3>
          <button @click="showTeamAddMember = !showTeamAddMember" class="btn-primary btn-sm flex items-center gap-1">
            <UserPlus class="w-3.5 h-3.5" /> {{ t('admin.add_member') }}
          </button>
        </div>

        <!-- Add member inline form -->
        <div v-if="showTeamAddMember" class="mb-4 p-3 rounded-lg bg-(--bg-surface-2) border border-(--border) space-y-3">
          <div>
            <label class="block text-xs text-(--text-2) mb-1">{{ t('admin.label_user') }}</label>
            <select v-model="teamAddMemberForm.user_id" class="input w-full text-sm">
              <option value="">{{ t('admin.select_user') }}</option>
              <option
                v-for="u in availableUsersForTeam"
                :key="u.id"
                :value="u.id"
              >{{ u.username }} ({{ u.email }})</option>
            </select>
          </div>
          <div>
            <label class="block text-xs text-(--text-2) mb-1">{{ t('admin.label_role') }}</label>
            <select v-model="teamAddMemberForm.role" class="input w-full text-sm">
              <option value="viewer">{{ t('sweep.role_viewer') }}</option>
              <option value="editor">{{ t('sweep.role_editor') }}</option>
              <option value="admin">{{ t('sweep.role_admin') }}</option>
              <option value="owner">{{ t('sweep.role_owner') }}</option>
            </select>
          </div>
          <div v-if="teamMemberError" class="text-(--down) text-xs">{{ teamMemberError }}</div>
          <div class="flex justify-end gap-2">
            <button @click="showTeamAddMember = false" class="btn-secondary btn-sm">{{ t('common.cancel') }}</button>
            <button @click="submitTeamAddMember" class="btn-primary btn-sm" :disabled="!teamAddMemberForm.user_id || submitting">{{ t('admin.add_btn') }}</button>
          </div>
        </div>

        <!-- Members table -->
        <div class="card overflow-hidden !p-0">
          <table class="w-full text-sm">
            <thead>
              <tr class="border-b border-(--border)">
                <th class="text-left px-4 py-2.5 text-(--text-2) font-medium">{{ t('admin.col_user') }}</th>
                <th class="text-left px-4 py-2.5 text-(--text-2) font-medium">{{ t('admin.label_role') }}</th>
                <th class="text-right px-4 py-2.5 text-(--text-2) font-medium">{{ t('admin.col_actions') }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-if="loadingTeamMembers">
                <td colspan="3" class="text-center py-6 text-(--text-3)">{{ t('admin.loading') }}</td>
              </tr>
              <tr v-else-if="teamMembers.length === 0">
                <td colspan="3" class="text-center py-6 text-(--text-3)">{{ t('admin.no_members') }}</td>
              </tr>
              <tr
                v-else
                v-for="m in teamMembers"
                :key="m.user_id"
                class="border-b border-(--border) hover:bg-(--bg-surface-2) transition-colors"
              >
                <td class="px-4 py-2.5">
                  <div class="flex items-center gap-2">
                    <div class="w-7 h-7 rounded-full bg-(--accent-glow) flex items-center justify-center text-(--accent) font-bold text-xs flex-shrink-0">
                      {{ m.username[0]?.toUpperCase() }}
                    </div>
                    <div>
                      <div class="text-(--text-1) font-medium text-sm">{{ m.username }}</div>
                      <div class="text-(--text-3) text-xs">{{ m.email }}</div>
                    </div>
                  </div>
                </td>
                <td class="px-4 py-2.5">
                  <select
                    :value="m.role"
                    @change="changeTeamMemberRole(m, $event.target.value)"
                    class="input text-xs px-2 py-1 w-24"
                  >
                    <option value="viewer">{{ t('sweep.role_viewer') }}</option>
                    <option value="editor">{{ t('sweep.role_editor') }}</option>
                    <option value="admin">{{ t('sweep.role_admin') }}</option>
                    <option value="owner">{{ t('sweep.role_owner') }}</option>
                  </select>
                </td>
                <td class="px-4 py-2.5 text-right">
                  <button
                    @click="confirmRemoveTeamMember(m)"
                    class="p-1 text-(--text-3) hover:text-(--down) transition-colors rounded"
                    :title="t('admin.remove_member_prefix')"
                    :aria-label="t('admin.remove_member_prefix')"
                  >
                    <Trash2 class="w-3.5 h-3.5" />
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
  </BaseModal>

  <!-- ===== MODAL EDIT TEAM ===== -->
  <BaseModal
    v-model="showEditTeamModal"
    :title="t('admin.edit_team_title')"
  >
        <form @submit.prevent="submitEditTeam" class="space-y-4">
          <div>
            <label class="block text-sm text-(--text-2) mb-1">{{ t('common.name') }}</label>
            <input v-model="teamEditForm.name" type="text" class="input w-full" required maxlength="200" />
          </div>
          <div v-if="teamError" class="text-(--down) text-sm">{{ teamError }}</div>
          <div class="flex justify-end gap-3 pt-2">
            <button type="button" @click="showEditTeamModal = false" class="btn-secondary">{{ t('common.cancel') }}</button>
            <button type="submit" class="btn-primary" :disabled="submitting">{{ submitting ? t('admin.saving') : t('admin.save_btn') }}</button>
          </div>
        </form>
  </BaseModal>

  <!-- ===== MODAL CONFIRM DELETE TEAM / REMOVE MEMBER ===== -->
  <BaseModal
    v-model="showTeamDeleteModal"
    :title="t('admin.confirm_team_action')"
    size="sm"
  >
    <p class="text-(--text-2) text-sm mb-6">{{ teamDeletePrefix }} <strong class="text-(--text-1)">{{ teamDeleteTarget }}</strong> {{ teamDeleteSuffix }}</p>
    <template #footer>
      <div class="flex justify-end gap-3 w-full">
        <button @click="showTeamDeleteModal = false" class="btn-secondary">{{ t('common.cancel') }}</button>
        <button @click="executeTeamDelete" class="btn-danger" :disabled="submitting">
          {{ t('common.confirm') }}
        </button>
      </div>
    </template>
  </BaseModal>
</template>

<script setup>
import { ref, watch, computed } from 'vue'
import { Pencil, Trash2, UserPlus } from 'lucide-vue-next'
import { useI18n } from 'vue-i18n'
import { useToast } from '../../composables/useToast'
import { teamsApi } from '../../api/teams'
import BaseModal from '../BaseModal.vue'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  team: { type: Object, default: null },
  users: { type: Array, default: () => [] },
})
const emit = defineEmits(['update:modelValue', 'changed', 'renamed', 'deleted'])

const { t } = useI18n()
const { error: toastError } = useToast()

const submitting = ref(false)
const teamMembers = ref([])
const loadingTeamMembers = ref(false)
const showEditTeamModal = ref(false)
const showTeamDeleteModal = ref(false)
const showTeamAddMember = ref(false)
const teamError = ref('')
const teamMemberError = ref('')
const teamDeletePrefix = ref('')
const teamDeleteTarget = ref('')
const teamDeleteSuffix = ref('')
let pendingTeamDeleteAction = null

const teamEditForm = ref({ name: '' })
const teamAddMemberForm = ref({ user_id: '', role: 'editor' })

const availableUsersForTeam = computed(() => {
  const memberIds = new Set(teamMembers.value.map(m => m.user_id))
  return props.users.filter(u => !memberIds.has(u.id))
})

watch(() => props.modelValue, (open) => {
  if (open && props.team) {
    showTeamAddMember.value = false
    teamMemberError.value = ''
    loadTeamMembers(props.team.id)
  }
})

function close() {
  emit('update:modelValue', false)
}

async function loadTeamMembers(teamId) {
  loadingTeamMembers.value = true
  try {
    const { data } = await teamsApi.listMembers(teamId)
    teamMembers.value = data
  } catch { teamMembers.value = [] } finally {
    loadingTeamMembers.value = false
  }
}

async function submitTeamAddMember() {
  submitting.value = true
  teamMemberError.value = ''
  try {
    await teamsApi.addMember(props.team.id, teamAddMemberForm.value, { skipErrorToast: true })
    teamAddMemberForm.value = { user_id: '', role: 'editor' }
    showTeamAddMember.value = false
    await loadTeamMembers(props.team.id)
    emit('changed')
  } catch (e) {
    teamMemberError.value = e.response?.data?.detail || t('common.error')
  } finally {
    submitting.value = false
  }
}

async function changeTeamMemberRole(member, newRole) {
  try {
    await teamsApi.updateMember(props.team.id, member.user_id, { role: newRole }, { skipErrorToast: true })
    await loadTeamMembers(props.team.id)
    emit('changed')
  } catch (e) {
    toastError(e.response?.data?.detail || t('teams.error_update_role'))
    await loadTeamMembers(props.team.id)
  }
}

function confirmRemoveTeamMember(member) {
  teamDeletePrefix.value = t('admin.remove_member_prefix')
  teamDeleteTarget.value = member.username
  teamDeleteSuffix.value = t('admin.remove_member_suffix')
  pendingTeamDeleteAction = async () => {
    await teamsApi.removeMember(props.team.id, member.user_id, { skipErrorToast: true })
    await loadTeamMembers(props.team.id)
    emit('changed')
  }
  showTeamDeleteModal.value = true
}

function confirmDeleteTeam() {
  teamDeletePrefix.value = t('admin.delete_team_prefix')
  teamDeleteTarget.value = props.team.name
  teamDeleteSuffix.value = t('admin.delete_team_suffix')
  pendingTeamDeleteAction = async () => {
    await teamsApi.delete(props.team.id, { skipErrorToast: true })
    emit('deleted')
  }
  showTeamDeleteModal.value = true
}

async function executeTeamDelete() {
  submitting.value = true
  try {
    await pendingTeamDeleteAction()
    showTeamDeleteModal.value = false
  } catch (e) {
    toastError(e.response?.data?.detail || t('common.error'))
  } finally {
    submitting.value = false
  }
}

function openEditTeamModal() {
  teamEditForm.value = { name: props.team.name }
  teamError.value = ''
  showEditTeamModal.value = true
}

async function submitEditTeam() {
  submitting.value = true
  teamError.value = ''
  try {
    await teamsApi.update(props.team.id, teamEditForm.value, { skipErrorToast: true })
    showEditTeamModal.value = false
    emit('renamed', teamEditForm.value.name)
    emit('changed')
  } catch (e) {
    teamError.value = e.response?.data?.detail || t('common.error')
  } finally {
    submitting.value = false
  }
}
</script>
