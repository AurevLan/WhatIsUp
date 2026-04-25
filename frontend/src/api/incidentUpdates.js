import api from './client'

export const incidentUpdatesApi = {
  list: (incidentId) => api.get(`/incidents/${incidentId}/updates`),
  create: (incidentId, data) => api.post(`/incidents/${incidentId}/updates`, data),
  delete: (incidentId, updateId) => api.delete(`/incidents/${incidentId}/updates/${updateId}`),
  ack: (incidentId) => api.post(`/incidents/${incidentId}/ack`),
  unack: (incidentId) => api.post(`/incidents/${incidentId}/unack`),
  bulkAck: (ids) => api.post('/incidents/bulk-ack', { ids }),
}
