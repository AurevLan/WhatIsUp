import api from './client.js'

export const apiKeysApi = {
  list: () => api.get('/api-keys/'),
  create: (data) => api.post('/api-keys/', data),
  revoke: (id) => api.delete(`/api-keys/${id}`),
}
