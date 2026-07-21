<template>
  <div class="page-body max-w-6xl">

    <!-- Header -->
    <div class="flex items-start justify-between mb-8">
      <div>
        <h1 class="font-display text-2xl font-bold text-(--text-1)">{{ t('admin.title') }}</h1>
        <p class="text-(--text-3) mt-1 text-sm">{{ t('admin.subtitle') }}</p>
      </div>
    </div>

    <!-- Tabs -->
    <div class="flex gap-1 mb-6 bg-(--bg-surface-2) p-1 rounded-xl border border-(--border) w-fit">
      <button
        v-for="tab in tabs"
        :key="tab.id"
        @click="activeTab = tab.id"
        :class="activeTab === tab.id
          ? 'bg-(--bg-surface-2) text-(--text-1) shadow-sm'
          : 'text-(--text-3) hover:text-(--text-1)'"
        class="px-4 py-2 rounded-lg text-sm font-medium transition-colors"
      >
        {{ tab.label }}
      </button>
    </div>

    <!-- ===== USERS TAB ===== -->
    <div v-if="activeTab === 'users'">
      <div class="flex justify-between items-center mb-4">
        <span class="text-sm text-(--text-3)">{{ t('admin.user_count', { n: users.length }) }}</span>
        <button @click="openCreateModal" class="btn-primary flex items-center gap-2">
          <UserPlus class="w-4 h-4" /> {{ t('admin.add_user') }}
        </button>
      </div>

      <div class="card overflow-hidden">
        <div class="overflow-x-auto">
        <table class="w-full text-sm min-w-[52rem]">
          <thead>
            <tr class="border-b border-(--border)">
              <th class="text-left px-4 py-3 text-(--text-2) font-medium">{{ t('admin.col_user') }}</th>
              <th class="text-left px-4 py-3 text-(--text-2) font-medium">{{ t('admin.col_email') }}</th>
              <th class="text-left px-4 py-3 text-(--text-2) font-medium">{{ t('admin.col_status') }}</th>
              <th class="text-left px-4 py-3 text-(--text-2) font-medium">{{ t('admin.col_permissions') }}</th>
              <th class="text-left px-4 py-3 text-(--text-2) font-medium">{{ t('admin.col_teams') }}</th>
              <th class="text-right px-4 py-3 text-(--text-2) font-medium">{{ t('admin.col_monitors') }}</th>
              <th class="text-right px-4 py-3 text-(--text-2) font-medium">{{ t('admin.col_actions') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="loadingUsers">
              <td colspan="7" class="text-center py-8 text-(--text-3)">{{ t('admin.loading') }}</td>
            </tr>
            <tr v-else-if="users.length === 0">
              <td colspan="7" class="text-center py-8 text-(--text-3)">{{ t('admin.no_users') }}</td>
            </tr>
            <tr
              v-else
              v-for="user in users"
              :key="user.id"
              class="border-b border-(--border) hover:bg-(--bg-surface-2) transition-colors"
            >
              <!-- Avatar + username -->
              <td class="px-4 py-3">
                <div class="flex items-center gap-3">
                  <div class="w-8 h-8 rounded-full [background:var(--brand-gradient)] flex items-center justify-center text-white font-bold text-sm flex-shrink-0">
                    {{ user.username[0]?.toUpperCase() }}
                  </div>
                  <div>
                    <div class="text-(--text-1) font-medium">{{ user.username }}</div>
                    <div v-if="user.full_name" class="text-(--text-3) text-xs">{{ user.full_name }}</div>
                  </div>
                </div>
              </td>
              <!-- Email -->
              <td class="px-4 py-3 text-(--text-2)">{{ user.email }}</td>
              <!-- Statut -->
              <td class="px-4 py-3">
                <span
                  :class="user.is_active ? 'bg-[color-mix(in_srgb,var(--up)_15%,transparent)] text-(--up) border-[color-mix(in_srgb,var(--up)_35%,transparent)]' : 'bg-(--bg-surface-2) text-(--text-3) border-(--border)'"
                  class="px-2 py-0.5 rounded text-xs border font-medium"
                >{{ user.is_active ? t('admin.status_active') : t('admin.status_inactive') }}</span>
                <span v-if="user.is_superadmin" class="ml-1 px-2 py-0.5 rounded text-xs border bg-(--accent-glow) text-(--accent) border-(--accent-border) font-medium">{{ t('sweep.admin') }}</span>
              </td>
              <!-- Permissions -->
              <td class="px-4 py-3">
                <span
                  v-if="user.can_create_monitors"
                  class="px-2 py-0.5 rounded text-xs border bg-(--accent-glow) text-(--accent) border-(--accent-border) font-medium"
                >{{ t('admin.can_create_monitors') }}</span>
                <span v-else class="text-(--text-3) text-xs">--</span>
              </td>
              <!-- Teams -->
              <td class="px-4 py-3">
                <div class="flex flex-wrap gap-1">
                  <span
                    v-for="tm in userTeamMap[user.id] || []"
                    :key="tm.team_id"
                    class="px-2 py-0.5 rounded text-xs border bg-(--bg-surface-2) text-(--text-2) border-(--border) font-medium"
                  >{{ tm.team_name }} <span class="text-(--text-3)">{{ tm.role }}</span></span>
                  <span v-if="!(userTeamMap[user.id] || []).length" class="text-(--text-3) text-xs">--</span>
                </div>
              </td>
              <!-- Monitor count -->
              <td class="px-4 py-3 text-right text-(--text-2)">{{ user.monitor_count }}</td>
              <!-- Actions -->
              <td class="px-4 py-3">
                <div class="flex justify-end gap-2">
                  <button
                    @click="openEditModal(user)"
                    class="p-1.5 text-(--text-3) hover:text-(--accent) transition-colors rounded"
                    :title="t('common.edit')"
                    :aria-label="t('common.edit')"
                  >
                    <Pencil class="w-4 h-4" />
                  </button>
                  <button
                    v-if="!user.is_superadmin"
                    @click="confirmDelete(user)"
                    class="p-1.5 text-(--text-3) hover:text-(--down) transition-colors rounded"
                    :title="t('common.delete')"
                    :aria-label="t('common.delete')"
                  >
                    <Trash2 class="w-4 h-4" />
                  </button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
        </div>
      </div>
    </div>

    <!-- ===== TEAMS TAB ===== -->
    <div v-if="activeTab === 'teams'">
      <div class="flex justify-between items-center mb-4">
        <span class="text-sm text-(--text-3)">{{ t('admin.team_count', { n: teams.length }) }}</span>
        <button @click="showCreateTeamModal = true" class="btn-primary flex items-center gap-2">
          <Plus class="w-4 h-4" /> {{ t('admin.create_team') }}
        </button>
      </div>

      <div v-if="loadingTeams" class="text-center py-8 text-(--text-3)">{{ t('admin.loading') }}</div>
      <div v-else-if="teams.length === 0" class="text-center py-16">
        <Users class="w-12 h-12 text-(--text-3) mx-auto mb-3" />
        <p class="text-(--text-3)">{{ t('admin.no_teams') }}</p>
      </div>

      <div v-else class="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <div
          v-for="team in teams"
          :key="team.id"
          class="card cursor-pointer hover:border-(--border-hover) transition-colors"
          @click="openTeamDetail(team)"
        >
          <div class="flex items-center justify-between mb-3">
            <h2 class="text-(--text-1) font-semibold text-lg">{{ team.name }}</h2>
            <span class="text-xs text-(--text-3) bg-(--bg-surface-2) px-2 py-0.5 rounded font-mono">{{ team.slug }}</span>
          </div>
          <div class="flex items-center gap-2 text-sm text-(--text-2)">
            <Users class="w-4 h-4" />
            <span>{{ team.member_count }} {{ team.member_count === 1 ? t('admin.member_singular') : t('admin.member_plural') }}</span>
          </div>
        </div>
      </div>
    </div>

    <!-- ===== MONITORS TAB ===== -->
    <div v-if="activeTab === 'monitors'">
      <div class="mb-4">
        <span class="text-sm text-(--text-3)">{{ t('admin.monitor_count', { n: allMonitors.length }) }}</span>
      </div>

      <div class="card overflow-hidden">
        <div class="overflow-x-auto">
        <table class="w-full text-sm min-w-[48rem]">
          <thead>
            <tr class="border-b border-(--border)">
              <th class="text-left px-4 py-3 text-(--text-2) font-medium">{{ t('admin.col_owner') }}</th>
              <th class="text-left px-4 py-3 text-(--text-2) font-medium">{{ t('admin.col_name') }}</th>
              <th class="text-left px-4 py-3 text-(--text-2) font-medium">{{ t('admin.col_type') }}</th>
              <th class="text-left px-4 py-3 text-(--text-2) font-medium">{{ t('admin.col_url') }}</th>
              <th class="text-left px-4 py-3 text-(--text-2) font-medium">{{ t('admin.col_status') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="loadingMonitors">
              <td colspan="5" class="text-center py-8 text-(--text-3)">{{ t('admin.loading') }}</td>
            </tr>
            <tr v-else-if="allMonitors.length === 0">
              <td colspan="5" class="text-center py-8 text-(--text-3)">{{ t('admin.no_monitors') }}</td>
            </tr>
            <tr
              v-else
              v-for="monitor in allMonitors"
              :key="monitor.id"
              class="border-b border-(--border) hover:bg-(--bg-surface-2) transition-colors"
            >
              <td class="px-4 py-3">
                <div class="flex items-center gap-2">
                  <div class="w-6 h-6 rounded-full [background:var(--brand-gradient)] flex items-center justify-center text-white font-bold text-xs flex-shrink-0">
                    {{ monitor.owner_username[0]?.toUpperCase() }}
                  </div>
                  <span class="text-(--text-2) text-xs">{{ monitor.owner_username }}</span>
                </div>
              </td>
              <td class="px-4 py-3 text-(--text-1) font-medium">{{ monitor.name }}</td>
              <td class="px-4 py-3">
                <span class="px-2 py-0.5 rounded text-xs border bg-(--bg-surface-2) text-(--text-2) border-(--border) font-mono">{{ monitor.check_type }}</span>
              </td>
              <td class="px-4 py-3 text-(--text-3) text-xs max-w-xs truncate">{{ monitor.url }}</td>
              <td class="px-4 py-3">
                <span
                  :class="monitor.enabled ? 'bg-[color-mix(in_srgb,var(--up)_15%,transparent)] text-(--up) border-[color-mix(in_srgb,var(--up)_35%,transparent)]' : 'bg-(--bg-surface-2) text-(--text-3) border-(--border)'"
                  class="px-2 py-0.5 rounded text-xs border font-medium"
                >{{ monitor.enabled ? t('admin.monitor_enabled') : t('admin.monitor_disabled') }}</span>
              </td>
            </tr>
          </tbody>
        </table>
        </div>
      </div>
    </div>

    <!-- ===== PROBE GROUPS TAB ===== -->
    <div v-if="activeTab === 'probe-groups'">
      <div class="flex justify-between items-center mb-4">
        <span class="text-sm text-(--text-3)">{{ t('admin.group_count', { n: probeGroups.length }) }}</span>
        <button @click="openCreateGroupModal" class="btn-primary flex items-center gap-2">
          <Plus class="w-4 h-4" /> {{ t('admin.create_group') }}
        </button>
      </div>

      <div v-if="loadingGroups" class="text-center py-8 text-(--text-3)">{{ t('admin.loading') }}</div>
      <div v-else-if="probeGroups.length === 0" class="text-center py-8 text-(--text-3)">{{ t('admin.no_groups') }}</div>
      <div v-else class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        <div
          v-for="group in probeGroups"
          :key="group.id"
          class="card p-4 flex flex-col gap-3"
        >
          <div class="flex items-start justify-between gap-2">
            <div>
              <div class="text-(--text-1) font-semibold">{{ group.name }}</div>
              <div v-if="group.description" class="text-(--text-3) text-xs mt-0.5">{{ group.description }}</div>
            </div>
            <div class="flex gap-1 flex-shrink-0">
              <button @click="openEditGroupModal(group)" class="p-1.5 text-(--text-3) hover:text-(--accent) transition-colors rounded" :title="t('common.edit')" :aria-label="t('common.edit')">
                <Pencil class="w-4 h-4" />
              </button>
              <button @click="confirmDeleteGroup(group)" class="p-1.5 text-(--text-3) hover:text-(--down) transition-colors rounded" :title="t('common.delete')" :aria-label="t('common.delete')">
                <Trash2 class="w-4 h-4" />
              </button>
            </div>
          </div>
          <div class="flex gap-3 text-xs text-(--text-3)">
            <span class="px-2 py-0.5 rounded bg-(--bg-surface-2) border border-(--border)">{{ t('admin.group_probes', { n: group.probe_ids.length }) }}</span>
            <span class="px-2 py-0.5 rounded bg-(--bg-surface-2) border border-(--border)">{{ t('admin.group_users', { n: group.user_ids.length }) }}</span>
          </div>
          <button @click="openGroupDetailModal(group)" class="text-xs text-(--accent) hover:text-(--accent) transition-colors text-left">
            {{ t('admin.manage_access') }}
          </button>
        </div>
      </div>
    </div>

    <!-- ===== OIDC TAB ===== -->
    <div v-if="activeTab === 'oidc'">
      <div v-if="oidcLoading" class="text-center py-8 text-(--text-3)">{{ t('admin.loading') }}</div>
      <div v-else class="max-w-xl">
        <div v-if="oidcSettings?.source === 'env'" class="mb-4 px-3 py-2 rounded-lg bg-[color-mix(in_srgb,var(--warn)_15%,transparent)] border border-[color-mix(in_srgb,var(--warn)_35%,transparent)] text-(--warn) text-sm">
          {{ t('admin.oidc_env_warning') }}
        </div>

        <form @submit.prevent="saveOidcSettings" class="space-y-5">
          <!-- Enabled toggle -->
          <div class="flex items-center justify-between py-3 px-4 rounded-lg bg-(--bg-surface-2) border border-(--border)">
            <div>
              <div class="text-sm text-(--text-2) font-medium">{{ t('admin.oidc_enable_label') }}</div>
              <div class="text-xs text-(--text-3) mt-0.5">{{ t('admin.oidc_enable_desc') }}</div>
            </div>
            <button
              type="button"
              @click="oidcForm.oidc_enabled = !oidcForm.oidc_enabled"
              :aria-label="t('admin.oidc_enable_label')"
              :class="oidcForm.oidc_enabled ? 'bg-(--accent)' : 'bg-(--bg-surface-3)'"
              class="relative w-11 h-6 rounded-full transition-colors flex-shrink-0"
            >
              <span
                :class="oidcForm.oidc_enabled ? 'translate-x-5' : 'translate-x-1'"
                class="absolute top-0.5 w-5 h-5 bg-white rounded-full shadow transition-transform"
              />
            </button>
          </div>

          <div>
            <label class="block text-sm text-(--text-2) mb-1">{{ t('admin.oidc_issuer_label') }} <span class="text-(--text-3)">{{ t('sweep.oidc_issuer_hint') }}</span></label>
            <input v-model="oidcForm.oidc_issuer_url" type="url" class="input w-full" placeholder="https://accounts.example.com" />
          </div>

          <div>
            <label class="block text-sm text-(--text-2) mb-1">{{ t('admin.oidc_client_id_label') }}</label>
            <input v-model="oidcForm.oidc_client_id" type="text" class="input w-full" />
          </div>

          <div>
            <label class="block text-sm text-(--text-2) mb-1">
              {{ t('admin.oidc_client_secret_label') }}
              <span v-if="oidcSettings?.oidc_client_secret_set" class="ml-1 text-xs text-(--up)">{{ t('admin.oidc_client_secret_set') }}</span>
              <span v-else class="ml-1 text-xs text-(--text-3)">{{ t('admin.oidc_client_secret_unset') }}</span>
            </label>
            <input v-model="oidcForm.oidc_client_secret" type="password" class="input w-full" autocomplete="new-password" placeholder="••••••••" />
          </div>

          <div>
            <label class="block text-sm text-(--text-2) mb-1">
              {{ t('admin.oidc_redirect_uri_label') }}
              <span class="text-(--text-3)">{{ t('admin.oidc_redirect_uri_hint') }}</span>
            </label>
            <input v-model="oidcForm.oidc_redirect_uri" type="url" class="input w-full" placeholder="https://app.example.com/api/v1/auth/oidc/callback" />
          </div>

          <div>
            <label class="block text-sm text-(--text-2) mb-1">{{ t('admin.oidc_scopes_label') }}</label>
            <input v-model="oidcForm.oidc_scopes" type="text" class="input w-full" />
          </div>

          <!-- Auto-provision toggle -->
          <div class="flex items-center justify-between py-3 px-4 rounded-lg bg-(--bg-surface-2) border border-(--border)">
            <div>
              <div class="text-sm text-(--text-2) font-medium">{{ t('admin.oidc_auto_provision_label') }}</div>
              <div class="text-xs text-(--text-3) mt-0.5">{{ t('admin.oidc_auto_provision_desc') }}</div>
            </div>
            <button
              type="button"
              @click="oidcForm.oidc_auto_provision = !oidcForm.oidc_auto_provision"
              :aria-label="t('admin.oidc_auto_provision_label')"
              :class="oidcForm.oidc_auto_provision ? 'bg-(--accent)' : 'bg-(--bg-surface-3)'"
              class="relative w-11 h-6 rounded-full transition-colors flex-shrink-0"
            >
              <span
                :class="oidcForm.oidc_auto_provision ? 'translate-x-5' : 'translate-x-1'"
                class="absolute top-0.5 w-5 h-5 bg-white rounded-full shadow transition-transform"
              />
            </button>
          </div>

          <div v-if="oidcError" class="text-(--down) text-sm">{{ oidcError }}</div>
          <div v-if="oidcSuccess" class="text-(--up) text-sm">{{ t('admin.oidc_saved') }}</div>

          <div class="flex justify-end">
            <button type="submit" class="btn-primary" :disabled="oidcSaving">
              {{ oidcSaving ? t('admin.oidc_saving') : t('admin.oidc_save') }}
            </button>
          </div>
        </form>
      </div>
    </div>

    <!-- ===== MODALS (composants admin/) ===== -->
    <GroupFormModal v-model="showGroupFormModal" :group="editingGroup" @saved="loadProbeGroups" />
    <AdminConfirmModal
      v-model="showDeleteGroupModal"
      :title="t('admin.confirm_delete_group')"
      :message="deletingGroup ? t('admin.confirm_delete_group_msg', { name: deletingGroup.name }) : ''"
      :busy="submitting"
      @confirm="executeDeleteGroup"
    />
    <GroupDetailModal
      v-model="showGroupDetailModal"
      :group="detailGroup"
      :probes="allProbes"
      :users="users"
      @changed="loadProbeGroups"
    />
    <UserCreateModal v-model="showCreateModal" @saved="loadUsers" />
    <UserEditModal v-model="showEditModal" :user="editingUser" @saved="loadUsers" />
    <AdminConfirmModal
      v-model="showDeleteModal"
      :title="t('admin.confirm_delete_user')"
      :message="deletingUser ? t('admin.confirm_delete_msg', { name: deletingUser.username }) : ''"
      :busy="submitting"
      @confirm="executeDelete"
    />
    <TeamCreateModal v-model="showCreateTeamModal" @saved="loadTeams" />
    <TeamDetailModal
      v-model="showTeamDetailModal"
      :team="selectedTeam"
      :users="users"
      @changed="loadTeams"
      @renamed="onTeamRenamed"
      @deleted="onTeamDeleted"
    />

  </div>
</template>

<script setup>
import { ref, onMounted, watch, computed } from 'vue'
import { Pencil, Trash2, UserPlus, Plus, Users } from 'lucide-vue-next'
import { useI18n } from 'vue-i18n'
import { adminApi } from '../api/admin'
import { teamsApi } from '../api/teams'
import { useProbesStore } from '../stores/probes'
import AdminConfirmModal from '../components/admin/AdminConfirmModal.vue'
import UserCreateModal from '../components/admin/UserCreateModal.vue'
import UserEditModal from '../components/admin/UserEditModal.vue'
import TeamCreateModal from '../components/admin/TeamCreateModal.vue'
import TeamDetailModal from '../components/admin/TeamDetailModal.vue'
import GroupFormModal from '../components/admin/GroupFormModal.vue'
import GroupDetailModal from '../components/admin/GroupDetailModal.vue'

const { t } = useI18n()
const probesStore = useProbesStore()

const tabs = computed(() => [
  { id: 'users', label: t('admin.tab_users') },
  { id: 'teams', label: t('admin.tab_teams') },
  { id: 'monitors', label: t('admin.tab_monitors') },
  { id: 'probe-groups', label: t('admin.tab_probe_groups') },
  { id: 'oidc', label: t('admin.tab_oidc') },
])
const activeTab = ref('users')

const submitting = ref(false)

// ─── Users ──────────────────────────────────────────────────────────────────
const users = ref([])
const loadingUsers = ref(false)

async function loadUsers() {
  loadingUsers.value = true
  try {
    const { data } = await adminApi.listUsers()
    users.value = data
  } finally {
    loadingUsers.value = false
  }
}

// ─── Monitors ───────────────────────────────────────────────────────────────
const allMonitors = ref([])
const loadingMonitors = ref(false)

async function loadMonitors() {
  loadingMonitors.value = true
  try {
    const { data } = await adminApi.listMonitors()
    allMonitors.value = data
  } finally {
    loadingMonitors.value = false
  }
}

watch(activeTab, (tab) => {
  if (tab === 'monitors' && allMonitors.value.length === 0) loadMonitors()
  if (tab === 'probe-groups') {
    loadProbeGroups()
    loadAllProbes()
    if (users.value.length === 0) loadUsers()
  }
  if (tab === 'oidc') loadOidcSettings()
  if (tab === 'teams') {
    loadTeams()
    if (users.value.length === 0) loadUsers()
  }
})

onMounted(() => loadUsers())

// ─── Create / edit user (modals) ────────────────────────────────────────────
const showCreateModal = ref(false)
const showEditModal = ref(false)
const editingUser = ref(null)

function openCreateModal() {
  showCreateModal.value = true
}

function openEditModal(user) {
  editingUser.value = user
  showEditModal.value = true
}

// ─── Delete user ────────────────────────────────────────────────────────────
const showDeleteModal = ref(false)
const deletingUser = ref(null)

function confirmDelete(user) {
  deletingUser.value = user
  showDeleteModal.value = true
}

async function executeDelete() {
  submitting.value = true
  try {
    await adminApi.deleteUser(deletingUser.value.id)
    showDeleteModal.value = false
    await loadUsers()
  } finally {
    submitting.value = false
  }
}

// ─── Teams ──────────────────────────────────────────────────────────────────
const teams = ref([])
const loadingTeams = ref(false)
const selectedTeam = ref(null)
const showTeamDetailModal = ref(false)
const showCreateTeamModal = ref(false)

// Build a map: userId -> [{team_id, team_name, role}]
const userTeamMap = computed(() => {
  const map = {}
  for (const team of teams.value) {
    if (!team._members) continue
    for (const m of team._members) {
      if (!map[m.user_id]) map[m.user_id] = []
      map[m.user_id].push({ team_id: team.id, team_name: team.name, role: m.role })
    }
  }
  return map
})

async function loadTeams() {
  loadingTeams.value = true
  try {
    const { data } = await teamsApi.list()
    // Load members for each team to build the user-team map
    const teamsWithMembers = await Promise.all(data.map(async (t) => {
      try {
        const { data: members } = await teamsApi.listMembers(t.id)
        return { ...t, _members: members }
      } catch {
        return { ...t, _members: [] }
      }
    }))
    teams.value = teamsWithMembers
  } finally {
    loadingTeams.value = false
  }
}

function openTeamDetail(team) {
  selectedTeam.value = team
  showTeamDetailModal.value = true
}

function onTeamRenamed(name) {
  if (selectedTeam.value) selectedTeam.value.name = name
}

function onTeamDeleted() {
  showTeamDetailModal.value = false
  selectedTeam.value = null
  loadTeams()
}

// ─── Probe Groups ───────────────────────────────────────────────────────────

const probeGroups = ref([])
const loadingGroups = ref(false)
const allProbes = ref([])

async function loadProbeGroups() {
  loadingGroups.value = true
  try {
    const { data } = await adminApi.listProbeGroups()
    probeGroups.value = data
  } finally {
    loadingGroups.value = false
  }
}

async function loadAllProbes() {
  try {
    // Through the shared store (force: admin must see post-mutation state).
    allProbes.value = await probesStore.fetch({ force: true })
  } catch {
    // ignore
  }
}

// Create / edit group (GroupFormModal : group=null → création)
const showGroupFormModal = ref(false)
const editingGroup = ref(null)

function openCreateGroupModal() {
  editingGroup.value = null
  showGroupFormModal.value = true
}

function openEditGroupModal(group) {
  editingGroup.value = group
  showGroupFormModal.value = true
}

// Delete group
const showDeleteGroupModal = ref(false)
const deletingGroup = ref(null)

function confirmDeleteGroup(group) {
  deletingGroup.value = group
  showDeleteGroupModal.value = true
}

async function executeDeleteGroup() {
  submitting.value = true
  try {
    await adminApi.deleteProbeGroup(deletingGroup.value.id)
    showDeleteGroupModal.value = false
    await loadProbeGroups()
  } finally {
    submitting.value = false
  }
}

// Group detail modal
const showGroupDetailModal = ref(false)
const detailGroup = ref(null)

function openGroupDetailModal(group) {
  detailGroup.value = group
  showGroupDetailModal.value = true
}

// ─── OIDC Settings ──────────────────────────────────────────────────────────

const oidcSettings = ref(null)
const oidcLoading = ref(false)
const oidcSaving = ref(false)
const oidcSuccess = ref(false)
const oidcError = ref('')
const oidcForm = ref({
  oidc_enabled: false,
  oidc_issuer_url: '',
  oidc_client_id: '',
  oidc_client_secret: '',
  oidc_redirect_uri: '',
  oidc_scopes: 'openid email profile',
  oidc_auto_provision: true,
})

async function loadOidcSettings() {
  oidcLoading.value = true
  oidcError.value = ''
  try {
    const { data } = await adminApi.getOidcSettings({ skipErrorToast: true })
    oidcSettings.value = data
    oidcForm.value = {
      oidc_enabled: data.oidc_enabled,
      oidc_issuer_url: data.oidc_issuer_url || '',
      oidc_client_id: data.oidc_client_id || '',
      oidc_client_secret: '',
      oidc_redirect_uri: data.oidc_redirect_uri || '',
      oidc_scopes: data.oidc_scopes || 'openid email profile',
      oidc_auto_provision: data.oidc_auto_provision,
    }
  } catch (e) {
    oidcError.value = e.response?.data?.detail || t('common.error')
  } finally {
    oidcLoading.value = false
  }
}

async function saveOidcSettings() {
  oidcSaving.value = true
  oidcError.value = ''
  oidcSuccess.value = false
  try {
    const payload = { ...oidcForm.value }
    if (!payload.oidc_client_secret) payload.oidc_client_secret = null
    const { data } = await adminApi.updateOidcSettings(payload, { skipErrorToast: true })
    oidcSettings.value = data
    oidcForm.value.oidc_client_secret = ''
    oidcSuccess.value = true
    setTimeout(() => { oidcSuccess.value = false }, 3000)
  } catch (e) {
    oidcError.value = e.response?.data?.detail || t('common.error')
  } finally {
    oidcSaving.value = false
  }
}
</script>
