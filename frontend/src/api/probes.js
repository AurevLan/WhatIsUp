import api from './client'

export const probesApi = {
  list: (config = {}) => api.get('/probes/', config),
  register: (data, config = {}) => api.post('/probes/register', data, config),
  get: (id) => api.get(`/probes/${id}`),
  update: (id, data, config = {}) => api.patch(`/probes/${id}`, data, config),
  setActive: (id, isActive, config = {}) => api.patch(`/probes/${id}`, { is_active: isActive }, config),
  remove: (id, config = {}) => api.delete(`/probes/${id}`, config),
  incidentTimeline: (id, days = 7) => api.get(`/probes/${id}/incident-timeline`, { params: { days } }),
  stats: (config = {}) => api.get('/probes/stats', config),
}
