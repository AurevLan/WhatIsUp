import api from './client'

export const probesApi = {
  list: () => api.get('/probes/'),
  register: (data) => api.post('/probes/register', data),
  get: (id) => api.get(`/probes/${id}`),
  update: (id, data) => api.patch(`/probes/${id}`, data),
  setActive: (id, isActive, config = {}) => api.patch(`/probes/${id}`, { is_active: isActive }, config),
  remove: (id, config = {}) => api.delete(`/probes/${id}`, config),
  incidentTimeline: (id, days = 7) => api.get(`/probes/${id}/incident-timeline`, { params: { days } }),
  stats: () => api.get('/probes/stats'),
}
