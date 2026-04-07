<template>
  <div class="page-body max-w-6xl">

    <!-- Header -->
    <div class="flex items-start justify-between mb-8">
      <div>
        <h1 class="text-2xl font-bold text-white">Administration</h1>
        <p class="text-gray-500 mt-1 text-sm">Gestion des utilisateurs, des equipes, des moniteurs et des groupes de sondes</p>
      </div>
    </div>

    <!-- Tabs -->
    <div class="flex gap-1 mb-6 bg-gray-800/60 p-1 rounded-xl border border-gray-700/50 w-fit">
      <button
        v-for="tab in tabs"
        :key="tab.id"
        @click="activeTab = tab.id"
        :class="activeTab === tab.id
          ? 'bg-gray-700 text-white shadow-sm'
          : 'text-gray-500 hover:text-gray-300'"
        class="px-4 py-2 rounded-lg text-sm font-medium transition-colors"
      >
        {{ tab.label }}
      </button>
    </div>

    <!-- ===== USERS TAB ===== -->
    <div v-if="activeTab === 'users'">
      <div class="flex justify-between items-center mb-4">
        <span class="text-sm text-gray-500">{{ users.length }} utilisateur(s)</span>
        <button @click="openCreateModal" class="btn-primary flex items-center gap-2">
          <UserPlus class="w-4 h-4" /> Ajouter un utilisateur
        </button>
      </div>

      <div class="card overflow-hidden">
        <table class="w-full text-sm">
          <thead>
            <tr class="border-b border-gray-800">
              <th class="text-left px-4 py-3 text-gray-400 font-medium">Utilisateur</th>
              <th class="text-left px-4 py-3 text-gray-400 font-medium">Email</th>
              <th class="text-left px-4 py-3 text-gray-400 font-medium">Statut</th>
              <th class="text-left px-4 py-3 text-gray-400 font-medium">Permissions</th>
              <th class="text-left px-4 py-3 text-gray-400 font-medium">Equipes</th>
              <th class="text-right px-4 py-3 text-gray-400 font-medium">Moniteurs</th>
              <th class="text-right px-4 py-3 text-gray-400 font-medium">Actions</th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="loadingUsers">
              <td colspan="7" class="text-center py-8 text-gray-600">Chargement...</td>
            </tr>
            <tr v-else-if="users.length === 0">
              <td colspan="7" class="text-center py-8 text-gray-600">Aucun utilisateur</td>
            </tr>
            <tr
              v-else
              v-for="user in users"
              :key="user.id"
              class="border-b border-gray-800/50 hover:bg-gray-800/30 transition-colors"
            >
              <!-- Avatar + username -->
              <td class="px-4 py-3">
                <div class="flex items-center gap-3">
                  <div class="w-8 h-8 rounded-full bg-gradient-to-br from-blue-500 to-purple-600 flex items-center justify-center text-white font-bold text-sm flex-shrink-0">
                    {{ user.username[0]?.toUpperCase() }}
                  </div>
                  <div>
                    <div class="text-white font-medium">{{ user.username }}</div>
                    <div v-if="user.full_name" class="text-gray-500 text-xs">{{ user.full_name }}</div>
                  </div>
                </div>
              </td>
              <!-- Email -->
              <td class="px-4 py-3 text-gray-400">{{ user.email }}</td>
              <!-- Statut -->
              <td class="px-4 py-3">
                <span
                  :class="user.is_active ? 'bg-green-900/40 text-green-400 border-green-800' : 'bg-gray-800 text-gray-500 border-gray-700'"
                  class="px-2 py-0.5 rounded text-xs border font-medium"
                >{{ user.is_active ? 'Actif' : 'Inactif' }}</span>
                <span v-if="user.is_superadmin" class="ml-1 px-2 py-0.5 rounded text-xs border bg-purple-900/40 text-purple-400 border-purple-800 font-medium">Admin</span>
              </td>
              <!-- Permissions -->
              <td class="px-4 py-3">
                <span
                  v-if="user.can_create_monitors"
                  class="px-2 py-0.5 rounded text-xs border bg-blue-900/40 text-blue-400 border-blue-800 font-medium"
                >Cree des moniteurs</span>
                <span v-else class="text-gray-600 text-xs">--</span>
              </td>
              <!-- Teams -->
              <td class="px-4 py-3">
                <div class="flex flex-wrap gap-1">
                  <span
                    v-for="tm in userTeamMap[user.id] || []"
                    :key="tm.team_id"
                    class="px-2 py-0.5 rounded text-xs border bg-gray-800 text-gray-300 border-gray-700 font-medium"
                  >{{ tm.team_name }} <span class="text-gray-500">{{ tm.role }}</span></span>
                  <span v-if="!(userTeamMap[user.id] || []).length" class="text-gray-600 text-xs">--</span>
                </div>
              </td>
              <!-- Monitor count -->
              <td class="px-4 py-3 text-right text-gray-400">{{ user.monitor_count }}</td>
              <!-- Actions -->
              <td class="px-4 py-3">
                <div class="flex justify-end gap-2">
                  <button
                    @click="openEditModal(user)"
                    class="p-1.5 text-gray-500 hover:text-blue-400 transition-colors rounded"
                    title="Modifier"
                  >
                    <Pencil class="w-4 h-4" />
                  </button>
                  <button
                    v-if="!user.is_superadmin"
                    @click="confirmDelete(user)"
                    class="p-1.5 text-gray-500 hover:text-red-400 transition-colors rounded"
                    title="Supprimer"
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

    <!-- ===== TEAMS TAB ===== -->
    <div v-if="activeTab === 'teams'">
      <div class="flex justify-between items-center mb-4">
        <span class="text-sm text-gray-500">{{ teams.length }} equipe(s)</span>
        <button @click="openCreateTeamModal" class="btn-primary flex items-center gap-2">
          <Plus class="w-4 h-4" /> Creer une equipe
        </button>
      </div>

      <div v-if="loadingTeams" class="text-center py-8 text-gray-600">Chargement...</div>
      <div v-else-if="teams.length === 0" class="text-center py-16">
        <Users class="w-12 h-12 text-gray-700 mx-auto mb-3" />
        <p class="text-gray-500">Aucune equipe. Creez-en une pour commencer.</p>
      </div>

      <div v-else class="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <div
          v-for="team in teams"
          :key="team.id"
          class="card cursor-pointer hover:border-gray-600 transition-colors"
          @click="openTeamDetail(team)"
        >
          <div class="flex items-center justify-between mb-3">
            <h3 class="text-white font-semibold text-lg">{{ team.name }}</h3>
            <span class="text-xs text-gray-500 bg-gray-800 px-2 py-0.5 rounded font-mono">{{ team.slug }}</span>
          </div>
          <div class="flex items-center gap-2 text-sm text-gray-400">
            <Users class="w-4 h-4" />
            <span>{{ team.member_count }} {{ team.member_count === 1 ? 'membre' : 'membres' }}</span>
          </div>
        </div>
      </div>
    </div>

    <!-- ===== MONITORS TAB ===== -->
    <div v-if="activeTab === 'monitors'">
      <div class="mb-4">
        <span class="text-sm text-gray-500">{{ allMonitors.length }} moniteur(s)</span>
      </div>

      <div class="card overflow-hidden">
        <table class="w-full text-sm">
          <thead>
            <tr class="border-b border-gray-800">
              <th class="text-left px-4 py-3 text-gray-400 font-medium">Proprietaire</th>
              <th class="text-left px-4 py-3 text-gray-400 font-medium">Nom</th>
              <th class="text-left px-4 py-3 text-gray-400 font-medium">Type</th>
              <th class="text-left px-4 py-3 text-gray-400 font-medium">URL</th>
              <th class="text-left px-4 py-3 text-gray-400 font-medium">Statut</th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="loadingMonitors">
              <td colspan="5" class="text-center py-8 text-gray-600">Chargement...</td>
            </tr>
            <tr v-else-if="allMonitors.length === 0">
              <td colspan="5" class="text-center py-8 text-gray-600">Aucun moniteur</td>
            </tr>
            <tr
              v-else
              v-for="monitor in allMonitors"
              :key="monitor.id"
              class="border-b border-gray-800/50 hover:bg-gray-800/30 transition-colors"
            >
              <td class="px-4 py-3">
                <div class="flex items-center gap-2">
                  <div class="w-6 h-6 rounded-full bg-gradient-to-br from-blue-500 to-purple-600 flex items-center justify-center text-white font-bold text-xs flex-shrink-0">
                    {{ monitor.owner_username[0]?.toUpperCase() }}
                  </div>
                  <span class="text-gray-300 text-xs">{{ monitor.owner_username }}</span>
                </div>
              </td>
              <td class="px-4 py-3 text-white font-medium">{{ monitor.name }}</td>
              <td class="px-4 py-3">
                <span class="px-2 py-0.5 rounded text-xs border bg-gray-800 text-gray-400 border-gray-700 font-mono">{{ monitor.check_type }}</span>
              </td>
              <td class="px-4 py-3 text-gray-500 text-xs max-w-xs truncate">{{ monitor.url }}</td>
              <td class="px-4 py-3">
                <span
                  :class="monitor.enabled ? 'bg-green-900/40 text-green-400 border-green-800' : 'bg-gray-800 text-gray-500 border-gray-700'"
                  class="px-2 py-0.5 rounded text-xs border font-medium"
                >{{ monitor.enabled ? 'Actif' : 'Desactive' }}</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- ===== PROBE GROUPS TAB ===== -->
    <div v-if="activeTab === 'probe-groups'">
      <div class="flex justify-between items-center mb-4">
        <span class="text-sm text-gray-500">{{ probeGroups.length }} groupe(s)</span>
        <button @click="openCreateGroupModal" class="btn-primary flex items-center gap-2">
          <Plus class="w-4 h-4" /> Creer un groupe
        </button>
      </div>

      <div v-if="loadingGroups" class="text-center py-8 text-gray-600">Chargement...</div>
      <div v-else-if="probeGroups.length === 0" class="text-center py-8 text-gray-600">Aucun groupe de sondes</div>
      <div v-else class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        <div
          v-for="group in probeGroups"
          :key="group.id"
          class="card p-4 flex flex-col gap-3"
        >
          <div class="flex items-start justify-between gap-2">
            <div>
              <div class="text-white font-semibold">{{ group.name }}</div>
              <div v-if="group.description" class="text-gray-500 text-xs mt-0.5">{{ group.description }}</div>
            </div>
            <div class="flex gap-1 flex-shrink-0">
              <button @click="openEditGroupModal(group)" class="p-1.5 text-gray-500 hover:text-blue-400 transition-colors rounded" title="Modifier">
                <Pencil class="w-4 h-4" />
              </button>
              <button @click="confirmDeleteGroup(group)" class="p-1.5 text-gray-500 hover:text-red-400 transition-colors rounded" title="Supprimer">
                <Trash2 class="w-4 h-4" />
              </button>
            </div>
          </div>
          <div class="flex gap-3 text-xs text-gray-500">
            <span class="px-2 py-0.5 rounded bg-gray-800 border border-gray-700">{{ group.probe_ids.length }} sonde(s)</span>
            <span class="px-2 py-0.5 rounded bg-gray-800 border border-gray-700">{{ group.user_ids.length }} utilisateur(s)</span>
          </div>
          <button @click="openGroupDetailModal(group)" class="text-xs text-blue-400 hover:text-blue-300 transition-colors text-left">
            Gerer les acces &rarr;
          </button>
        </div>
      </div>
    </div>

    <!-- ===== OIDC TAB ===== -->
    <div v-if="activeTab === 'oidc'">
      <div v-if="oidcLoading" class="text-center py-8 text-gray-600">Chargement...</div>
      <div v-else class="max-w-xl">
        <div v-if="oidcSettings?.source === 'env'" class="mb-4 px-3 py-2 rounded-lg bg-yellow-900/30 border border-yellow-700/50 text-yellow-400 text-sm">
          Configuration actuelle lue depuis les variables d'environnement. Enregistrer ici creera une configuration en base qui prend le dessus.
        </div>

        <form @submit.prevent="saveOidcSettings" class="space-y-5">
          <!-- Enabled toggle -->
          <div class="flex items-center justify-between py-3 px-4 rounded-lg bg-gray-800/60 border border-gray-700/50">
            <div>
              <div class="text-sm text-gray-300 font-medium">Activer le SSO (OIDC)</div>
              <div class="text-xs text-gray-500 mt-0.5">Affiche le bouton "Connexion SSO" sur la page de login</div>
            </div>
            <button
              type="button"
              @click="oidcForm.oidc_enabled = !oidcForm.oidc_enabled"
              :class="oidcForm.oidc_enabled ? 'bg-blue-600' : 'bg-gray-700'"
              class="relative w-11 h-6 rounded-full transition-colors flex-shrink-0"
            >
              <span
                :class="oidcForm.oidc_enabled ? 'translate-x-5' : 'translate-x-1'"
                class="absolute top-0.5 w-5 h-5 bg-white rounded-full shadow transition-transform"
              />
            </button>
          </div>

          <div>
            <label class="block text-sm text-gray-400 mb-1">Issuer URL <span class="text-gray-600">(ex: https://accounts.google.com)</span></label>
            <input v-model="oidcForm.oidc_issuer_url" type="url" class="input w-full" placeholder="https://accounts.example.com" />
          </div>

          <div>
            <label class="block text-sm text-gray-400 mb-1">Client ID</label>
            <input v-model="oidcForm.oidc_client_id" type="text" class="input w-full" />
          </div>

          <div>
            <label class="block text-sm text-gray-400 mb-1">
              Client Secret
              <span v-if="oidcSettings?.oidc_client_secret_set" class="ml-1 text-xs text-green-500">(secret enregistre -- laisser vide pour conserver)</span>
              <span v-else class="ml-1 text-xs text-gray-600">(non defini)</span>
            </label>
            <input v-model="oidcForm.oidc_client_secret" type="password" class="input w-full" autocomplete="new-password" placeholder="••••••••" />
          </div>

          <div>
            <label class="block text-sm text-gray-400 mb-1">
              Redirect URI
              <span class="text-gray-600">(laissez vide pour auto-detection)</span>
            </label>
            <input v-model="oidcForm.oidc_redirect_uri" type="url" class="input w-full" placeholder="https://app.example.com/api/v1/auth/oidc/callback" />
          </div>

          <div>
            <label class="block text-sm text-gray-400 mb-1">Scopes</label>
            <input v-model="oidcForm.oidc_scopes" type="text" class="input w-full" />
          </div>

          <!-- Auto-provision toggle -->
          <div class="flex items-center justify-between py-3 px-4 rounded-lg bg-gray-800/60 border border-gray-700/50">
            <div>
              <div class="text-sm text-gray-300 font-medium">Auto-provisioning</div>
              <div class="text-xs text-gray-500 mt-0.5">Creer automatiquement un compte local au premier login SSO</div>
            </div>
            <button
              type="button"
              @click="oidcForm.oidc_auto_provision = !oidcForm.oidc_auto_provision"
              :class="oidcForm.oidc_auto_provision ? 'bg-blue-600' : 'bg-gray-700'"
              class="relative w-11 h-6 rounded-full transition-colors flex-shrink-0"
            >
              <span
                :class="oidcForm.oidc_auto_provision ? 'translate-x-5' : 'translate-x-1'"
                class="absolute top-0.5 w-5 h-5 bg-white rounded-full shadow transition-transform"
              />
            </button>
          </div>

          <div v-if="oidcError" class="text-red-400 text-sm">{{ oidcError }}</div>
          <div v-if="oidcSuccess" class="text-green-400 text-sm">Configuration sauvegardee.</div>

          <div class="flex justify-end">
            <button type="submit" class="btn-primary" :disabled="oidcSaving">
              {{ oidcSaving ? 'Enregistrement...' : 'Enregistrer' }}
            </button>
          </div>
        </form>
      </div>
    </div>

    <!-- ===== MODAL CREATE GROUP ===== -->
    <Teleport to="body">
      <div v-if="showCreateGroupModal" class="fixed inset-0 bg-black/60 backdrop-blur-sm z-50 flex items-center justify-center p-4" @click.self="showCreateGroupModal = false">
        <div class="card w-full max-w-md" @click.stop>
          <div class="flex justify-between items-center mb-6">
            <h2 class="text-lg font-semibold text-white">Creer un groupe de sondes</h2>
            <button @click="showCreateGroupModal = false" class="text-gray-500 hover:text-gray-300"><X class="w-5 h-5" /></button>
          </div>
          <form @submit.prevent="submitCreateGroup" class="space-y-4">
            <div>
              <label class="block text-sm text-gray-400 mb-1">Nom *</label>
              <input v-model="groupForm.name" type="text" class="input w-full" required maxlength="255" />
            </div>
            <div>
              <label class="block text-sm text-gray-400 mb-1">Description</label>
              <input v-model="groupForm.description" type="text" class="input w-full" />
            </div>
            <div v-if="groupError" class="text-red-400 text-sm">{{ groupError }}</div>
            <div class="flex justify-end gap-3 pt-2">
              <button type="button" @click="showCreateGroupModal = false" class="btn-secondary">Annuler</button>
              <button type="submit" class="btn-primary" :disabled="submitting">{{ submitting ? 'Creation...' : 'Creer' }}</button>
            </div>
          </form>
        </div>
      </div>
    </Teleport>

    <!-- ===== MODAL EDIT GROUP ===== -->
    <Teleport to="body">
      <div v-if="showEditGroupModal && editingGroup" class="fixed inset-0 bg-black/60 backdrop-blur-sm z-50 flex items-center justify-center p-4" @click.self="showEditGroupModal = false">
        <div class="card w-full max-w-md" @click.stop>
          <div class="flex justify-between items-center mb-6">
            <h2 class="text-lg font-semibold text-white">Modifier -- {{ editingGroup.name }}</h2>
            <button @click="showEditGroupModal = false" class="text-gray-500 hover:text-gray-300"><X class="w-5 h-5" /></button>
          </div>
          <form @submit.prevent="submitEditGroup" class="space-y-4">
            <div>
              <label class="block text-sm text-gray-400 mb-1">Nom</label>
              <input v-model="groupForm.name" type="text" class="input w-full" maxlength="255" />
            </div>
            <div>
              <label class="block text-sm text-gray-400 mb-1">Description</label>
              <input v-model="groupForm.description" type="text" class="input w-full" />
            </div>
            <div v-if="groupError" class="text-red-400 text-sm">{{ groupError }}</div>
            <div class="flex justify-end gap-3 pt-2">
              <button type="button" @click="showEditGroupModal = false" class="btn-secondary">Annuler</button>
              <button type="submit" class="btn-primary" :disabled="submitting">{{ submitting ? 'Enregistrement...' : 'Enregistrer' }}</button>
            </div>
          </form>
        </div>
      </div>
    </Teleport>

    <!-- ===== MODAL CONFIRM DELETE GROUP ===== -->
    <Teleport to="body">
      <div v-if="showDeleteGroupModal && deletingGroup" class="fixed inset-0 bg-black/60 backdrop-blur-sm z-50 flex items-center justify-center p-4" @click.self="showDeleteGroupModal = false">
        <div class="card w-full max-w-sm" @click.stop>
          <h2 class="text-lg font-semibold text-white mb-3">Confirmer la suppression</h2>
          <p class="text-gray-400 text-sm mb-6">
            Supprimer le groupe <strong class="text-white">{{ deletingGroup.name }}</strong> ?
            Cette action est irreversible.
          </p>
          <div class="flex justify-end gap-3">
            <button @click="showDeleteGroupModal = false" class="btn-secondary">Annuler</button>
            <button @click="executeDeleteGroup" class="btn-danger" :disabled="submitting">{{ submitting ? 'Suppression...' : 'Supprimer' }}</button>
          </div>
        </div>
      </div>
    </Teleport>

    <!-- ===== MODAL GROUP DETAIL (manage probes & users) ===== -->
    <Teleport to="body">
      <div v-if="showGroupDetailModal && detailGroup" class="fixed inset-0 bg-black/60 backdrop-blur-sm z-50 flex items-center justify-center p-4" @click.self="showGroupDetailModal = false">
        <div class="card w-full max-w-2xl max-h-[80vh] overflow-y-auto" @click.stop>
          <div class="flex justify-between items-center mb-6">
            <h2 class="text-lg font-semibold text-white">{{ detailGroup.name }}</h2>
            <button @click="showGroupDetailModal = false" class="text-gray-500 hover:text-gray-300"><X class="w-5 h-5" /></button>
          </div>

          <!-- Probes section -->
          <div class="mb-6">
            <div class="flex items-center justify-between mb-3">
              <h3 class="text-sm font-medium text-gray-300">Sondes</h3>
            </div>
            <div v-if="detailGroup.probe_ids.length === 0" class="text-gray-600 text-sm">Aucune sonde dans ce groupe.</div>
            <div v-else class="space-y-1 mb-3">
              <div
                v-for="probeId in detailGroup.probe_ids"
                :key="probeId"
                class="flex items-center justify-between py-1.5 px-3 rounded bg-gray-800/60 border border-gray-700/50"
              >
                <span class="text-gray-300 text-sm">{{ probeNameById(probeId) }}</span>
                <button @click="removeProbeFromDetailGroup(probeId)" class="text-gray-600 hover:text-red-400 transition-colors" :disabled="submitting">
                  <X class="w-4 h-4" />
                </button>
              </div>
            </div>
            <!-- Add probes -->
            <div class="flex gap-2 mt-2">
              <select v-model="addProbeSelection" class="input flex-1 text-sm">
                <option value="">-- Ajouter une sonde --</option>
                <option
                  v-for="probe in availableProbesForGroup"
                  :key="probe.id"
                  :value="probe.id"
                >{{ probe.name }} ({{ probe.location_name }})</option>
              </select>
              <button @click="addProbeToDetailGroup" class="btn-primary text-sm" :disabled="!addProbeSelection || submitting">Ajouter</button>
            </div>
          </div>

          <!-- Users section -->
          <div>
            <div class="flex items-center justify-between mb-3">
              <h3 class="text-sm font-medium text-gray-300">Utilisateurs avec acces</h3>
            </div>
            <div v-if="detailGroup.user_ids.length === 0" class="text-gray-600 text-sm">Aucun utilisateur.</div>
            <div v-else class="space-y-1 mb-3">
              <div
                v-for="userId in detailGroup.user_ids"
                :key="userId"
                class="flex items-center justify-between py-1.5 px-3 rounded bg-gray-800/60 border border-gray-700/50"
              >
                <span class="text-gray-300 text-sm">{{ userNameById(userId) }}</span>
                <button @click="revokeUserFromDetailGroup(userId)" class="text-gray-600 hover:text-red-400 transition-colors" :disabled="submitting">
                  <X class="w-4 h-4" />
                </button>
              </div>
            </div>
            <!-- Add user -->
            <div class="flex gap-2 mt-2">
              <select v-model="addUserSelection" class="input flex-1 text-sm">
                <option value="">-- Accorder l'acces a un utilisateur --</option>
                <option
                  v-for="user in availableUsersForGroup"
                  :key="user.id"
                  :value="user.id"
                >{{ user.username }}</option>
              </select>
              <button @click="grantUserToDetailGroup" class="btn-primary text-sm" :disabled="!addUserSelection || submitting">Ajouter</button>
            </div>
          </div>

          <div v-if="detailError" class="mt-4 text-red-400 text-sm">{{ detailError }}</div>
        </div>
      </div>
    </Teleport>

    <!-- ===== MODAL CREATE USER ===== -->
    <Teleport to="body">
      <div v-if="showCreateModal" class="fixed inset-0 bg-black/60 backdrop-blur-sm z-50 flex items-center justify-center p-4" @click.self="showCreateModal = false">
        <div class="card w-full max-w-md" @click.stop>
          <div class="flex justify-between items-center mb-6">
            <h2 class="text-lg font-semibold text-white">Ajouter un utilisateur</h2>
            <button @click="showCreateModal = false" class="text-gray-500 hover:text-gray-300">
              <X class="w-5 h-5" />
            </button>
          </div>

          <form @submit.prevent="submitCreate" class="space-y-4">
            <div>
              <label class="block text-sm text-gray-400 mb-1">Email *</label>
              <input v-model="createForm.email" type="email" class="input w-full" required />
            </div>
            <div>
              <label class="block text-sm text-gray-400 mb-1">Nom d'utilisateur (optionnel)</label>
              <input v-model="createForm.username" type="text" class="input w-full" placeholder="Genere automatiquement" />
            </div>
            <div>
              <label class="block text-sm text-gray-400 mb-1">Nom complet</label>
              <input v-model="createForm.full_name" type="text" class="input w-full" />
            </div>
            <div>
              <label class="block text-sm text-gray-400 mb-1">Mot de passe *</label>
              <input v-model="createForm.password" type="password" class="input w-full" required minlength="8" />
            </div>
            <div class="flex items-center justify-between py-2 px-3 rounded-lg bg-gray-800/60 border border-gray-700/50">
              <div>
                <div class="text-sm text-gray-300 font-medium">Peut creer des moniteurs</div>
                <div class="text-xs text-gray-500">Autorise cet utilisateur a creer des moniteurs</div>
              </div>
              <button
                type="button"
                @click="createForm.can_create_monitors = !createForm.can_create_monitors"
                :class="createForm.can_create_monitors ? 'bg-blue-600' : 'bg-gray-700'"
                class="relative w-11 h-6 rounded-full transition-colors flex-shrink-0"
              >
                <span
                  :class="createForm.can_create_monitors ? 'translate-x-5' : 'translate-x-1'"
                  class="absolute top-0.5 w-5 h-5 bg-white rounded-full shadow transition-transform"
                />
              </button>
            </div>

            <div class="flex items-center justify-between py-2 px-3 rounded-lg bg-gray-800/60 border border-gray-700/50">
              <div>
                <div class="text-sm text-gray-300 font-medium">Administrateur</div>
                <div class="text-xs text-gray-500">Acces complet a l'administration de la plateforme</div>
              </div>
              <button
                type="button"
                @click="createForm.is_superadmin = !createForm.is_superadmin"
                :class="createForm.is_superadmin ? 'bg-purple-600' : 'bg-gray-700'"
                class="relative w-11 h-6 rounded-full transition-colors flex-shrink-0"
              >
                <span
                  :class="createForm.is_superadmin ? 'translate-x-5' : 'translate-x-1'"
                  class="absolute top-0.5 w-5 h-5 bg-white rounded-full shadow transition-transform"
                />
              </button>
            </div>

            <div v-if="createError" class="text-red-400 text-sm">{{ createError }}</div>

            <div class="flex justify-end gap-3 pt-2">
              <button type="button" @click="showCreateModal = false" class="btn-secondary">Annuler</button>
              <button type="submit" class="btn-primary" :disabled="submitting">
                {{ submitting ? 'Creation...' : 'Creer' }}
              </button>
            </div>
          </form>
        </div>
      </div>
    </Teleport>

    <!-- ===== MODAL EDIT USER ===== -->
    <Teleport to="body">
      <div v-if="showEditModal && editingUser" class="fixed inset-0 bg-black/60 backdrop-blur-sm z-50 flex items-center justify-center p-4" @click.self="showEditModal = false">
        <div class="card w-full max-w-md" @click.stop>
          <div class="flex justify-between items-center mb-6">
            <h2 class="text-lg font-semibold text-white">Modifier -- {{ editingUser.username }}</h2>
            <button @click="showEditModal = false" class="text-gray-500 hover:text-gray-300">
              <X class="w-5 h-5" />
            </button>
          </div>

          <form @submit.prevent="submitEdit" class="space-y-4">
            <div>
              <label class="block text-sm text-gray-400 mb-1">Email</label>
              <input v-model="editForm.email" type="email" class="input w-full" />
            </div>
            <div>
              <label class="block text-sm text-gray-400 mb-1">Nom complet</label>
              <input v-model="editForm.full_name" type="text" class="input w-full" />
            </div>
            <div>
              <label class="block text-sm text-gray-400 mb-1">Nouveau mot de passe (laisser vide pour ne pas changer)</label>
              <input v-model="editForm.password" type="password" class="input w-full" minlength="8" />
            </div>

            <div class="flex items-center justify-between py-2 px-3 rounded-lg bg-gray-800/60 border border-gray-700/50">
              <div>
                <div class="text-sm text-gray-300 font-medium">Compte actif</div>
              </div>
              <button
                type="button"
                @click="editForm.is_active = !editForm.is_active"
                :class="editForm.is_active ? 'bg-green-600' : 'bg-gray-700'"
                class="relative w-11 h-6 rounded-full transition-colors flex-shrink-0"
              >
                <span
                  :class="editForm.is_active ? 'translate-x-5' : 'translate-x-1'"
                  class="absolute top-0.5 w-5 h-5 bg-white rounded-full shadow transition-transform"
                />
              </button>
            </div>

            <div class="flex items-center justify-between py-2 px-3 rounded-lg bg-gray-800/60 border border-gray-700/50">
              <div>
                <div class="text-sm text-gray-300 font-medium">Peut creer des moniteurs</div>
              </div>
              <button
                type="button"
                @click="editForm.can_create_monitors = !editForm.can_create_monitors"
                :class="editForm.can_create_monitors ? 'bg-blue-600' : 'bg-gray-700'"
                class="relative w-11 h-6 rounded-full transition-colors flex-shrink-0"
              >
                <span
                  :class="editForm.can_create_monitors ? 'translate-x-5' : 'translate-x-1'"
                  class="absolute top-0.5 w-5 h-5 bg-white rounded-full shadow transition-transform"
                />
              </button>
            </div>

            <div class="flex items-center justify-between py-2 px-3 rounded-lg bg-gray-800/60 border border-gray-700/50">
              <div>
                <div class="text-sm text-gray-300 font-medium">Administrateur</div>
                <div class="text-xs text-gray-500">Acces complet a l'administration</div>
              </div>
              <button
                type="button"
                @click="editForm.is_superadmin = !editForm.is_superadmin"
                :class="editForm.is_superadmin ? 'bg-purple-600' : 'bg-gray-700'"
                class="relative w-11 h-6 rounded-full transition-colors flex-shrink-0"
              >
                <span
                  :class="editForm.is_superadmin ? 'translate-x-5' : 'translate-x-1'"
                  class="absolute top-0.5 w-5 h-5 bg-white rounded-full shadow transition-transform"
                />
              </button>
            </div>

            <div v-if="editError" class="text-red-400 text-sm">{{ editError }}</div>

            <div class="flex justify-end gap-3 pt-2">
              <button type="button" @click="showEditModal = false" class="btn-secondary">Annuler</button>
              <button type="submit" class="btn-primary" :disabled="submitting">
                {{ submitting ? 'Enregistrement...' : 'Enregistrer' }}
              </button>
            </div>
          </form>
        </div>
      </div>
    </Teleport>

    <!-- ===== MODAL CONFIRM DELETE USER ===== -->
    <Teleport to="body">
      <div v-if="showDeleteModal && deletingUser" class="fixed inset-0 bg-black/60 backdrop-blur-sm z-50 flex items-center justify-center p-4" @click.self="showDeleteModal = false">
        <div class="card w-full max-w-sm" @click.stop>
          <h2 class="text-lg font-semibold text-white mb-3">Confirmer la suppression</h2>
          <p class="text-gray-400 text-sm mb-6">
            Supprimer l'utilisateur <strong class="text-white">{{ deletingUser.username }}</strong> ?
            Cette action est irreversible.
          </p>
          <div class="flex justify-end gap-3">
            <button @click="showDeleteModal = false" class="btn-secondary">Annuler</button>
            <button @click="executeDelete" class="btn-danger" :disabled="submitting">
              {{ submitting ? 'Suppression...' : 'Supprimer' }}
            </button>
          </div>
        </div>
      </div>
    </Teleport>

    <!-- ===== MODAL CREATE TEAM ===== -->
    <Teleport to="body">
      <div v-if="showCreateTeamModal" class="fixed inset-0 bg-black/60 backdrop-blur-sm z-50 flex items-center justify-center p-4" @click.self="showCreateTeamModal = false">
        <div class="card w-full max-w-md" @click.stop>
          <div class="flex justify-between items-center mb-6">
            <h2 class="text-lg font-semibold text-white">Creer une equipe</h2>
            <button @click="showCreateTeamModal = false" class="text-gray-500 hover:text-gray-300"><X class="w-5 h-5" /></button>
          </div>
          <form @submit.prevent="submitCreateTeam" class="space-y-4">
            <div>
              <label class="block text-sm text-gray-400 mb-1">Nom *</label>
              <input v-model="teamCreateForm.name" type="text" class="input w-full" required maxlength="200" />
            </div>
            <div>
              <label class="block text-sm text-gray-400 mb-1">Slug (optionnel)</label>
              <input v-model="teamCreateForm.slug" type="text" class="input w-full" placeholder="genere automatiquement" pattern="^[a-z0-9][a-z0-9-]*$" />
            </div>
            <div v-if="teamError" class="text-red-400 text-sm">{{ teamError }}</div>
            <div class="flex justify-end gap-3 pt-2">
              <button type="button" @click="showCreateTeamModal = false" class="btn-secondary">Annuler</button>
              <button type="submit" class="btn-primary" :disabled="submitting">{{ submitting ? 'Creation...' : 'Creer' }}</button>
            </div>
          </form>
        </div>
      </div>
    </Teleport>

    <!-- ===== MODAL TEAM DETAIL ===== -->
    <Teleport to="body">
      <div v-if="showTeamDetailModal && selectedTeam" class="fixed inset-0 bg-black/60 backdrop-blur-sm z-50 flex items-center justify-center p-4" @click.self="showTeamDetailModal = false">
        <div class="card w-full max-w-2xl max-h-[85vh] overflow-y-auto" @click.stop>

          <!-- Header -->
          <div class="flex justify-between items-center mb-6">
            <div>
              <h2 class="text-lg font-semibold text-white">{{ selectedTeam.name }}</h2>
              <span class="text-xs text-gray-500 font-mono">{{ selectedTeam.slug }}</span>
            </div>
            <div class="flex items-center gap-2">
              <button @click="openEditTeamModal" class="p-1.5 text-gray-500 hover:text-blue-400 transition-colors rounded" title="Modifier">
                <Pencil class="w-4 h-4" />
              </button>
              <button @click="confirmDeleteTeam" class="p-1.5 text-gray-500 hover:text-red-400 transition-colors rounded" title="Supprimer">
                <Trash2 class="w-4 h-4" />
              </button>
              <button @click="showTeamDetailModal = false" class="text-gray-500 hover:text-gray-300">
                <X class="w-5 h-5" />
              </button>
            </div>
          </div>

          <!-- Members section -->
          <div class="mb-4 flex items-center justify-between">
            <h3 class="text-sm font-medium text-gray-400">Membres ({{ teamMembers.length }})</h3>
            <button @click="showTeamAddMember = !showTeamAddMember" class="btn-primary text-xs flex items-center gap-1 px-3 py-1.5">
              <UserPlus class="w-3.5 h-3.5" /> Ajouter un membre
            </button>
          </div>

          <!-- Add member inline form -->
          <div v-if="showTeamAddMember" class="mb-4 p-3 rounded-lg bg-gray-800/60 border border-gray-700/50 space-y-3">
            <div>
              <label class="block text-xs text-gray-400 mb-1">Utilisateur</label>
              <select v-model="teamAddMemberForm.user_id" class="input w-full text-sm">
                <option value="">-- Selectionner un utilisateur --</option>
                <option
                  v-for="u in availableUsersForTeam"
                  :key="u.id"
                  :value="u.id"
                >{{ u.username }} ({{ u.email }})</option>
              </select>
            </div>
            <div>
              <label class="block text-xs text-gray-400 mb-1">Role</label>
              <select v-model="teamAddMemberForm.role" class="input w-full text-sm">
                <option value="viewer">Viewer</option>
                <option value="editor">Editor</option>
                <option value="admin">Admin</option>
                <option value="owner">Owner</option>
              </select>
            </div>
            <div v-if="teamMemberError" class="text-red-400 text-xs">{{ teamMemberError }}</div>
            <div class="flex justify-end gap-2">
              <button @click="showTeamAddMember = false" class="btn-secondary text-xs px-3 py-1">Annuler</button>
              <button @click="submitTeamAddMember" class="btn-primary text-xs px-3 py-1" :disabled="!teamAddMemberForm.user_id || submitting">Ajouter</button>
            </div>
          </div>

          <!-- Members table -->
          <div class="card overflow-hidden !p-0">
            <table class="w-full text-sm">
              <thead>
                <tr class="border-b border-gray-800">
                  <th class="text-left px-4 py-2.5 text-gray-400 font-medium">Utilisateur</th>
                  <th class="text-left px-4 py-2.5 text-gray-400 font-medium">Role</th>
                  <th class="text-right px-4 py-2.5 text-gray-400 font-medium">Actions</th>
                </tr>
              </thead>
              <tbody>
                <tr v-if="loadingTeamMembers">
                  <td colspan="3" class="text-center py-6 text-gray-600">Chargement...</td>
                </tr>
                <tr v-else-if="teamMembers.length === 0">
                  <td colspan="3" class="text-center py-6 text-gray-600">Aucun membre</td>
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
                      title="Retirer"
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
            <h2 class="text-lg font-semibold text-white">Modifier l'equipe</h2>
            <button @click="showEditTeamModal = false" class="text-gray-500 hover:text-gray-300"><X class="w-5 h-5" /></button>
          </div>
          <form @submit.prevent="submitEditTeam" class="space-y-4">
            <div>
              <label class="block text-sm text-gray-400 mb-1">Nom</label>
              <input v-model="teamEditForm.name" type="text" class="input w-full" required maxlength="200" />
            </div>
            <div v-if="teamError" class="text-red-400 text-sm">{{ teamError }}</div>
            <div class="flex justify-end gap-3 pt-2">
              <button type="button" @click="showEditTeamModal = false" class="btn-secondary">Annuler</button>
              <button type="submit" class="btn-primary" :disabled="submitting">{{ submitting ? 'Enregistrement...' : 'Enregistrer' }}</button>
            </div>
          </form>
        </div>
      </div>
    </Teleport>

    <!-- ===== MODAL CONFIRM DELETE TEAM / REMOVE MEMBER ===== -->
    <Teleport to="body">
      <div v-if="showTeamDeleteModal" class="fixed inset-0 bg-black/60 backdrop-blur-sm z-50 flex items-center justify-center p-4" @click.self="showTeamDeleteModal = false">
        <div class="card w-full max-w-sm" @click.stop>
          <h2 class="text-lg font-semibold text-white mb-3">Confirmer</h2>
          <p class="text-gray-400 text-sm mb-6">{{ teamDeletePrefix }} <strong class="text-white">{{ teamDeleteTarget }}</strong> {{ teamDeleteSuffix }}</p>
          <div class="flex justify-end gap-3">
            <button @click="showTeamDeleteModal = false" class="btn-secondary">Annuler</button>
            <button @click="executeTeamDelete" class="bg-red-600 hover:bg-red-500 text-white px-4 py-2 rounded-lg text-sm font-medium transition-colors" :disabled="submitting">
              Confirmer
            </button>
          </div>
        </div>
      </div>
    </Teleport>

  </div>
</template>

<script setup>
import { ref, onMounted, watch, computed } from 'vue'
import { Pencil, Trash2, UserPlus, X, Plus, Users } from 'lucide-vue-next'
import { adminApi } from '../api/admin'
import { probesApi } from '../api/probes'
import { teamsApi } from '../api/teams'

const tabs = [
  { id: 'users', label: 'Utilisateurs' },
  { id: 'teams', label: 'Equipes' },
  { id: 'monitors', label: 'Moniteurs' },
  { id: 'probe-groups', label: 'Groupes de sondes' },
  { id: 'oidc', label: 'SSO / OIDC' },
]
const activeTab = ref('users')

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

// ─── Create user ────────────────────────────────────────────────────────────
const showCreateModal = ref(false)
const submitting = ref(false)
const createError = ref('')
const createForm = ref({
  email: '',
  username: '',
  full_name: '',
  password: '',
  can_create_monitors: false,
  is_superadmin: false,
})

function openCreateModal() {
  createForm.value = { email: '', username: '', full_name: '', password: '', can_create_monitors: false, is_superadmin: false }
  createError.value = ''
  showCreateModal.value = true
}

async function submitCreate() {
  submitting.value = true
  createError.value = ''
  try {
    const payload = { ...createForm.value }
    if (!payload.username) delete payload.username
    if (!payload.full_name) delete payload.full_name
    await adminApi.createUser(payload)
    showCreateModal.value = false
    await loadUsers()
  } catch (e) {
    createError.value = e.response?.data?.detail || 'Erreur lors de la creation'
  } finally {
    submitting.value = false
  }
}

// ─── Edit user ──────────────────────────────────────────────────────────────
const showEditModal = ref(false)
const editingUser = ref(null)
const editError = ref('')
const editForm = ref({
  email: '',
  full_name: '',
  password: '',
  is_active: true,
  can_create_monitors: false,
  is_superadmin: false,
})

function openEditModal(user) {
  editingUser.value = user
  editForm.value = {
    email: user.email,
    full_name: user.full_name || '',
    password: '',
    is_active: user.is_active,
    can_create_monitors: user.can_create_monitors,
    is_superadmin: user.is_superadmin,
  }
  editError.value = ''
  showEditModal.value = true
}

async function submitEdit() {
  submitting.value = true
  editError.value = ''
  try {
    const payload = { ...editForm.value }
    if (!payload.password) delete payload.password
    if (!payload.full_name) delete payload.full_name
    await adminApi.updateUser(editingUser.value.id, payload)
    showEditModal.value = false
    await loadUsers()
  } catch (e) {
    editError.value = e.response?.data?.detail || 'Erreur lors de la modification'
  } finally {
    submitting.value = false
  }
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
const teamMembers = ref([])
const loadingTeamMembers = ref(false)
const selectedTeam = ref(null)
const showTeamDetailModal = ref(false)
const showCreateTeamModal = ref(false)
const showEditTeamModal = ref(false)
const showTeamDeleteModal = ref(false)
const showTeamAddMember = ref(false)
const teamError = ref('')
const teamMemberError = ref('')
const teamDeletePrefix = ref('')
const teamDeleteTarget = ref('')
const teamDeleteSuffix = ref('')
let pendingTeamDeleteAction = null

const teamCreateForm = ref({ name: '', slug: '' })
const teamEditForm = ref({ name: '' })
const teamAddMemberForm = ref({ user_id: '', role: 'editor' })

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

const availableUsersForTeam = computed(() => {
  const memberIds = new Set(teamMembers.value.map(m => m.user_id))
  return users.value.filter(u => !memberIds.has(u.id))
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

function openCreateTeamModal() {
  teamCreateForm.value = { name: '', slug: '' }
  teamError.value = ''
  showCreateTeamModal.value = true
}

async function submitCreateTeam() {
  submitting.value = true
  teamError.value = ''
  try {
    const payload = { ...teamCreateForm.value }
    if (!payload.slug) delete payload.slug
    await teamsApi.create(payload)
    showCreateTeamModal.value = false
    await loadTeams()
  } catch (e) {
    teamError.value = e.response?.data?.detail || 'Erreur'
  } finally {
    submitting.value = false
  }
}

async function openTeamDetail(team) {
  selectedTeam.value = team
  showTeamDetailModal.value = true
  showTeamAddMember.value = false
  teamMemberError.value = ''
  await loadTeamMembers(team.id)
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
    await teamsApi.addMember(selectedTeam.value.id, teamAddMemberForm.value)
    teamAddMemberForm.value = { user_id: '', role: 'editor' }
    showTeamAddMember.value = false
    await loadTeamMembers(selectedTeam.value.id)
    await loadTeams()
  } catch (e) {
    teamMemberError.value = e.response?.data?.detail || 'Erreur'
  } finally {
    submitting.value = false
  }
}

async function changeTeamMemberRole(member, newRole) {
  try {
    await teamsApi.updateMember(selectedTeam.value.id, member.user_id, { role: newRole })
    await loadTeamMembers(selectedTeam.value.id)
    await loadTeams()
  } catch (e) {
    alert(e.response?.data?.detail || 'Erreur lors du changement de role')
    await loadTeamMembers(selectedTeam.value.id)
  }
}

function confirmRemoveTeamMember(member) {
  teamDeletePrefix.value = 'Retirer'
  teamDeleteTarget.value = member.username
  teamDeleteSuffix.value = "de l'equipe ?"
  pendingTeamDeleteAction = async () => {
    await teamsApi.removeMember(selectedTeam.value.id, member.user_id)
    await loadTeamMembers(selectedTeam.value.id)
    await loadTeams()
  }
  showTeamDeleteModal.value = true
}

function confirmDeleteTeam() {
  teamDeletePrefix.value = "Supprimer l'equipe"
  teamDeleteTarget.value = selectedTeam.value.name
  teamDeleteSuffix.value = '? Cette action est irreversible.'
  pendingTeamDeleteAction = async () => {
    await teamsApi.delete(selectedTeam.value.id)
    showTeamDetailModal.value = false
    selectedTeam.value = null
    await loadTeams()
  }
  showTeamDeleteModal.value = true
}

async function executeTeamDelete() {
  submitting.value = true
  try {
    await pendingTeamDeleteAction()
    showTeamDeleteModal.value = false
  } catch (e) {
    alert(e.response?.data?.detail || 'Erreur')
  } finally {
    submitting.value = false
  }
}

function openEditTeamModal() {
  teamEditForm.value = { name: selectedTeam.value.name }
  teamError.value = ''
  showEditTeamModal.value = true
}

async function submitEditTeam() {
  submitting.value = true
  teamError.value = ''
  try {
    await teamsApi.update(selectedTeam.value.id, teamEditForm.value)
    showEditTeamModal.value = false
    selectedTeam.value.name = teamEditForm.value.name
    await loadTeams()
  } catch (e) {
    teamError.value = e.response?.data?.detail || 'Erreur'
  } finally {
    submitting.value = false
  }
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
    const { data } = await probesApi.list()
    allProbes.value = data
  } catch (_) {
    // ignore
  }
}

function probeNameById(probeId) {
  const p = allProbes.value.find(p => p.id === probeId)
  return p ? `${p.name} (${p.location_name})` : probeId
}

function userNameById(userId) {
  const u = users.value.find(u => u.id === userId)
  return u ? u.username : userId
}

// Create group
const showCreateGroupModal = ref(false)
const groupForm = ref({ name: '', description: '' })
const groupError = ref('')

function openCreateGroupModal() {
  groupForm.value = { name: '', description: '' }
  groupError.value = ''
  showCreateGroupModal.value = true
}

async function submitCreateGroup() {
  submitting.value = true
  groupError.value = ''
  try {
    const payload = { name: groupForm.value.name }
    if (groupForm.value.description) payload.description = groupForm.value.description
    await adminApi.createProbeGroup(payload)
    showCreateGroupModal.value = false
    await loadProbeGroups()
  } catch (e) {
    groupError.value = e.response?.data?.detail || 'Erreur lors de la creation'
  } finally {
    submitting.value = false
  }
}

// Edit group
const showEditGroupModal = ref(false)
const editingGroup = ref(null)

function openEditGroupModal(group) {
  editingGroup.value = group
  groupForm.value = { name: group.name, description: group.description || '' }
  groupError.value = ''
  showEditGroupModal.value = true
}

async function submitEditGroup() {
  submitting.value = true
  groupError.value = ''
  try {
    const payload = {}
    if (groupForm.value.name) payload.name = groupForm.value.name
    if (groupForm.value.description !== undefined) payload.description = groupForm.value.description || null
    await adminApi.updateProbeGroup(editingGroup.value.id, payload)
    showEditGroupModal.value = false
    await loadProbeGroups()
  } catch (e) {
    groupError.value = e.response?.data?.detail || 'Erreur lors de la modification'
  } finally {
    submitting.value = false
  }
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
const detailError = ref('')
const addProbeSelection = ref('')
const addUserSelection = ref('')

const availableProbesForGroup = computed(() => {
  if (!detailGroup.value) return allProbes.value
  return allProbes.value.filter(p => !detailGroup.value.probe_ids.includes(p.id))
})

const availableUsersForGroup = computed(() => {
  if (!detailGroup.value) return users.value
  return users.value.filter(u => !detailGroup.value.user_ids.includes(u.id))
})

function openGroupDetailModal(group) {
  detailGroup.value = { ...group, probe_ids: [...group.probe_ids], user_ids: [...group.user_ids] }
  addProbeSelection.value = ''
  addUserSelection.value = ''
  detailError.value = ''
  showGroupDetailModal.value = true
}

async function addProbeToDetailGroup() {
  if (!addProbeSelection.value) return
  submitting.value = true
  detailError.value = ''
  try {
    const { data } = await adminApi.addProbesToGroup(detailGroup.value.id, [addProbeSelection.value])
    detailGroup.value = { ...data, probe_ids: data.probe_ids, user_ids: data.user_ids }
    addProbeSelection.value = ''
    await loadProbeGroups()
  } catch (e) {
    detailError.value = e.response?.data?.detail || 'Erreur'
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
    await loadProbeGroups()
  } catch (e) {
    detailError.value = e.response?.data?.detail || 'Erreur'
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
    await loadProbeGroups()
  } catch (e) {
    detailError.value = e.response?.data?.detail || 'Erreur'
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
    await loadProbeGroups()
  } catch (e) {
    detailError.value = e.response?.data?.detail || 'Erreur'
  } finally {
    submitting.value = false
  }
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
    const { data } = await adminApi.getOidcSettings()
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
    oidcError.value = e.response?.data?.detail || 'Erreur de chargement'
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
    const { data } = await adminApi.updateOidcSettings(payload)
    oidcSettings.value = data
    oidcForm.value.oidc_client_secret = ''
    oidcSuccess.value = true
    setTimeout(() => { oidcSuccess.value = false }, 3000)
  } catch (e) {
    oidcError.value = e.response?.data?.detail || 'Erreur lors de la sauvegarde'
  } finally {
    oidcSaving.value = false
  }
}
</script>
