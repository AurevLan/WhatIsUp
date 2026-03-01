import api from './client'

export const probesApi = {
  list: () => api.get('/probes/'),
  register: (data) => api.post('/probes/register', data),
  get: (id) => api.get(`/probes/${id}`),
  deactivate: (id) => api.delete(`/probes/${id}`),
}
