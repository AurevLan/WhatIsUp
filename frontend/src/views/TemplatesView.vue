<template>
  <div class="page-body">
    <div class="flex items-center justify-between mb-8">
      <div>
        <h1 class="text-2xl font-bold text-white">{{ t('templates.title') }}</h1>
        <p class="text-gray-400 mt-1">{{ t('templates.subtitle') }}</p>
      </div>
      <button @click="showCreate = true" class="btn-primary">+ {{ t('templates.new') }}</button>
    </div>

    <!-- Loading skeleton -->
    <div v-if="loading" class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
      <div v-for="i in 6" :key="i" class="card">
        <div class="space-y-3">
          <div class="skeleton-line w-1/2" />
          <div class="skeleton-line w-full" style="height:.5rem" />
          <div class="skeleton-line w-20" style="height:1.25rem;border-radius:4px" />
          <div class="skeleton-line w-full" style="height:2rem;border-radius:var(--radius-sm);margin-top:auto" />
        </div>
      </div>
    </div>

    <div v-else-if="templates.length === 0" class="empty-state">
      <div class="empty-state__icon"><Copy :size="22" /></div>
      <p class="empty-state__title">{{ t('templates.no_templates') }}</p>
      <p class="empty-state__text">{{ t('templates.empty_desc') }}</p>
      <button @click="showCreate = true" class="btn-primary mt-2">+ {{ t('templates.new') }}</button>
    </div>

    <div v-else class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
      <div
        v-for="tpl in templates"
        :key="tpl.id"
        class="card flex flex-col gap-3"
      >
        <div class="flex items-start justify-between">
          <div>
            <div class="flex items-center gap-2">
              <span class="text-white font-semibold">{{ tpl.name }}</span>
              <span v-if="tpl.is_public" class="text-xs px-1.5 py-0.5 rounded bg-blue-500/20 text-blue-400">{{ t('templates.public_badge') }}</span>
              <span v-if="tpl.owner_id !== currentUserId" class="text-xs px-1.5 py-0.5 rounded bg-purple-500/20 text-purple-400">{{ t('templates.shared_badge') }}</span>
            </div>
            <p v-if="tpl.description" class="text-sm text-gray-400 mt-1">{{ tpl.description }}</p>
          </div>
          <div class="flex gap-2 flex-shrink-0 ml-2">
            <button
              v-if="tpl.owner_id === currentUserId"
              @click="startEdit(tpl)"
              class="text-xs text-blue-400 hover:text-blue-300"
            >{{ t('templates.edit') }}</button>
            <button
              v-if="tpl.owner_id === currentUserId"
              @click="deleteTemplate(tpl)"
              class="text-xs text-red-400 hover:text-red-300"
            >{{ t('templates.delete') }}</button>
          </div>
        </div>

        <!-- Variables -->
        <div v-if="tpl.variables?.length" class="text-xs text-gray-500">
          <span class="text-gray-400">{{ t('templates.variables_label') }}:</span>
          <span v-for="v in tpl.variables" :key="v.name" class="ml-1 font-mono bg-gray-800 px-1 rounded" v-text="'{{' + v.name + '}}'"></span>
        </div>

        <!-- Check type badge -->
        <span class="text-xs font-mono px-2 py-0.5 rounded w-fit bg-gray-800 text-gray-400 uppercase">
          {{ tpl.monitor_config?.check_type || 'http' }}
        </span>

        <button
          @click="openApply(tpl)"
          class="btn-primary text-sm mt-auto"
        >
          {{ t('templates.apply') }}
        </button>
      </div>
    </div>

    <!-- Create/Edit modal -->
    <BaseModal :model-value="showCreate || !!editingTemplate" size="lg"
      :title="editingTemplate ? t('templates.edit_title') : t('templates.new')"
      @close="closeModal">
      <div class="space-y-4">
          <div>
            <label class="block text-sm text-gray-400 mb-1">{{ t('templates.form_name') }}</label>
            <input v-model="form.name" class="input w-full" :placeholder="t('templates.form_name_placeholder')" />
          </div>
          <div>
            <label class="block text-sm text-gray-400 mb-1">{{ t('templates.form_description') }}</label>
            <input v-model="form.description" class="input w-full" />
          </div>
          <div class="flex items-center gap-2">
            <input v-model="form.is_public" type="checkbox" id="tpl-public" />
            <label for="tpl-public" class="text-sm text-gray-300">{{ t('templates.form_public') }}</label>
          </div>

          <div>
            <label class="block text-sm text-gray-400 mb-1">{{ t('templates.variables_label') }}</label>
            <div v-for="(v, i) in form.variables" :key="i" class="flex gap-2 mb-2">
              <input v-model="v.name" class="input flex-1" :placeholder="t('templates.var_name')" />
              <input v-model="v.description" class="input flex-1" :placeholder="t('templates.var_description')" />
              <input v-model="v.default" class="input w-32" :placeholder="t('templates.var_default')" />
              <button @click="form.variables.splice(i, 1)" class="text-red-400 hover:text-red-300">✕</button>
            </div>
            <button @click="form.variables.push({ name: '', description: '', default: '' })" class="text-xs text-blue-400 hover:text-blue-300">{{ t('templates.form_add_variable') }}</button>
          </div>

          <div>
            <label class="block text-sm text-gray-400 mb-1">
              {{ t('templates.form_config') }}
              <span class="text-gray-500 ml-1">—
                <i18n-t keypath="templates.form_config_hint" tag="span">
                  <template #placeholder>
                    <code class="font-mono bg-gray-800 px-1 rounded" v-text="'{{VAR}}'"></code>
                  </template>
                </i18n-t>
              </span>
            </label>
            <textarea
              v-model="form.configJson"
              class="input w-full font-mono text-xs"
              rows="10"
              placeholder="{&quot;check_type&quot;: &quot;http&quot;, &quot;name&quot;: &quot;{{SERVICE_NAME}}&quot;, &quot;url&quot;: &quot;{{URL}}&quot;, ...}"
            ></textarea>
            <p v-if="configError" class="text-xs text-red-400 mt-1">{{ configError }}</p>
          </div>
        </div>

      <template #footer>
        <button @click="closeModal" class="btn-secondary ml-auto">{{ t('common.cancel') }}</button>
        <button @click="saveTemplate" class="btn-primary" :disabled="saving">
          <Loader2 v-if="saving" class="w-4 h-4 mr-2 animate-spin inline" />
          {{ editingTemplate ? t('common.save') : t('templates.create') }}
        </button>
      </template>
    </BaseModal>

    <!-- Apply modal -->
    <BaseModal :model-value="!!applyTemplate"
      :title="t('templates.apply_title', { name: applyTemplate?.name ?? '' })"
      :message="t('templates.apply_subtitle')"
      @close="applyTemplate = null">
      <div class="space-y-3">
        <div v-for="v in applyTemplate?.variables ?? []" :key="v.name">
          <label class="block text-sm text-gray-400 mb-1">
            <code class="font-mono text-purple-400" v-text="'{{' + v.name + '}}'"></code>
            <span v-if="v.description" class="text-gray-500 ml-1">{{ v.description }}</span>
          </label>
          <input
            v-model="applyValues[v.name]"
            class="input w-full"
            :placeholder="v.default || v.name"
          />
        </div>

        <div v-if="!applyTemplate?.variables?.length" class="text-sm text-gray-500">
          {{ t('templates.no_variables') }}
        </div>

        <div>
          <label class="block text-sm text-gray-400 mb-1">{{ t('templates.name_override') }}</label>
          <input v-model="applyNameOverride" class="input w-full" :placeholder="t('templates.name_override_placeholder')" />
        </div>
      </div>

      <template #footer>
        <button @click="applyTemplate = null" class="btn-secondary ml-auto">{{ t('common.cancel') }}</button>
        <button @click="doApply" class="btn-primary" :disabled="applying">
          <Loader2 v-if="applying" class="w-4 h-4 mr-2 animate-spin inline" />
          {{ t('templates.create_monitor') }}
        </button>
      </template>
    </BaseModal>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { Copy, Loader2 } from 'lucide-vue-next'
