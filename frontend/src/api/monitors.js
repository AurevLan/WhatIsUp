import api from './client'

export const monitorsApi = {
  list: (params = {}) => api.get('/monitors/', { params }),
  get: (id) => api.get(`/monitors/${id}`),
  create: (data) => api.post('/monitors/', data),
  update: (id, data) => api.patch(`/monitors/${id}`, data),
  delete: (id) => api.delete(`/monitors/${id}`),
  results: (id, params = {}) => api.get(`/monitors/${id}/results`, { params }),
  uptime: (id, periodHours = 24) => api.get(`/monitors/${id}/uptime`, { params: { period_hours: periodHours } }),
  incidents: (id, params = {}) => api.get(`/monitors/${id}/incidents`, { params }),
}

export const groupsApi = {
  list: () => api.get('/groups/'),
  get: (id) => api.get(`/groups/${id}`),
  create: (data) => api.post('/groups/', data),
  update: (id, data) => api.patch(`/groups/${id}`, data),
  delete: (id) => api.delete(`/groups/${id}`),
  monitors: (id) => api.get(`/groups/${id}/monitors`),
}
