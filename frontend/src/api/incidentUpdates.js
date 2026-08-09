import api from './client'

export const incidentUpdatesApi = {
  list: (incidentId) => api.get(`/incidents/${incidentId}/updates`),
  create: (incidentId, data) => api.post(`/incidents/${incidentId}/updates`, data),
  delete: (incidentId, updateId) => api.delete(`/incidents/${incidentId}/updates/${updateId}`),
  ack: (incidentId, config = {}) => api.post(`/incidents/${incidentId}/ack`, undefined, config),
  unack: (incidentId) => api.post(`/incidents/${incidentId}/unack`),
  bulkAck: (ids) => api.post('/incidents/bulk-ack', { ids }),
  diagnostics: (incidentId, config = {}) => api.get(`/incidents/${incidentId}/diagnostics`, config),
  // C-3 — what the monitor's pushed metrics did around the incident.
  metricCorrelation: (incidentId, config = {}) =>
    api.get(`/incidents/${incidentId}/metric-correlation`, config),
}
