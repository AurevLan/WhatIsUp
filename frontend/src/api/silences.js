import api from './client'

export const silencesApi = {
  list: (config = {}) => api.get('/silences/', config),
  create: (data, config = {}) => api.post('/silences/', data, config),
  update: (id, data) => api.patch(`/silences/${id}`, data),
  delete: (id, config = {}) => api.delete(`/silences/${id}`, config),
}
