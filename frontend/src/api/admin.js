import api from './client'

export const adminApi = {
  listUsers: () => api.get('/admin/users'),
  createUser: (data) => api.post('/admin/users', data),
  updateUser: (id, data) => api.patch(`/admin/users/${id}`, data),
  deleteUser: (id) => api.delete(`/admin/users/${id}`),
  listMonitors: () => api.get('/admin/monitors'),
  // Probe groups
  listProbeGroups: () => api.get('/admin/probe-groups'),
  createProbeGroup: (data) => api.post('/admin/probe-groups', data),
  updateProbeGroup: (id, data) => api.patch(`/admin/probe-groups/${id}`, data),
  deleteProbeGroup: (id) => api.delete(`/admin/probe-groups/${id}`),
  addProbesToGroup: (groupId, probeIds) => api.post(`/admin/probe-groups/${groupId}/probes`, { probe_ids: probeIds }),
  removeProbeFromGroup: (groupId, probeId) => api.delete(`/admin/probe-groups/${groupId}/probes/${probeId}`),
  grantGroupAccess: (groupId, userIds) => api.post(`/admin/probe-groups/${groupId}/users`, { user_ids: userIds }),
  revokeGroupAccess: (groupId, userId) => api.delete(`/admin/probe-groups/${groupId}/users/${userId}`),
  // OIDC settings
  getOidcSettings: () => api.get('/admin/settings/oidc'),
  updateOidcSettings: (data) => api.put('/admin/settings/oidc', data),
}
