import client from './client.js'

export const metricsApi = {
  push: (monitorId, payload) => client.post(`/metrics/${monitorId}`, payload),
  list: (monitorId, params = {}) => client.get(`/metrics/${monitorId}`, { params }),
  summary: (monitorId, params = {}) => client.get(`/metrics/${monitorId}/summary`, { params }),
  // C-1 — the series registry. Read from it rather than derived from the points
  // so series that have gone quiet still show up, which is exactly what someone
  // configuring a `metric_absent` rule needs to pick from.
  series: (monitorId, params = {}) => client.get(`/metrics/${monitorId}/series`, { params }),
}
