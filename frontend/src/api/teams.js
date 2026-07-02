import api from './client'

export const teamsApi = {
  list: () => api.get('/teams/'),
  get: (id) => api.get(`/teams/${id}`),
  create: (data, config = {}) => api.post('/teams/', data, config),
  update: (id, data, config = {}) => api.patch(`/teams/${id}`, data, config),
  delete: (id, config = {}) => api.delete(`/teams/${id}`, config),
  listMembers: (id) => api.get(`/teams/${id}/members`),
  addMember: (id, data, config = {}) => api.post(`/teams/${id}/members`, data, config),
  updateMember: (teamId, userId, data, config = {}) => api.patch(`/teams/${teamId}/members/${userId}`, data, config),
  removeMember: (teamId, userId, config = {}) => api.delete(`/teams/${teamId}/members/${userId}`, config),
}
