import api from './client'

export const maintenanceApi = {
  list: () => api.get('/maintenance/'),
  create: (data, config = {}) => api.post('/maintenance/', data, config),
  update: (id, data, config = {}) => api.patch(`/maintenance/${id}`, data, config),
  remove: (id, config = {}) => api.delete(`/maintenance/${id}`, config),
}
