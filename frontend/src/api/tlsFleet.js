import api from './client'

export const tlsFleetApi = {
  list: (params = {}) => api.get('/tls-fleet/', { params }),
  exportCsv: (params = {}) =>
    api.get('/tls-fleet/', { params: { ...params, fmt: 'csv' }, responseType: 'blob' }),
}
