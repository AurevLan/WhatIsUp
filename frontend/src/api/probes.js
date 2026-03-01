import api from './client'

export const probesApi = {
  list: () => api.get('/probes/'),
  register: (data) => api.post('/probes/register', data),
  get: (id) => api.get(`/probes/${id}`),
  update: (id, data) => api.patch(`/probes/${id}`, data),
  deactivate: (id) => api.delete(`/probes/${id}`),
}
