import api from './client'

export const adminApi = {
  listUsers: () => api.get('/admin/users'),
  createUser: (data, config = {}) => api.post('/admin/users', data, config),
  updateUser: (id, data, config = {}) => api.patch(`/admin/users/${id}`, data, config),
  deleteUser: (id) => api.delete(`/admin/users/${id}`),
  listMonitors: () => api.get('/admin/monitors'),
  // Probe groups
  listProbeGroups: () => api.get('/admin/probe-groups'),
  createProbeGroup: (data, config = {}) => api.post('/admin/probe-groups', data, config),
  updateProbeGroup: (id, data, config = {}) => api.patch(`/admin/probe-groups/${id}`, data, config),
  deleteProbeGroup: (id) => api.delete(`/admin/probe-groups/${id}`),
  addProbesToGroup: (groupId, probeIds, config = {}) => api.post(`/admin/probe-groups/${groupId}/probes`, { probe_ids: probeIds }, config),
  removeProbeFromGroup: (groupId, probeId, config = {}) => api.delete(`/admin/probe-groups/${groupId}/probes/${probeId}`, config),
  grantGroupAccess: (groupId, userIds, config = {}) => api.post(`/admin/probe-groups/${groupId}/users`, { user_ids: userIds }, config),
  revokeGroupAccess: (groupId, userId, config = {}) => api.delete(`/admin/probe-groups/${groupId}/users/${userId}`, config),
  // OIDC settings
  getOidcSettings: (config = {}) => api.get('/admin/settings/oidc', config),
  updateOidcSettings: (data, config = {}) => api.put('/admin/settings/oidc', data, config),
}
