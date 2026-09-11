import client from './client.js'

export const metricsApi = {
  push: (monitorId, payload) => client.post(`/metrics/${monitorId}`, payload),
  list: (monitorId, params = {}) => client.get(`/metrics/${monitorId}`, { params }),
  summary: (monitorId, params = {}) => client.get(`/metrics/${monitorId}/summary`, { params }),
  // C-1 — the series registry. Read from it rather than derived from the points
  // so series that have gone quiet still show up — useful to spot a dead
  // pusher even though nothing can alert on it directly (plan cap v2, 6f/C1
  // cut pushed-metric alerting; ingestion and correlation stay).
  series: (monitorId, params = {}) => client.get(`/metrics/${monitorId}/series`, { params }),
}
