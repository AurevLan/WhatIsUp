import api from './client'

export const incidentGroupsApi = {
  list: (params = {}) => api.get('/incident-groups/', { params }),
  get: (id) => api.get(`/incident-groups/${id}`),
}
