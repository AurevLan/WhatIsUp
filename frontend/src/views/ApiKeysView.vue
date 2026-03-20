<template>
  <div class="p-8">
    <div class="flex items-center justify-between mb-8">
      <h1 class="text-2xl font-bold text-white">{{ t('apiKeys.title') }}</h1>
      <button class="btn-primary" @click="showCreate = true">
        <Plus class="w-4 h-4 mr-2" />
        {{ t('apiKeys.new') }}
      </button>
    </div>

    <!-- Info banner -->
    <div class="mb-6 p-4 rounded-lg bg-blue-500/10 border border-blue-500/30 text-sm text-blue-300">
      <p class="font-medium mb-1">{{ t('apiKeys.info_title') }}</p>
      <p class="text-blue-400">{{ t('apiKeys.info_body') }}</p>
      <code class="mt-2 block text-xs bg-gray-900/60 rounded px-2 py-1 text-gray-300">
        Authorization: Bearer wiu_u_...
      </code>
    </div>

    <!-- Key list -->
    <div class="card space-y-3">
      <div v-if="loading" class="text-center py-8 text-gray-400">{{ t('common.loading') }}</div>

      <div v-else-if="keys.length === 0" class="text-center py-8 text-gray-400">
        {{ t('apiKeys.empty') }}
      </div>

      <div
        v-for="k in keys"
        :key="k.id"
        class="flex items-center justify-between p-3 rounded-lg bg-gray-800/50 border border-gray-700/50"
      >
        <div class="flex items-center gap-3 min-w-0">
          <KeyRound class="w-4 h-4 text-gray-400 flex-shrink-0" />
          <div class="min-w-0">
            <p class="text-white font-medium truncate">{{ k.name }}</p>
            <p class="text-xs text-gray-400 font-mono">
              {{ k.key_prefix }}••••••••••••••••••••••••••••••
            </p>
          </div>
        </div>

        <div class="flex items-center gap-4 flex-shrink-0 ml-4">
          <div class="text-right text-xs text-gray-400 hidden sm:block">
            <p v-if="k.last_used_at">
              {{ t('apiKeys.last_used') }} {{ formatDate(k.last_used_at) }}
            </p>
            <p v-else class="italic">{{ t('apiKeys.never_used') }}</p>
            <p v-if="k.expires_at" class="mt-0.5">
              {{ t('apiKeys.expires') }} {{ formatDate(k.expires_at) }}
            </p>
          </div>

          <span
            v-if="k.is_revoked"
            class="text-xs px-2 py-0.5 rounded-full bg-red-500/20 text-red-400"
          >
            {{ t('apiKeys.revoked') }}
          </span>
          <span
            v-else
            class="text-xs px-2 py-0.5 rounded-full bg-green-500/20 text-green-400"
          >
            {{ t('apiKeys.active') }}
          </span>

          <button
            v-if="!k.is_revoked"
            class="text-red-400 hover:text-red-300 transition-colors"
            :title="t('apiKeys.revoke')"
            @click="confirmRevoke(k)"
          >
            <Trash2 class="w-4 h-4" />
          </button>
        </div>
      </div>
    </div>

    <!-- Create modal -->
    <div
      v-if="showCreate"
      class="fixed inset-0 bg-black/60 flex items-center justify-center z-50"
      @click.self="showCreate = false"
    >
      <div class="card w-full max-w-md mx-4">
        <h2 class="text-lg font-semibold text-white mb-4">{{ t('apiKeys.new') }}</h2>

        <div class="space-y-4">
          <div>
            <label class="block text-sm text-gray-400 mb-1">{{ t('apiKeys.key_name') }}</label>
            <input
              v-model="form.name"
              class="input w-full"
              :placeholder="t('apiKeys.key_name_placeholder')"
              maxlength="100"
              @keydown.enter="createKey"
            />
          </div>
          <div>
            <label class="block text-sm text-gray-400 mb-1">
              {{ t('apiKeys.expires_at') }}
              <span class="text-gray-500 ml-1">({{ t('common.optional') }})</span>
            </label>
            <input v-model="form.expires_at" type="datetime-local" class="input w-full" />
          </div>
        </div>

        <div class="flex justify-end gap-3 mt-6">
          <button class="btn-secondary" @click="showCreate = false">
            {{ t('common.cancel') }}
          </button>
          <button class="btn-primary" :disabled="!form.name.trim() || creating" @click="createKey">
            <Loader2 v-if="creating" class="w-4 h-4 mr-2 animate-spin" />
            {{ t('apiKeys.create') }}
          </button>
        </div>
      </div>
    </div>

    <!-- Key reveal modal — shown once after creation -->
    <div
      v-if="newKey"
      class="fixed inset-0 bg-black/60 flex items-center justify-center z-50"
    >
      <div class="card w-full max-w-lg mx-4">
        <div class="flex items-center gap-3 mb-4">
          <CheckCircle class="w-6 h-6 text-green-400 flex-shrink-0" />
          <h2 class="text-lg font-semibold text-white">{{ t('apiKeys.created') }}</h2>
        </div>

        <p class="text-sm text-amber-300 mb-3">{{ t('apiKeys.show_once_warning') }}</p>

        <div class="relative">
          <code
            class="block w-full bg-gray-900 border border-gray-700 rounded-lg px-4 py-3 text-sm text-green-300 font-mono break-all pr-12"
          >
            {{ newKey.key }}
          </code>
          <button
            class="absolute right-2 top-2 text-gray-400 hover:text-white transition-colors"
            :title="t('common.copy')"
            @click="copyKey"
          >
            <Copy class="w-4 h-4" />
          </button>
        </div>

        <p class="mt-3 text-xs text-gray-400">{{ t('apiKeys.usage_hint') }}</p>
        <code class="mt-1 block text-xs bg-gray-900/60 rounded px-2 py-1 text-gray-300 font-mono">
          Authorization: Bearer {{ newKey.key }}
        </code>

        <div class="flex justify-end mt-6">
          <button class="btn-primary" @click="newKey = null">{{ t('apiKeys.i_saved_it') }}</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { CheckCircle, Copy, KeyRound, Loader2, Plus, Trash2 } from 'lucide-vue-next'
