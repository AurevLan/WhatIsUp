import api from './client'

// plan D — discovery sources (D-0) + discovered-service review (D-2/D-3).
export const discoveryApi = {
  sources: {
    list: (config = {}) => api.get('/discovery/sources/', config),
    create: (data, config = {}) => api.post('/discovery/sources/', data, config),
    update: (id, data, config = {}) => api.patch(`/discovery/sources/${id}`, data, config),
    remove: (id, config = {}) => api.delete(`/discovery/sources/${id}`, config),
    // plan E, E-1 — request an out-of-cycle run on the probe's next heartbeat.
    scanNow: (id, config = {}) => api.post(`/discovery/sources/${id}/scan-now`, {}, config),
  },

  services: {
    list: (params = {}, config = {}) => api.get('/discovery/services/', { ...config, params }),
    accept: (id, data, config = {}) => api.post(`/discovery/services/${id}/accept`, data, config),
    dismiss: (id, data, config = {}) => api.post(`/discovery/services/${id}/dismiss`, data, config),
    bulk: (data, config = {}) => api.post('/discovery/services/bulk', data, config),
  },
}
