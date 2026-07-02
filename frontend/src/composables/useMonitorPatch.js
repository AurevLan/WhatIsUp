// Optimistic single-field patches on the monitor object.
//
// Each patcher in this composable follows the same pattern: mutate
// monitor.value locally, fire the API call, and roll back if it fails.
// Centralising them avoids the 8 sites previously sprinkled across the view
// that all repeated this dance manually.

import { useI18n } from 'vue-i18n'
import { computed } from 'vue'
import { monitorsApi } from '../api/monitors'
import { useToast } from './useToast'

export function useMonitorPatch(monitorRef) {
  const { t } = useI18n()
  const { error: toastError } = useToast()

  // ── Schema drift baseline
  async function toggleSchemaDrift(enabled) {
    if (!monitorRef.value) return
    try {
      await monitorsApi.update(monitorRef.value.id, { schema_drift_enabled: enabled })
      monitorRef.value.schema_drift_enabled = enabled
    } catch {
      // Silent: error already surfaces via the API client's global toast.
    }
  }

  async function acceptSchemaBaseline() {
    if (!monitorRef.value) return
    try {
      const { data } = await monitorsApi.acceptSchemaBaseline(monitorRef.value.id, { skipErrorToast: true })
      monitorRef.value.schema_baseline = data.baseline
      monitorRef.value.schema_baseline_updated_at = new Date().toISOString()
    } catch (e) {
      toastError(e.response?.data?.detail || 'Error accepting baseline')
    }
  }

  async function resetSchemaBaseline() {
    if (!monitorRef.value) return
    try {
      await monitorsApi.resetSchemaBaseline(monitorRef.value.id)
      monitorRef.value.schema_baseline = null
      monitorRef.value.schema_baseline_updated_at = null
    } catch {
      // Silent.
    }
  }

  // ── Tags (optimistic, rolls back on failure)
  async function patchTags(newTags) {
    if (!monitorRef.value) return
    const previous = monitorRef.value.tags || []
    monitorRef.value.tags = newTags
    try {
      await monitorsApi.update(monitorRef.value.id, {
        tag_ids: newTags.map((t) => t.id),
      })
    } catch {
      monitorRef.value.tags = previous
    }
  }

  // ── Network scope (all / internal / external)
  const networkScopeOptions = computed(() => [
    {
      value: 'all',
      icon: '🌍',
      label: t('monitors.network_scope.all'),
      desc: t('monitors.network_scope.all_desc'),
    },
    {
      value: 'internal',
      icon: '🏠',
      label: t('monitors.network_scope.internal'),
      desc: t('monitors.network_scope.internal_desc'),
    },
    {
      value: 'external',
      icon: '☁️',
      label: t('monitors.network_scope.external'),
      desc: t('monitors.network_scope.external_desc'),
    },
  ])

  async function setNetworkScope(scope) {
    if (!monitorRef.value || monitorRef.value.network_scope === scope) return
    const prev = monitorRef.value.network_scope
    monitorRef.value.network_scope = scope
    try {
      await monitorsApi.update(monitorRef.value.id, { network_scope: scope })
    } catch {
      monitorRef.value.network_scope = prev
    }
  }

  return {
    toggleSchemaDrift,
    acceptSchemaBaseline,
    resetSchemaBaseline,
    patchTags,
    networkScopeOptions,
    setNetworkScope,
  }
}
