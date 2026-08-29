<template>
  <div class="page-body">
    <div class="flex items-center justify-between mb-8">
      <h1 class="font-display text-2xl font-bold text-(--text-1)">{{ t('apiKeys.title') }}</h1>
      <button class="btn-primary" @click="showCreate = true">
        <Plus class="w-4 h-4 mr-2" />
        {{ t('apiKeys.new') }}
      </button>
    </div>

    <!-- Info banner -->
    <div class="mb-6 p-4 rounded-lg bg-(--accent-glow) border border-(--accent-border) text-sm text-(--accent)">
      <p class="font-medium mb-1">{{ t('apiKeys.info_title') }}</p>
      <p class="text-(--accent)">{{ t('apiKeys.info_body') }}</p>
      <code class="mt-2 block text-xs bg-(--bg-surface-2) rounded px-2 py-1 text-(--text-2)">
        Authorization: Bearer wiu_u_...
      </code>
    </div>

    <!-- Key list -->
    <div class="card space-y-3">
      <div v-if="loading" class="space-y-3">
        <div v-for="i in 3" :key="i" class="flex items-center gap-3 p-3 rounded-lg" style="background:var(--bg-surface-2);border:1px solid var(--border)">
          <div class="skeleton-circle" style="width:2rem;height:2rem" />
          <div class="flex-1 space-y-1.5">
            <div class="skeleton-line w-1/3" />
            <div class="skeleton-line w-2/3" style="height:.5rem" />
          </div>
          <div class="skeleton-line w-16" style="height:1.25rem;border-radius:99px" />
        </div>
      </div>

      <EmptyState
        v-else-if="keys.length === 0"
        :title="t('apiKeys.empty_title')"
        :text="t('apiKeys.empty')"
        :cta-label="t('apiKeys.new')"
        @cta="showCreate = true"
      >
        <template #icon><KeyRound :size="22" /></template>
      </EmptyState>

      <div
        v-for="k in keys"
        :key="k.id"
        class="flex items-center justify-between p-3 rounded-lg bg-(--bg-surface-2) border border-(--border)"
      >
        <div class="flex items-center gap-3 min-w-0">
          <KeyRound class="w-4 h-4 text-(--text-2) flex-shrink-0" />
          <div class="min-w-0">
            <p class="text-(--text-1) font-medium truncate">{{ k.name }}</p>
            <p class="text-xs text-(--text-2) font-mono">
              {{ k.key_prefix }}••••••••••••••••••••••••••••••
            </p>
            <p v-if="k.scopes && !k.scopes.includes('write')" class="text-xs text-(--text-3) mt-0.5">
              {{ t('apiKeys.read_only') }}
            </p>
          </div>
        </div>

        <div class="flex items-center gap-4 flex-shrink-0 ml-4">
          <div class="text-right text-xs text-(--text-2) hidden sm:block">
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
            class="text-xs px-2 py-0.5 rounded-full bg-[color-mix(in_srgb,var(--down)_20%,transparent)] text-(--down)"
          >
            {{ t('apiKeys.revoked') }}
          </span>
          <span
            v-else
            class="text-xs px-2 py-0.5 rounded-full bg-[color-mix(in_srgb,var(--up)_20%,transparent)] text-(--up)"
          >
            {{ t('apiKeys.active') }}
          </span>

          <button
            v-if="!k.is_revoked"
            class="text-(--down) hover:text-(--down) transition-colors"
            :title="t('apiKeys.revoke')"
            :aria-label="t('apiKeys.revoke')"
            @click="confirmRevoke(k)"
          >
            <Trash2 class="w-4 h-4" />
          </button>
        </div>
      </div>
    </div>

    <!-- Create modal -->
    <BaseModal v-model="showCreate" :title="t('apiKeys.new')">
      <div class="space-y-4">
        <div>
          <label class="block text-sm text-(--text-2) mb-1">{{ t('apiKeys.key_name') }}</label>
          <input
            v-model="form.name"
            class="input w-full"
            :placeholder="t('apiKeys.key_name_placeholder')"
            maxlength="100"
            @keydown.enter="createKey"
          />
        </div>
        <div>
          <label class="block text-sm text-(--text-2) mb-1">
            {{ t('apiKeys.expires_at') }}
            <span class="text-(--text-3) ml-1">({{ t('common.optional') }})</span>
          </label>
          <input v-model="form.expires_at" type="datetime-local" class="input w-full" />
        </div>
        <div>
          <label class="block text-sm text-(--text-2) mb-1">{{ t('apiKeys.scopes') }}</label>
          <div class="flex gap-2">
            <button
              v-for="opt in scopeOptions" :key="opt.label" type="button"
              class="flex-1 py-2 px-3 rounded-lg border text-xs font-medium transition-colors text-left"
              :class="form.readOnly === opt.readOnly
                ? 'bg-(--accent-glow) border-(--accent-border) text-(--accent)'
                : 'border-(--border) text-(--text-2) hover:border-(--border-hover)'"
              @click="form.readOnly = opt.readOnly"
            >
              <span class="block font-semibold">{{ opt.label }}</span>
              <span class="block text-(--text-3) mt-0.5">{{ opt.desc }}</span>
            </button>
          </div>
        </div>
      </div>

      <template #footer>
        <button class="btn-secondary ml-auto" @click="showCreate = false">
          {{ t('common.cancel') }}
        </button>
        <button class="btn-primary" :disabled="!form.name.trim() || creating" @click="createKey">
          <Loader2 v-if="creating" class="w-4 h-4 mr-2 animate-spin" />
          {{ t('apiKeys.create') }}
        </button>
      </template>
    </BaseModal>

    <!-- Key reveal modal — shown once after creation -->
    <BaseModal :model-value="!!newKey" size="lg" @close="newKey = null">
      <template #header>
        <div class="flex items-center gap-3">
          <CheckCircle class="w-6 h-6 text-(--up) flex-shrink-0" />
          <h2 class="text-lg font-semibold text-(--text-1)">{{ t('apiKeys.created') }}</h2>
        </div>
      </template>

      <p class="text-sm text-(--warn) mb-3">{{ t('apiKeys.show_once_warning') }}</p>

      <div class="relative">
        <code
          class="block w-full bg-(--bg-surface-2) border border-(--border) rounded-lg px-4 py-3 text-sm text-(--up) font-mono break-all pr-12"
        >
          {{ newKey?.key }}
        </code>
        <button
          class="absolute right-2 top-2 text-(--text-2) hover:text-(--text-1) transition-colors"
          :title="t('common.copy')"
          :aria-label="t('common.copy')"
          @click="copyKey"
        >
          <Copy class="w-4 h-4" />
        </button>
      </div>

      <p class="mt-3 text-xs text-(--text-2)">{{ t('apiKeys.usage_hint') }}</p>
      <code class="mt-1 block text-xs bg-(--bg-surface-2) rounded px-2 py-1 text-(--text-2) font-mono">
        Authorization: Bearer {{ newKey?.key }}
      </code>

      <template #footer>
        <button class="btn-primary ml-auto" @click="newKey = null">{{ t('apiKeys.i_saved_it') }}</button>
      </template>
    </BaseModal>
  </div>