import { templatesApi } from '../api/templates.js'
import BaseModal from '../components/BaseModal.vue'
import { useToast } from '../composables/useToast'
import { useConfirm } from '../composables/useConfirm'
import { useAuthStore } from '../stores/auth'

const { t } = useI18n()
const { success, error: toastError } = useToast()
const { confirm } = useConfirm()
const auth = useAuthStore()

const templates = ref([])
const loading = ref(false)
const showCreate = ref(false)
const editingTemplate = ref(null)
const saving = ref(false)
const configError = ref('')
const applyTemplate = ref(null)
const applyValues = ref({})
const applyNameOverride = ref('')
const applying = ref(false)

const currentUserId = auth.user?.id

const form = ref({
  name: '',
  description: '',
  is_public: false,
  variables: [],
  configJson: '{\n  "check_type": "http",\n  "name": "{{SERVICE_NAME}}",\n  "url": "{{URL}}"\n}',
})

async function load() {
  loading.value = true
  try {
    const { data } = await templatesApi.list()
    templates.value = data
  } finally {
    loading.value = false
  }
}

function startEdit(tpl) {
  editingTemplate.value = tpl
  form.value = {
    name: tpl.name,
    description: tpl.description || '',
    is_public: tpl.is_public,
    variables: (tpl.variables || []).map(v => ({ ...v })),
    configJson: JSON.stringify(tpl.monitor_config, null, 2),
  }
}

