import api from './client'

export const templatesApi = {
  list: () => api.get('/templates/'),
  get: (id) => api.get(`/templates/${id}`),
  create: (data, config = {}) => api.post('/templates/', data, config),
  update: (id, data, config = {}) => api.patch(`/templates/${id}`, data, config),
  delete: (id, config = {}) => api.delete(`/templates/${id}`, config),
  apply: (id, data, config = {}) => api.post(`/templates/${id}/apply`, data, config),
}
