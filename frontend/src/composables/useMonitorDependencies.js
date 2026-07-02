// Dependency picker data + composite-monitor membership CRUD for
// MonitorDetailView.
//
// `allMonitors` feeds the dependency edge picker (rendered by
// `<MonitorDependencies>`) and the composite member dropdown. `compositeMembers`
// is loaded lazily — only when the current monitor's `check_type` is composite.

import { computed, ref } from 'vue'
import { monitorsApi } from '../api/monitors'
import { useToast } from './useToast'

export function useMonitorDependencies(monitorRef) {
  const { error: toastError } = useToast()

  const allMonitors = ref([])
  const compositeMembers = ref([])
  const newMember = ref({ monitor_id: '', role: '', weight: 1 })

  function memberName(monitorId) {
    const m = allMonitors.value.find((x) => x.id === monitorId)
    return m ? m.name : monitorId.slice(0, 8)
  }

  const availableMonitors = computed(() =>
    allMonitors.value.filter(
      (m) =>
        m.id !== monitorRef.value?.id &&
        m.check_type !== 'composite' &&
        !compositeMembers.value.some((cm) => cm.monitor_id === m.id),
    ),
  )

  async function loadAllMonitors() {
    try {
      const { data } = await monitorsApi.list()
      allMonitors.value = data
    } catch {
      // Silent: dependency picker simply renders empty if list fails.
    }
  }

  async function loadCompositeMembers() {
    if (monitorRef.value?.check_type !== 'composite') return
    try {
      const { data } = await monitorsApi.listCompositeMembers(monitorRef.value.id)
      compositeMembers.value = data
    } catch {
      // Silent: empty list on failure.
    }
  }

  async function addCompositeMember() {
    if (!newMember.value.monitor_id || !monitorRef.value) return
    try {
      const { data } = await monitorsApi.addCompositeMember(monitorRef.value.id, {
        monitor_id: newMember.value.monitor_id,
        role: newMember.value.role || null,
        weight: newMember.value.weight || 1,
      }, { skipErrorToast: true })
      compositeMembers.value.push(data)
      newMember.value = { monitor_id: '', role: '', weight: 1 }
    } catch (e) {
      toastError(e.response?.data?.detail || 'Error adding member')
    }
  }

  async function removeCompositeMember(memberId) {
    if (!monitorRef.value) return
    try {
      await monitorsApi.removeCompositeMember(monitorRef.value.id, memberId, { skipErrorToast: true })
      compositeMembers.value = compositeMembers.value.filter((m) => m.id !== memberId)
    } catch (e) {
      toastError(e.response?.data?.detail || 'Error removing member')
    }
  }

  return {
    allMonitors,
    compositeMembers,
    newMember,
    availableMonitors,
    memberName,
    loadAllMonitors,
    loadCompositeMembers,
    addCompositeMember,
    removeCompositeMember,
  }
}