function closeModal() {
  showCreate.value = false
  editingTemplate.value = null
  form.value = { name: '', description: '', is_public: false, variables: [], configJson: '' }
  configError.value = ''
}

async function saveTemplate() {
  configError.value = ''
  let monitor_config
  try {
    monitor_config = JSON.parse(form.value.configJson)
  } catch (e) {
    configError.value = t('templates.invalid_json', { msg: e.message })
    return
  }

  saving.value = true
  try {
    const payload = {
      name: form.value.name,
      description: form.value.description || null,
      is_public: form.value.is_public,
      variables: form.value.variables.filter(v => v.name),
      monitor_config,
    }
    if (editingTemplate.value) {
      await templatesApi.update(editingTemplate.value.id, payload)
      success(t('templates.updated'))
    } else {
      await templatesApi.create(payload)
      success(t('templates.created'))
    }
    closeModal()
    await load()
  } catch {
    toastError(t('templates.error_saving'))
  } finally {
    saving.value = false
  }
}

async function deleteTemplate(tpl) {
  const ok = await confirm({
    title: t('templates.delete_confirm', { name: tpl.name }),
    confirmLabel: t('common.delete'),
  })
  if (!ok) return
  try {
    await templatesApi.delete(tpl.id)
    templates.value = templates.value.filter((tp) => tp.id !== tpl.id)
    success(t('templates.deleted'))
  } catch {
    toastError(t('templates.error_deleting'))
  }
}

function openApply(tpl) {
  applyTemplate.value = tpl
  applyValues.value = {}
  applyNameOverride.value = ''
  // Prefill defaults
  for (const v of tpl.variables || []) {
    if (v.default) applyValues.value[v.name] = v.default
  }
}

async function doApply() {
  applying.value = true
  try {
    const payload = {
      values: applyValues.value,
      name_override: applyNameOverride.value || null,
    }
    const { data } = await templatesApi.apply(applyTemplate.value.id, payload)
    success(t('templates.applied', { name: data.name }))
    applyTemplate.value = null
  } catch (e) {
    toastError(t('templates.error_applying', { detail: e.response?.data?.detail || e.message }))
  } finally {
    applying.value = false
  }
}

onMounted(load)
</script>
