<template>
  <!-- ===== MODAL TEAM DETAIL ===== -->
  <Teleport to="body">
    <div v-if="modelValue && team" class="fixed inset-0 bg-black/60 backdrop-blur-sm z-50 flex items-center justify-center p-4" @click.self="close">
      <div class="card w-full max-w-2xl max-h-[85vh] overflow-y-auto" @click.stop>

        <!-- Header -->
        <div class="flex justify-between items-center mb-6">
          <div>
            <h2 class="text-lg font-semibold text-white">{{ team.name }}</h2>
            <span class="text-xs text-gray-500 font-mono">{{ team.slug }}</span>
          </div>
          <div class="flex items-center gap-2">
            <button @click="openEditTeamModal" class="p-1.5 text-gray-500 hover:text-blue-400 transition-colors rounded" :title="t('common.edit')">
              <Pencil class="w-4 h-4" />
            </button>
            <button @click="confirmDeleteTeam" class="p-1.5 text-gray-500 hover:text-red-400 transition-colors rounded" :title="t('common.delete')">
              <Trash2 class="w-4 h-4" />
            </button>
            <button @click="close" class="text-gray-500 hover:text-gray-300">
              <X class="w-5 h-5" />
            </button>
          </div>
        </div>

        <!-- Members section -->
        <div class="mb-4 flex items-center justify-between">
          <h3 class="text-sm font-medium text-gray-400">{{ t('admin.members_count', { n: teamMembers.length }) }}</h3>
          <button @click="showTeamAddMember = !showTeamAddMember" class="btn-primary text-xs flex items-center gap-1 px-3 py-1.5">
            <UserPlus class="w-3.5 h-3.5" /> {{ t('admin.add_member') }}
          </button>
        </div>

        <!-- Add member inline form -->
        <div v-if="showTeamAddMember" class="mb-4 p-3 rounded-lg bg-gray-800/60 border border-gray-700/50 space-y-3">
          <div>
            <label class="block text-xs text-gray-400 mb-1">{{ t('admin.label_user') }}</label>
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
            <label class="block text-xs text-gray-400 mb-1">{{ t('admin.label_role') }}</label>
            <select v-model="teamAddMemberForm.role" class="input w-full text-sm">
              <option value="viewer">Viewer</option>
              <option value="editor">Editor</option>
              <option value="admin">Admin</option>
              <option value="owner">Owner</option>
            </select>
          </div>
          <div v-if="teamMemberError" class="text-red-400 text-xs">{{ teamMemberError }}</div>
          <div class="flex justify-end gap-2">
            <button @click="showTeamAddMember = false" class="btn-secondary text-xs px-3 py-1">{{ t('common.cancel') }}</button>
            <button @click="submitTeamAddMember" class="btn-primary text-xs px-3 py-1" :disabled="!teamAddMemberForm.user_id || submitting">{{ t('admin.add_btn') }}</button>
          </div>
        </div>

        <!-- Members table -->
        <div class="card overflow-hidden !p-0">
          <table class="w-full text-sm">
            <thead>
              <tr class="border-b border-gray-800">
                <th class="text-left px-4 py-2.5 text-gray-400 font-medium">{{ t('admin.col_user') }}</th>
                <th class="text-left px-4 py-2.5 text-gray-400 font-medium">{{ t('admin.label_role') }}</th>
                <th class="text-right px-4 py-2.5 text-gray-400 font-medium">{{ t('admin.col_actions') }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-if="loadingTeamMembers">
                <td colspan="3" class="text-center py-6 text-gray-600">{{ t('admin.loading') }}</td>
              </tr>
              <tr v-else-if="teamMembers.length === 0">
                <td colspan="3" class="text-center py-6 text-gray-600">{{ t('admin.no_members') }}</td>
              </tr>
              <tr
                v-else
                v-for="m in teamMembers"
                :key="m.user_id"
                class="border-b border-gray-800/50 hover:bg-gray-800/30 transition-colors"
              >
                <td class="px-4 py-2.5">
                  <div class="flex items-center gap-2">
                    <div class="w-7 h-7 rounded-full bg-gradient-to-br from-blue-500 to-purple-600 flex items-center justify-center text-white font-bold text-xs flex-shrink-0">
                      {{ m.username[0]?.toUpperCase() }}
                    </div>
                    <div>
                      <div class="text-white font-medium text-sm">{{ m.username }}</div>
                      <div class="text-gray-500 text-xs">{{ m.email }}</div>
                    </div>
                  </div>
                </td>
                <td class="px-4 py-2.5">
                  <select
                    :value="m.role"
                    @change="changeTeamMemberRole(m, $event.target.value)"
                    class="input text-xs px-2 py-1 w-24"
                  >
                    <option value="viewer">Viewer</option>
                    <option value="editor">Editor</option>
                    <option value="admin">Admin</option>
                    <option value="owner">Owner</option>
                  </select>
                </td>
                <td class="px-4 py-2.5 text-right">
                  <button
                    @click="confirmRemoveTeamMember(m)"
                    class="p-1 text-gray-500 hover:text-red-400 transition-colors rounded"
                    :title="t('admin.remove_member_prefix')"
                  >
                    <Trash2 class="w-3.5 h-3.5" />
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>

      </div>
    </div>
  </Teleport>

  <!-- ===== MODAL EDIT TEAM ===== -->
  <Teleport to="body">
    <div v-if="showEditTeamModal" class="fixed inset-0 bg-black/60 backdrop-blur-sm z-50 flex items-center justify-center p-4" @click.self="showEditTeamModal = false">
      <div class="card w-full max-w-md" @click.stop>
        <div class="flex justify-between items-center mb-6">
          <h2 class="text-lg font-semibold text-white">{{ t('admin.edit_team_title') }}</h2>
          <button @click="showEditTeamModal = false" class="text-gray-500 hover:text-gray-300"><X class="w-5 h-5" /></button>
        </div>
        <form @submit.prevent="submitEditTeam" class="space-y-4">
          <div>
            <label class="block text-sm text-gray-400 mb-1">{{ t('common.name') }}</label>
            <input v-model="teamEditForm.name" type="text" class="input w-full" required maxlength="200" />
          </div>
          <div v-if="teamError" class="text-red-400 text-sm">{{ teamError }}</div>
          <div class="flex justify-end gap-3 pt-2">
            <button type="button" @click="showEditTeamModal = false" class="btn-secondary">{{ t('common.cancel') }}</button>
            <button type="submit" class="btn-primary" :disabled="submitting">{{ submitting ? t('admin.saving') : t('admin.save_btn') }}</button>
          </div>
        </form>
      </div>
    </div>
  </Teleport>

  <!-- ===== MODAL CONFIRM DELETE TEAM / REMOVE MEMBER ===== -->
  <Teleport to="body">
    <div v-if="showTeamDeleteModal" class="fixed inset-0 bg-black/60 backdrop-blur-sm z-50 flex items-center justify-center p-4" @click.self="showTeamDeleteModal = false">
      <div class="card w-full max-w-sm" @click.stop>
        <h2 class="text-lg font-semibold text-white mb-3">{{ t('admin.confirm_team_action') }}</h2>
        <p class="text-gray-400 text-sm mb-6">{{ teamDeletePrefix }} <strong class="text-white">{{ teamDeleteTarget }}</strong> {{ teamDeleteSuffix }}</p>
        <div class="flex justify-end gap-3">
          <button @click="showTeamDeleteModal = false" class="btn-secondary">{{ t('common.cancel') }}</button>
          <button @click="executeTeamDelete" class="bg-red-600 hover:bg-red-500 text-white px-4 py-2 rounded-lg text-sm font-medium transition-colors" :disabled="submitting">
            {{ t('common.confirm') }}
          </button>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup>
import { ref, watch, computed } from 'vue'
import { Pencil, Trash2, UserPlus, X } from 'lucide-vue-next'
import { useI18n } from 'vue-i18n'
import { useToast } from '../../composables/useToast'
import { teamsApi } from '../../api/teams'

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
    await teamsApi.addMember(props.team.id, teamAddMemberForm.value)
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
    await teamsApi.updateMember(props.team.id, member.user_id, { role: newRole })
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
    await teamsApi.removeMember(props.team.id, member.user_id)
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
    await teamsApi.delete(props.team.id)
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
    await teamsApi.update(props.team.id, teamEditForm.value)
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
