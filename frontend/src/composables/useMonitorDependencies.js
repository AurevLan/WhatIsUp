// Monitor list for MonitorDetailView's dependency edge picker
// (rendered by `<MonitorDependencies>`).

import { ref } from 'vue'
import { monitorsApi } from '../api/monitors'

export function useMonitorDependencies() {
  const allMonitors = ref([])

  async function loadAllMonitors() {
    try {
      const { data } = await monitorsApi.list()
      allMonitors.value = data
    } catch {
      // Silent: dependency picker simply renders empty if list fails.
    }
  }

  return {
    allMonitors,
    loadAllMonitors,
  }
}
