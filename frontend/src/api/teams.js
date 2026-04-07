import api from './client'

export const teamsApi = {
  list: () => api.get('/teams/'),
  get: (id) => api.get(`/teams/${id}`),
  create: (data) => api.post('/teams/', data),
  update: (id, data) => api.patch(`/teams/${id}`, data),
  delete: (id) => api.delete(`/teams/${id}`),
  listMembers: (id) => api.get(`/teams/${id}/members`),
  addMember: (id, data) => api.post(`/teams/${id}/members`, data),
  updateMember: (teamId, userId, data) => api.patch(`/teams/${teamId}/members/${userId}`, data),
  removeMember: (teamId, userId) => api.delete(`/teams/${teamId}/members/${userId}`),
}
