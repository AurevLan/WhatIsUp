// Runbook editing state for MonitorDetailView.
//
// Owns the edit/preview toggle, draft buffer, and save flow. After a successful
// save the composable mutates `monitor.value.runbook_markdown` in place so the
// view's read-mode block reflects the new content without a refetch.

import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { monitorsApi } from '../api/monitors'
import { renderRunbookMarkdown } from '../lib/runbookMarkdown'
import { useToast } from './useToast'

export function useMonitorRunbook(monitorRef) {
  const { t } = useI18n()
  const { error: toastError, success: toastSuccess } = useToast()

  const editing = ref(false)
  const draft = ref('')
  const saving = ref(false)

  const renderedHtml = computed(() =>
    renderRunbookMarkdown(monitorRef.value?.runbook_markdown || ''),
  )
  const previewHtml = computed(() => renderRunbookMarkdown(draft.value || ''))

  function startEdit() {
    draft.value = monitorRef.value?.runbook_markdown || ''
    editing.value = true
  }

  function cancelEdit() {
    editing.value = false
    draft.value = ''
  }

  async function save() {
    if (!monitorRef.value) return
    saving.value = true
    try {
      const { data } = await monitorsApi.update(monitorRef.value.id, {
        runbook_markdown: draft.value || null,
      })
      monitorRef.value.runbook_markdown = data.runbook_markdown
      editing.value = false
      toastSuccess(t('runbook.saved'))
    } catch {
      toastError(t('runbook.save_failed'))
    } finally {
      saving.value = false
    }
  }

  return {
    editing,
    draft,
    saving,
    renderedHtml,
    previewHtml,
    startEdit,
    cancelEdit,
    save,
  }
}
