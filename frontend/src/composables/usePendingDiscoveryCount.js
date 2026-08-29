import { ref, onMounted, onUnmounted } from 'vue'
import { discoveryApi } from '../api/discovery'

// plan E, E-3 — nav badge for "N proposals waiting for review", same visual
// mechanic as the other sidebar badges (`downCount`/`openIncidentCount` in
// AppLayout — a plain :badge on NavLink, which itself renders nothing for a
// falsy value, so zero already means "no badge" with no extra logic here).
//
// Unlike those two, discovery proposals aren't part of the WebSocket
// dashboard stream, so the refresh mechanic is a lightweight poll instead —
// same "poll while mounted" shape as the scan-now feedback loop (plan E,
// E-1). A user without discovery access (or a network hiccup) must see no
// badge, never a crash: any failure collapses to zero.
const POLL_INTERVAL_MS = 30_000

export function usePendingDiscoveryCount() {
  const pendingCount = ref(0)
  let timer = null

  async function refresh() {
    try {
      const { data } = await discoveryApi.services.pendingCount({ skipErrorToast: true })
      pendingCount.value = data?.count ?? 0
    } catch {
      pendingCount.value = 0
    }
  }

  onMounted(() => {
    refresh()
    timer = setInterval(refresh, POLL_INTERVAL_MS)
  })
  onUnmounted(() => {
    if (timer) clearInterval(timer)
  })

  return { pendingCount, refresh }
}
