import { ref } from 'vue'
import { discoveryApi } from '../api/discovery'

// plan D, D-3 — "le frontend récupère GET /discovery/services?status=orphaned
// une fois par vue et badge les monitors dont l'id est dans les monitor_id
// retournés. Pas d'enrichissement backend, pas de N+1." One call per view
// mount, a plain Set lookup per row — never a request per monitor.
//
// A user without discovery access (or a network hiccup) must see zero
// badges, never a crash: any failure collapses to an empty Set.
export function useOrphanedMonitors() {
  const orphanedMonitorIds = ref(new Set())

  async function loadOrphanedMonitors() {
    try {
      const { data } = await discoveryApi.services.list(
        { status: 'orphaned' },
        { skipErrorToast: true }
      )
      orphanedMonitorIds.value = new Set(
        (data || []).map((service) => service.monitor_id).filter((id) => id != null)
      )
    } catch {
      orphanedMonitorIds.value = new Set()
    }
  }

  function isOrphaned(monitorId) {
    return orphanedMonitorIds.value.has(monitorId)
  }

  return { orphanedMonitorIds, loadOrphanedMonitors, isOrphaned }
}
