import api from './client'

export const maintenanceApi = {
  list: () => api.get('/maintenance/'),
  create: (data) => api.post('/maintenance/', data),
  update: (id, data) => api.patch(`/maintenance/${id}`, data),
  remove: (id) => api.delete(`/maintenance/${id}`),
}