</template>

<script setup>
import { computed, ref, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { CheckCircle, Copy, KeyRound, Loader2, Plus, Trash2 } from 'lucide-vue-next'
import { apiKeysApi } from '../api/apiKeys.js'
import BaseModal from '../components/BaseModal.vue'
import EmptyState from '../components/shared/EmptyState.vue'
import { useToast } from '../composables/useToast'
import { useConfirm } from '../composables/useConfirm'
import { useDateFormat } from '../composables/useDateFormat'

const { t } = useI18n()
const { success } = useToast()
const { confirm } = useConfirm()
const { formatDate: fmtDate } = useDateFormat()

const keys = ref([])
const loading = ref(false)
const showCreate = ref(false)
const creating = ref(false)
const newKey = ref(null)
// `readOnly: false` par défaut — même portée que les clés émises avant
// l'arrivée des scopes, pour ne pas surprendre qui recrée une clé existante.
const form = ref({ name: '', expires_at: '', readOnly: false })

const scopeOptions = computed(() => [
  { readOnly: false, label: t('apiKeys.scope_full'), desc: t('apiKeys.scope_full_desc') },
  { readOnly: true, label: t('apiKeys.scope_read'), desc: t('apiKeys.scope_read_desc') },
])

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
    const payload = {
      name: form.value.name.trim(),
      scopes: form.value.readOnly ? ['read'] : ['read', 'write'],
    }
    if (form.value.expires_at) payload.expires_at = new Date(form.value.expires_at).toISOString()
    const { data } = await apiKeysApi.create(payload)
    newKey.value = data
    showCreate.value = false
    form.value = { name: '', expires_at: '', readOnly: false }
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
  success(t('apiKeys.toast_revoked', { name: k.name }))
}

async function copyKey() {
  if (newKey.value?.key) {
    await navigator.clipboard.writeText(newKey.value.key)
    success(t('apiKeys.toast_copied'))
  }
}

const formatDate = (iso) => fmtDate(iso, { dateStyle: 'medium' })

onMounted(load)
</script>
