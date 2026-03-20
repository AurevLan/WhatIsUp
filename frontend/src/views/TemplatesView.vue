<template>
  <div class="p-8">
    <div class="flex items-center justify-between mb-8">
      <div>
        <h1 class="text-2xl font-bold text-white">Monitor Templates</h1>
        <p class="text-gray-400 mt-1">Reusable blueprints to create monitors quickly</p>
      </div>
      <button @click="showCreate = true" class="btn-primary">+ New template</button>
    </div>

    <!-- List -->
    <div v-if="loading" class="text-center py-16 text-gray-400">{{ t('common.loading') }}</div>

    <div v-else-if="templates.length === 0" class="text-center py-16 text-gray-500">
      No templates yet. Create one to get started.
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
              <span v-if="tpl.is_public" class="text-xs px-1.5 py-0.5 rounded bg-blue-500/20 text-blue-400">Public</span>
              <span v-if="tpl.owner_id !== currentUserId" class="text-xs px-1.5 py-0.5 rounded bg-purple-500/20 text-purple-400">Shared</span>
            </div>
            <p v-if="tpl.description" class="text-sm text-gray-400 mt-1">{{ tpl.description }}</p>
          </div>
          <div class="flex gap-2 flex-shrink-0 ml-2">
            <button
              v-if="tpl.owner_id === currentUserId"
              @click="startEdit(tpl)"
              class="text-xs text-blue-400 hover:text-blue-300"
            >Edit</button>
            <button
              v-if="tpl.owner_id === currentUserId"
              @click="deleteTemplate(tpl)"
              class="text-xs text-red-400 hover:text-red-300"
            >Delete</button>
          </div>
        </div>

        <!-- Variables -->
        <div v-if="tpl.variables?.length" class="text-xs text-gray-500">
          <span class="text-gray-400">Variables:</span>
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
          Apply template
        </button>
      </div>
    </div>

    <!-- Create/Edit modal -->
    <div v-if="showCreate || editingTemplate" class="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4" @click.self="closeModal">
      <div class="card w-full max-w-2xl max-h-[90vh] overflow-y-auto">
        <h2 class="text-lg font-semibold text-white mb-4">{{ editingTemplate ? 'Edit template' : 'New template' }}</h2>

        <div class="space-y-4">
          <div>
            <label class="block text-sm text-gray-400 mb-1">Name</label>
            <input v-model="form.name" class="input w-full" placeholder="e.g. REST API monitor" />
          </div>
          <div>
            <label class="block text-sm text-gray-400 mb-1">Description (optional)</label>
            <input v-model="form.description" class="input w-full" />
          </div>
          <div class="flex items-center gap-2">
            <input v-model="form.is_public" type="checkbox" id="tpl-public" />
            <label for="tpl-public" class="text-sm text-gray-300">Make this template public (visible to all users)</label>
          </div>

          <div>
            <label class="block text-sm text-gray-400 mb-1">Variables</label>
            <div v-for="(v, i) in form.variables" :key="i" class="flex gap-2 mb-2">
              <input v-model="v.name" class="input flex-1" placeholder="VAR_NAME" />
              <input v-model="v.description" class="input flex-1" placeholder="Description" />
              <input v-model="v.default" class="input w-32" placeholder="Default" />
              <button @click="form.variables.splice(i, 1)" class="text-red-400 hover:text-red-300">✕</button>
            </div>
            <button @click="form.variables.push({ name: '', description: '', default: '' })" class="text-xs text-blue-400 hover:text-blue-300">+ Add variable</button>
          </div>

          <div>
            <label class="block text-sm text-gray-400 mb-1">
              Monitor config (JSON)
              <span class="text-gray-500 ml-1">— use <code class="font-mono bg-gray-800 px-1 rounded" v-text="'{{VAR}}'"></code> for substitution</span>
            </label>
            <textarea
              v-model="form.configJson"
              class="input w-full font-mono text-xs"
              rows="10"
              placeholder='{"check_type": "http", "name": "{{SERVICE_NAME}}", "url": "{{URL}}", ...}'
            ></textarea>
            <p v-if="configError" class="text-xs text-red-400 mt-1">{{ configError }}</p>
          </div>
        </div>

        <div class="flex justify-end gap-3 mt-6">
          <button @click="closeModal" class="btn-secondary">{{ t('common.cancel') }}</button>
          <button @click="saveTemplate" class="btn-primary" :disabled="saving">
            <Loader2 v-if="saving" class="w-4 h-4 mr-2 animate-spin inline" />
            {{ editingTemplate ? 'Save' : 'Create' }}
          </button>
        </div>
      </div>
    </div>

    <!-- Apply modal -->
    <div v-if="applyTemplate" class="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4" @click.self="applyTemplate = null">
      <div class="card w-full max-w-md">
        <h2 class="text-lg font-semibold text-white mb-1">Apply: {{ applyTemplate.name }}</h2>
        <p class="text-sm text-gray-400 mb-4">Fill in the variables to create a monitor from this template.</p>

        <div class="space-y-3">
          <div v-for="v in applyTemplate.variables" :key="v.name">
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

          <div v-if="!applyTemplate.variables?.length" class="text-sm text-gray-500">
            No variables to fill. A monitor will be created immediately.
          </div>

          <div>
            <label class="block text-sm text-gray-400 mb-1">Name override (optional)</label>
            <input v-model="applyNameOverride" class="input w-full" placeholder="Custom monitor name" />
          </div>
        </div>

        <div class="flex justify-end gap-3 mt-6">
          <button @click="applyTemplate = null" class="btn-secondary">{{ t('common.cancel') }}</button>
          <button @click="doApply" class="btn-primary" :disabled="applying">
            <Loader2 v-if="applying" class="w-4 h-4 mr-2 animate-spin inline" />
            Create monitor
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { Loader2 } from 'lucide-vue-next'
import { templatesApi } from '../api/templates.js'
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
    configError.value = 'Invalid JSON: ' + e.message
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
      success('Template updated')
    } else {
      await templatesApi.create(payload)
      success('Template created')
    }
    closeModal()
    await load()
  } catch (e) {
    toastError('Error saving template')
  } finally {
    saving.value = false
  }
}

async function deleteTemplate(tpl) {
  const ok = await confirm({
    title: `Delete template "${tpl.name}"?`,
    confirmLabel: 'Delete',
  })
  if (!ok) return
  try {
    await templatesApi.delete(tpl.id)
    templates.value = templates.value.filter(t => t.id !== tpl.id)
    success('Template deleted')
  } catch {
    toastError('Error deleting template')
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
    success(`Monitor "${data.name}" created`)
    applyTemplate.value = null
  } catch (e) {
    toastError('Error applying template: ' + (e.response?.data?.detail || e.message))
  } finally {
    applying.value = false
  }
}

onMounted(load)
</script>
