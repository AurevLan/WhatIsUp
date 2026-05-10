// Annotations CRUD for MonitorDetailView. Annotations mark deployments and
// interventions on the response-time chart timeline.

import { ref } from 'vue'
import {
  createAnnotation,
  deleteAnnotation,
  listAnnotations,
} from '../api/monitors'

export function useMonitorAnnotations(monitorIdRef) {
  const annotations = ref([])
  const showForm = ref(false)
  const newAnnotation = ref({ content: '', annotated_at: '' })

  async function load() {
    try {
      annotations.value = await listAnnotations(monitorIdRef.value)
    } catch {
      annotations.value = []
    }
  }

  async function add() {
    if (!newAnnotation.value.content || !newAnnotation.value.annotated_at) return
    await createAnnotation(monitorIdRef.value, {
      content: newAnnotation.value.content,
      annotated_at: new Date(newAnnotation.value.annotated_at).toISOString(),
    })
    newAnnotation.value = { content: '', annotated_at: '' }
    showForm.value = false
    await load()
  }

  async function remove(id) {
    await deleteAnnotation(monitorIdRef.value, id)
    await load()
  }

  return { annotations, showForm, newAnnotation, load, add, remove }
}
