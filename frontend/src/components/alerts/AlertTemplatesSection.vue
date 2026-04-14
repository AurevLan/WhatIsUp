<template>
  <div>
    <div class="flex items-center justify-between mb-4">
      <div>
        <h2 class="text-lg font-semibold text-white">{{ t('alert_matrix.templates.section_title') }}</h2>
        <p class="text-xs text-gray-500 mt-1">{{ t('alert_matrix.templates.section_hint') }}</p>
      </div>
      <button @click="createNew" class="text-sm btn-primary">
        + {{ t('alert_matrix.templates.new') }}
      </button>
    </div>

    <div v-if="loading" class="text-sm text-gray-500 text-center py-6">
      {{ t('common.loading') }}
    </div>

    <div v-else-if="!groupedTemplates.length" class="text-sm text-gray-500 text-center py-8 italic">
      {{ t('alert_matrix.templates.empty') }}
    </div>

    <div v-else class="space-y-6">
      <div v-for="group in groupedTemplates" :key="group.check_type">
        <h3 class="text-xs font-mono uppercase tracking-wide text-gray-500 mb-2">{{ group.check_type }}</h3>
        <div class="space-y-2">
          <div
            v-for="tpl in group.templates"
            :key="tpl.id"
            class="card flex items-start justify-between gap-4"
          >
            <div class="min-w-0 flex-1">
              <div class="flex items-center gap-2 mb-1">
                <span class="text-sm font-semibold text-white">{{ tpl.name }}</span>
                <span
                  v-if="tpl.is_system"
                  class="text-[9px] uppercase tracking-wider px-1.5 py-0.5 rounded bg-gray-800 text-gray-400 border border-gray-700"
                >{{ t('alert_matrix.templates.system') }}</span>
              </div>
              <p v-if="tpl.description" class="text-xs text-gray-500 mb-2">{{ tpl.description }}</p>
              <div class="flex flex-wrap gap-1">
                <span
                  v-for="row in tpl.rows"
                  :key="row.condition"
                  class="inline-block px-2 py-0.5 rounded text-[10px] font-mono bg-gray-800/80 text-gray-300 border border-gray-800"
                >
                  {{ row.condition }}
                </span>
              </div>
            </div>
            <div class="flex items-center gap-2 shrink-0">
              <button
                v-if="!tpl.is_system"
                type="button"
                @click="edit(tpl)"
                class="text-gray-500 hover:text-blue-400"
                :title="t('common.edit')"
              >
                <Pencil :size="14" />
              </button>
              <button
                v-if="!tpl.is_system"
                type="button"
                @click="remove(tpl)"
                class="text-gray-500 hover:text-red-400"
                :title="t('common.delete')"
              >
                <Trash2 :size="14" />
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>

    <TemplateEditor
      v-model="editorOpen"
      :template="editingTemplate"
      default-check-type="http"
      @saved="onSaved"
    />
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { Pencil, Trash2 } from 'lucide-vue-next'
import api from '../../api/client'
import TemplateEditor from '../monitors/alert-matrix/TemplateEditor.vue'
import { CHECK_TYPES } from '../../constants/alertMatrix'

const { t } = useI18n()

const templates = ref([])
const loading = ref(false)
const editorOpen = ref(false)
const editingTemplate = ref(null)

const groupedTemplates = computed(() => {
  const byType = {}
  for (const tpl of templates.value) {
    if (!byType[tpl.check_type]) byType[tpl.check_type] = []
    byType[tpl.check_type].push(tpl)
  }
  return CHECK_TYPES.filter(ct => byType[ct]?.length).map(ct => ({
    check_type: ct,
    templates: byType[ct],
  }))
})

async function load() {
  loading.value = true
  try {
    const results = await Promise.all(
      CHECK_TYPES.map(ct => api.get(`/alerts/matrix-templates/${ct}`).then(r => r.data))
    )
    templates.value = results.flat()
  } finally {
    loading.value = false
  }
}

function createNew() {
  editingTemplate.value = null
  editorOpen.value = true
}

function edit(tpl) {
  editingTemplate.value = tpl
  editorOpen.value = true
}

async function remove(tpl) {
  if (!confirm(t('alert_matrix.templates.editor.confirm_delete'))) return
  await api.delete(`/alerts/matrix-templates/${tpl.id}`)
  await load()
}

async function onSaved() {
  await load()
}

onMounted(load)
</script>
