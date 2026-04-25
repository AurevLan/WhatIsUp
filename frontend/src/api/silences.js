import api from './client'

export const silencesApi = {
  list: () => api.get('/silences/'),
  create: (data) => api.post('/silences/', data),
  update: (id, data) => api.patch(`/silences/${id}`, data),
  delete: (id) => api.delete(`/silences/${id}`),
}
