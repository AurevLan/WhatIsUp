<template>
  <div class="monitor-dependencies">
    <h3 class="section-title">{{ t('dependencies.title') }}</h3>
    <p class="section-desc">{{ t('dependencies.description') }}</p>

    <div v-if="loading" class="loading-text">{{ t('common.loading') }}</div>

    <template v-else>
      <ul v-if="dependencies.length > 0" class="dep-list">
        <li v-for="dep in dependencies" :key="dep.id" class="dep-item">
          <span class="dep-parent-name">{{ parentName(dep.parent_id) }}</span>
          <span v-if="dep.suppress_on_parent_down" class="badge badge-warn">
            {{ t('dependencies.suppress_on_parent_down') }}
          </span>
          <button class="btn-icon btn-danger" @click="removeDep(dep)" :title="t('dependencies.remove')">
            &times;
          </button>
        </li>
      </ul>
      <p v-else class="empty-text">{{ t('dependencies.empty') }}</p>

      <!-- Add form -->
      <form class="dep-add-form" @submit.prevent="addDep">
        <select v-model="selectedParentId" class="select-input" required>
          <option value="" disabled>{{ t('dependencies.parent_monitor') }}</option>
          <option
            v-for="m in availableMonitors"
            :key="m.id"
            :value="m.id"
          >{{ m.name }}</option>
        </select>
        <label class="checkbox-label">
          <input type="checkbox" v-model="suppressOnDown" />
          {{ t('dependencies.suppress_on_parent_down') }}
        </label>
        <button type="submit" class="btn btn-primary btn-sm" :disabled="!selectedParentId || saving">
          {{ t('dependencies.add') }}
        </button>
      </form>

      <p v-if="errorMsg" class="error-text">{{ errorMsg }}</p>
      <p v-if="successMsg" class="success-text">{{ successMsg }}</p>
    </template>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { monitorsApi } from '../../api/monitors'

const props = defineProps({
  monitorId: { type: String, required: true },
  allMonitors: { type: Array, default: () => [] },
})

const { t } = useI18n()

const dependencies = ref([])
const loading = ref(true)
const saving = ref(false)
const selectedParentId = ref('')
const suppressOnDown = ref(true)
const errorMsg = ref('')
const successMsg = ref('')

// Monitors available as parents: all except self and already-added parents
const availableMonitors = computed(() => {
  const existingParentIds = new Set(dependencies.value.map((d) => d.parent_id))
  return props.allMonitors.filter(
    (m) => m.id !== props.monitorId && !existingParentIds.has(m.id)
  )
})

function parentName(parentId) {
  const m = props.allMonitors.find((m) => m.id === parentId)
  return m ? m.name : parentId
}

async function loadDeps() {
  loading.value = true
  try {
    const res = await monitorsApi.listDependencies(props.monitorId)
    dependencies.value = res.data
  } finally {
    loading.value = false
  }
}

async function addDep() {
  errorMsg.value = ''
  successMsg.value = ''
  saving.value = true
  try {
    const res = await monitorsApi.addDependency(props.monitorId, {
      parent_id: selectedParentId.value,
      suppress_on_parent_down: suppressOnDown.value,
    })
    dependencies.value.push(res.data)
    selectedParentId.value = ''
    successMsg.value = t('dependencies.added')
  } catch (e) {
    const status = e.response?.status
    if (status === 409) errorMsg.value = t('dependencies.error_duplicate')
    else if (status === 400) errorMsg.value = t('dependencies.error_self')
    else errorMsg.value = t('common.error')
  } finally {
    saving.value = false
  }
}

async function removeDep(dep) {
  errorMsg.value = ''
  successMsg.value = ''
  try {
    await monitorsApi.removeDependency(props.monitorId, dep.id)
    dependencies.value = dependencies.value.filter((d) => d.id !== dep.id)
    successMsg.value = t('dependencies.removed')
  } catch {
    errorMsg.value = t('common.error')
  }
}

onMounted(loadDeps)
</script>

<style scoped>
.monitor-dependencies {
  margin-top: 2rem;
}
.section-title {
  font-size: 1rem;
  font-weight: 600;
  margin-bottom: 0.25rem;
}
.section-desc {
  font-size: 0.875rem;
  color: var(--color-text-muted, #6b7280);
  margin-bottom: 1rem;
}
.dep-list {
  list-style: none;
  padding: 0;
  margin: 0 0 1rem;
}
.dep-item {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.4rem 0;
  border-bottom: 1px solid var(--color-border, #e5e7eb);
}
.dep-parent-name {
  flex: 1;
  font-weight: 500;
}
.badge {
  font-size: 0.75rem;
  padding: 0.15rem 0.5rem;
  border-radius: 9999px;
}
.badge-warn {
  background: #fef3c7;
  color: #92400e;
}
.btn-icon {
  background: none;
  border: none;
  cursor: pointer;
  font-size: 1.1rem;
  line-height: 1;
  padding: 0.1rem 0.4rem;
  border-radius: 4px;
}
.btn-danger { color: #dc2626; }
.btn-danger:hover { background: #fee2e2; }
.dep-add-form {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  flex-wrap: wrap;
  margin-top: 0.5rem;
}
.select-input {
  flex: 1;
  min-width: 160px;
  padding: 0.35rem 0.5rem;
  border: 1px solid var(--color-border, #d1d5db);
  border-radius: 6px;
  font-size: 0.875rem;
}
.checkbox-label {
  display: flex;
  align-items: center;
  gap: 0.35rem;
  font-size: 0.875rem;
}
.btn { padding: 0.35rem 0.9rem; border-radius: 6px; border: none; cursor: pointer; font-size: 0.875rem; }
.btn-primary { background: #2563eb; color: #fff; }
.btn-primary:disabled { opacity: 0.5; cursor: not-allowed; }
.btn-sm { padding: 0.3rem 0.75rem; }
.empty-text { font-size: 0.875rem; color: var(--color-text-muted, #6b7280); }
.loading-text { font-size: 0.875rem; color: var(--color-text-muted, #6b7280); }
.error-text { color: #dc2626; font-size: 0.875rem; margin-top: 0.5rem; }
.success-text { color: #16a34a; font-size: 0.875rem; margin-top: 0.5rem; }
</style>
