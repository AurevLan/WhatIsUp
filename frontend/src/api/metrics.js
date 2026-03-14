import client from './client.js'

export const metricsApi = {
  push: (monitorId, payload) => client.post(`/metrics/${monitorId}`, payload),
  list: (monitorId, params = {}) => client.get(`/metrics/${monitorId}`, { params }),
}
