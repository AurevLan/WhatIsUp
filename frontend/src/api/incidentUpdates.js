import api from './client'

export const incidentUpdatesApi = {
  list: (incidentId) => api.get(`/incidents/${incidentId}/updates`),
  create: (incidentId, data) => api.post(`/incidents/${incidentId}/updates`, data),
  delete: (incidentId, updateId) => api.delete(`/incidents/${incidentId}/updates/${updateId}`),
}
