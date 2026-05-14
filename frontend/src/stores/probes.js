import { defineStore } from 'pinia'
import { ref } from 'vue'
import { probesApi } from '../api/probes'

export const useProbesStore = defineStore('probes', () => {
  const probes = ref([])
  const probeMap = ref({})
  const loading = ref(false)
  let fetchPromise = null

  async function fetch({ force = false } = {}) {
    if (!force && probes.value.length > 0) return probes.value
    if (fetchPromise) return fetchPromise
    loading.value = true
    fetchPromise = probesApi
      .list()
      .then(({ data }) => {
        probes.value = data
        probeMap.value = Object.fromEntries(data.map(p => [p.id, p]))
        return data
      })
      .catch(() => {
        // Graceful fallback — non-superadmin users get 403.
        probes.value = []
        probeMap.value = {}
        return []
      })
      .finally(() => {
        loading.value = false
        fetchPromise = null
      })
    return fetchPromise
  }

  function reset() {
    probes.value = []
    probeMap.value = {}
    fetchPromise = null
  }

  return { probes, probeMap, loading, fetch, reset }
})
