import api from './client'

export const monitorsApi = {
  list: (params = {}) => api.get('/monitors/', { params }),
  get: (id) => api.get(`/monitors/${id}`),
  create: (data) => api.post('/monitors/', data),
  update: (id, data) => api.patch(`/monitors/${id}`, data),
  delete: (id) => api.delete(`/monitors/${id}`),
  results: (id, params = {}) => api.get(`/monitors/${id}/results`, { params }),
  uptime: (id, periodHours = 24) => api.get(`/monitors/${id}/uptime`, { params: { period_hours: periodHours } }),
  incidents: (id, params = {}) => api.get(`/monitors/${id}/incidents`, { params }),
  probeStatus: (id) => api.get(`/monitors/${id}/probes`),
  percentiles: (id, params) => api.get(`/monitors/${id}/percentiles`, { params }),
  bulkAction: (payload) => api.post('/monitors/bulk', payload),
  getPostmortem: (monitorId, incidentId) => api.get(`/monitors/${monitorId}/incidents/${incidentId}/postmortem`),
  // Dependencies
  listDependencies: (id) => api.get(`/monitors/${id}/dependencies`),
  addDependency: (id, data) => api.post(`/monitors/${id}/dependencies`, data),
  removeDependency: (id, depId) => api.delete(`/monitors/${id}/dependencies/${depId}`),
  // DNS baseline
  acceptDnsBaseline: (id) => api.post(`/monitors/${id}/dns-baseline/accept`),
  resetDnsBaseline: (id, type = 'all') => api.delete(`/monitors/${id}/dns-baseline`, { params: { type } }),
  // Schema baseline
  acceptSchemaBaseline: (id) => api.post(`/monitors/${id}/schema-baseline/accept`),
  resetSchemaBaseline: (id) => api.delete(`/monitors/${id}/schema-baseline`),
  // Composite members
  listCompositeMembers: (id) => api.get(`/monitors/${id}/composite-members`),
  addCompositeMember: (id, data) => api.post(`/monitors/${id}/composite-members`, data),
  updateCompositeMember: (id, memberId, data) => api.patch(`/monitors/${id}/composite-members/${memberId}`, data),
  removeCompositeMember: (id, memberId) => api.delete(`/monitors/${id}/composite-members/${memberId}`),
}

export async function triggerCheck(monitorId) {
  const res = await api.post(`/monitors/${monitorId}/trigger-check`)
  return res.data
}

export async function getSlaReport(monitorId, from, to) {
  const params = { from }
  if (to) params.to = to
  const res = await api.get(`/monitors/${monitorId}/report`, { params })
  return res.data
}

export async function listAnnotations(monitorId) {
  const res = await api.get(`/monitors/${monitorId}/annotations`)
  return res.data
}

export async function createAnnotation(monitorId, payload) {
  const res = await api.post(`/monitors/${monitorId}/annotations`, payload)
  return res.data
}

export async function deleteAnnotation(monitorId, annotationId) {
  await api.delete(`/monitors/${monitorId}/annotations/${annotationId}`)
}

export async function getSlo(monitorId) {
  const res = await api.get(`/monitors/${monitorId}/slo`)
  return res.data
}

export const groupsApi = {
  list: () => api.get('/groups/'),
  get: (id) => api.get(`/groups/${id}`),
  create: (data) => api.post('/groups/', data),
  update: (id, data) => api.patch(`/groups/${id}`, data),
  delete: (id) => api.delete(`/groups/${id}`),
  monitors: (id) => api.get(`/groups/${id}/monitors`),
}