import { apiKeysApi } from '../api/apiKeys.js'
import { useToast } from '../composables/useToast'
import { useConfirm } from '../composables/useConfirm'

const { t } = useI18n()
const { success } = useToast()
const { confirm } = useConfirm()

const keys = ref([])
const loading = ref(false)
const showCreate = ref(false)
const creating = ref(false)
const newKey = ref(null)
const form = ref({ name: '', expires_at: '' })

async function load() {
  loading.value = true
  try {
    const { data } = await apiKeysApi.list()
    keys.value = data
  } finally {
    loading.value = false
  }
}

async function createKey() {
  if (!form.value.name.trim() || creating.value) return
  creating.value = true
  try {
    const payload = { name: form.value.name.trim() }
    if (form.value.expires_at) payload.expires_at = new Date(form.value.expires_at).toISOString()
    const { data } = await apiKeysApi.create(payload)
    newKey.value = data
    showCreate.value = false
    form.value = { name: '', expires_at: '' }
    await load()
  } finally {
    creating.value = false
  }
}

async function confirmRevoke(k) {
  const ok = await confirm({
    title: t('apiKeys.revoke_confirm', { name: k.name }),
    confirmLabel: t('apiKeys.revoke'),
  })
  if (!ok) return
  await apiKeysApi.revoke(k.id)
  await load()
  success(`Clé "${k.name}" révoquée`)
}

async function copyKey() {
  if (newKey.value?.key) {
    await navigator.clipboard.writeText(newKey.value.key)
    success('Clé copiée dans le presse-papiers')
  }
}

function formatDate(iso) {
  return new Date(iso).toLocaleDateString(undefined, { dateStyle: 'medium' })
}

onMounted(load)
</script>
